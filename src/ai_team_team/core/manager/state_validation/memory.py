"""Strict validation for journal and Agent-owned episodic memory state."""

from typing import Any, Dict, Iterable, Set

from ...exceptions import StateRestoreError
from ...memory import (
    AgentMemoryCard,
    AgentMemorySegment,
    MemoryIndexStatus,
    RetainedMemoryReference,
    SystemMemoryEvent,
)
from ...memory.sanitization import content_digest, normalize_tags, render_recall_content


def _unique(values: Iterable[str], label: str) -> Set[str]:
    items = list(values)
    if len(items) != len(set(items)):
        raise StateRestoreError(f"Persisted {label} contain duplicate identifiers.")
    return set(items)


def validate_memory_state(
    payload: Any,
    agent_ids: Set[str],
    team_ids: Set[str],
) -> None:
    """Validates append-only events and every derived ownership/reference edge."""
    try:
        events = [
            SystemMemoryEvent.model_validate(item, strict=False)
            for item in payload.memory_events
        ]
        segments = [
            AgentMemorySegment.model_validate(item, strict=False)
            for item in payload.memory_segments
        ]
        cards = [
            AgentMemoryCard.model_validate(item, strict=False)
            for item in payload.memory_cards
        ]
        references = [
            RetainedMemoryReference.model_validate(item, strict=False)
            for item in payload.memory_references
        ]
    except Exception as exc:
        raise StateRestoreError(f"Invalid persisted memory record: {exc}") from exc

    event_ids = _unique((item.event_id for item in events), "memory events")
    _unique((str(item.sequence) for item in events), "memory event sequences")
    segment_ids = _unique((item.segment_id for item in segments), "memory segments")
    memory_ids = _unique((item.memory_id for item in cards), "Memory Cards")
    _unique((item.reference_id for item in references), "memory references")
    _unique((item.turn_id for item in segments), "memory segment turns")
    _unique((item.turn_id for item in cards), "Memory Card turns")

    event_map: Dict[str, SystemMemoryEvent] = {item.event_id: item for item in events}
    segment_map = {item.segment_id: item for item in segments}
    card_map = {item.memory_id: item for item in cards}

    for segment in segments:
        if segment.agent_id not in agent_ids:
            raise StateRestoreError(
                f"Memory segment {segment.segment_id!r} references a missing Agent."
            )
        if segment.origin_team_id is not None and segment.origin_team_id not in team_ids:
            raise StateRestoreError(
                f"Memory segment {segment.segment_id!r} references a missing AgentTeam."
            )
        if not segment.source_event_ids or len(segment.source_event_ids) != len(
            set(segment.source_event_ids)
        ):
            raise StateRestoreError(
                f"Memory segment {segment.segment_id!r} has missing or duplicate source events."
            )
        source_events = []
        for event_id in segment.source_event_ids:
            event = event_map.get(event_id)
            if event is None:
                raise StateRestoreError(
                    f"Memory segment {segment.segment_id!r} references missing event {event_id!r}."
                )
            if event.agent_id != segment.agent_id or event.turn_id != segment.turn_id:
                raise StateRestoreError(
                    f"Memory segment {segment.segment_id!r} crosses an Agent or turn boundary."
                )
            source_events.append(event)
        if [event.sequence for event in source_events] != sorted(
            event.sequence for event in source_events
        ):
            raise StateRestoreError(
                f"Memory segment {segment.segment_id!r} has out-of-order source events."
            )
        started = [
            event for event in source_events if event.event_type == "agent_turn_started"
        ]
        finished = [
            event for event in source_events if event.event_type == "agent_turn_finished"
        ]
        if len(started) != 1 or len(finished) != 1:
            raise StateRestoreError(
                f"Memory segment {segment.segment_id!r} must contain one start and one terminal event."
            )
        if source_events[0] is not started[0] or source_events[-1] is not finished[0]:
            raise StateRestoreError(
                f"Memory segment {segment.segment_id!r} has invalid turn boundaries."
            )
        expected_source_ids = [
            event.event_id
            for event in sorted(events, key=lambda item: item.sequence)
            if event.agent_id == segment.agent_id
            and event.turn_id == segment.turn_id
            and started[0].sequence <= event.sequence <= finished[0].sequence
        ]
        if segment.source_event_ids != expected_source_ids:
            raise StateRestoreError(
                f"Memory segment {segment.segment_id!r} omits or adds turn events."
            )
        terminal_status = finished[0].payload.get("status")
        if terminal_status not in {"completed", "incomplete"}:
            raise StateRestoreError(
                f"Memory segment {segment.segment_id!r} has an invalid terminal status."
            )
        for boundary_event in (started[0], finished[0]):
            if (
                boundary_event.team_id != segment.origin_team_id
                or boundary_event.discussion_id != segment.discussion_id
            ):
                raise StateRestoreError(
                    f"Memory segment {segment.segment_id!r} has inconsistent turn provenance."
                )
        rendered = render_recall_content(source_events)
        if rendered != segment.recall_content or content_digest(rendered) != segment.content_sha256:
            raise StateRestoreError(
                f"Memory segment {segment.segment_id!r} failed deterministic-content validation."
            )

    for card in cards:
        source_segment = segment_map.get(card.segment_id)
        if source_segment is None or card.segment_id not in segment_ids:
            raise StateRestoreError(
                f"Memory Card {card.memory_id!r} references a missing segment."
            )
        if card.agent_id not in agent_ids or card.agent_id != source_segment.agent_id:
            raise StateRestoreError(
                f"Memory Card {card.memory_id!r} has an invalid Agent owner."
            )
        if card.turn_id != source_segment.turn_id:
            raise StateRestoreError(
                f"Memory Card {card.memory_id!r} crosses a turn boundary."
            )
        if source_segment.status is not MemoryIndexStatus.INDEXED:
            raise StateRestoreError(
                f"Memory Card {card.memory_id!r} references a segment that is not indexed."
            )
        if (
            card.origin_team_id != source_segment.origin_team_id
            or card.discussion_id != source_segment.discussion_id
        ):
            raise StateRestoreError(
                f"Memory Card {card.memory_id!r} has inconsistent provenance."
            )
        if not card.title.strip() or not card.summary.strip():
            raise StateRestoreError(
                f"Memory Card {card.memory_id!r} has empty display metadata."
            )
        try:
            normalized = normalize_tags(
                card.tags,
                maximum=payload.config.episodic_memory.max_tags_per_card,
            )
        except Exception as exc:
            raise StateRestoreError(
                f"Memory Card {card.memory_id!r} has invalid tags."
            ) from exc
        if normalized != card.tags:
            raise StateRestoreError(
                f"Memory Card {card.memory_id!r} has non-normalized tags."
            )

    card_segment_ids = {card.segment_id for card in cards}
    for segment in segments:
        if (
            segment.status is MemoryIndexStatus.INDEXED
            and segment.segment_id not in card_segment_ids
        ):
            raise StateRestoreError(
                f"Indexed memory segment {segment.segment_id!r} has no Memory Card."
            )

    for reference in references:
        referenced_card = card_map.get(reference.memory_id)
        if reference.agent_id not in agent_ids or referenced_card is None:
            raise StateRestoreError(
                f"Memory reference {reference.reference_id!r} has a missing owner or card."
            )
        if referenced_card.agent_id != reference.agent_id:
            raise StateRestoreError(
                f"Memory reference {reference.reference_id!r} crosses Agent ownership."
            )
        if referenced_card.status.value != "active":
            raise StateRestoreError(
                f"Memory reference {reference.reference_id!r} points to a forgotten card."
            )
        if not reference.note.strip():
            raise StateRestoreError(
                f"Memory reference {reference.reference_id!r} has an empty note."
            )

    # Historical journal identities intentionally have no foreign keys: permanent
    # Agent deletion retains immutable events and their identity snapshots.
    if any(event.agent_id is not None and not event.agent_name_snapshot for event in events):
        raise StateRestoreError(
            "Every Agent-owned journal event must retain an Agent name snapshot."
        )
