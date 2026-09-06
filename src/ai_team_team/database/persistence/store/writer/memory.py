"""Append-only Journal, derived memory, and FTS5 writes."""

from typing import Any, Dict, Iterable

from sqlalchemy import text

from ai_team_team.database.models import (
    AgentMemoryCardModel,
    AgentMemorySegmentModel,
    MemoryCardSourceEventModel,
    MemoryCardTagModel,
    RetainedMemoryReferenceModel,
    SystemMemoryEventModel,
)


class MemoryWriteMixin:
    @staticmethod
    def _write_memory_events(
        session: Any,
        events: Iterable[Dict[str, Any]],
        *,
        full: bool,
    ) -> None:
        events = list(events)
        if full:
            persisted_ids = {
                value
                for (value,) in session.query(SystemMemoryEventModel.event_id).all()
            }
            snapshot_ids = {event["event_id"] for event in events}
            missing = sorted(persisted_ids - snapshot_ids)
            if missing:
                raise ValueError(
                    "A full snapshot cannot omit immutable journal events: "
                    + ", ".join(missing)
                )
        for event in events:
            existing = session.get(SystemMemoryEventModel, event["event_id"])
            values = {
                "event_id": event["event_id"],
                "sequence": event["sequence"],
                "event_type": event["event_type"],
                "agent_id": event.get("agent_id"),
                "agent_name_snapshot": event.get("agent_name_snapshot"),
                "team_id": event.get("team_id"),
                "discussion_id": event.get("discussion_id"),
                "turn_id": event.get("turn_id"),
                "role": event.get("role"),
                "payload": event.get("payload", {}),
                "redacted": int(event.get("redacted", False)),
                "created_at": event["created_at"],
            }
            if existing is None:
                session.add(SystemMemoryEventModel(**values))
                continue
            current = {
                "event_id": existing.event_id,
                "sequence": existing.sequence,
                "event_type": existing.event_type,
                "agent_id": existing.agent_id,
                "agent_name_snapshot": existing.agent_name_snapshot,
                "team_id": existing.team_id,
                "discussion_id": existing.discussion_id,
                "turn_id": existing.turn_id,
                "role": existing.role,
                "payload": existing.payload,
                "redacted": existing.redacted,
                "created_at": existing.created_at,
            }
            if current != values:
                raise ValueError(
                    f"Immutable journal event {event['event_id']!r} was modified."
                )

    @staticmethod
    def _write_memory_segments(
        session: Any, segments: Iterable[Dict[str, Any]]
    ) -> None:
        for segment in segments:
            session.merge(
                AgentMemorySegmentModel(
                    segment_id=segment["segment_id"],
                    agent_id=segment["agent_id"],
                    turn_id=segment["turn_id"],
                    origin_team_id=segment.get("origin_team_id"),
                    discussion_id=segment.get("discussion_id"),
                    recall_content=segment["recall_content"],
                    content_sha256=segment["content_sha256"],
                    status=segment["status"],
                    attempts=segment["attempts"],
                    last_error_kind=segment.get("last_error_kind"),
                    created_at=segment["created_at"],
                    updated_at=segment["updated_at"],
                )
            )
            session.query(MemoryCardSourceEventModel).filter_by(
                segment_id=segment["segment_id"]
            ).delete(synchronize_session=False)
            for index, event_id in enumerate(segment["source_event_ids"]):
                session.add(
                    MemoryCardSourceEventModel(
                        segment_id=segment["segment_id"],
                        event_id=event_id,
                        sequence=index,
                    )
                )

    @staticmethod
    def _write_memory_cards(
        session: Any, cards: Iterable[Dict[str, Any]]
    ) -> None:
        for card in cards:
            session.merge(
                AgentMemoryCardModel(
                    memory_id=card["memory_id"],
                    agent_id=card["agent_id"],
                    turn_id=card["turn_id"],
                    title=card["title"],
                    summary=card["summary"],
                    origin_team_id=card.get("origin_team_id"),
                    discussion_id=card.get("discussion_id"),
                    segment_id=card["segment_id"],
                    status=card["status"],
                    version=card["version"],
                    created_at=card["created_at"],
                    updated_at=card["updated_at"],
                )
            )
            session.query(MemoryCardTagModel).filter_by(
                memory_id=card["memory_id"]
            ).delete(synchronize_session=False)
            for index, tag in enumerate(card["tags"]):
                session.add(
                    MemoryCardTagModel(
                        memory_id=card["memory_id"],
                        tag=tag,
                        sequence=index,
                    )
                )

    @staticmethod
    def _write_memory_references(
        session: Any, references: Iterable[Dict[str, Any]]
    ) -> None:
        for reference in references:
            session.merge(
                RetainedMemoryReferenceModel(
                    reference_id=reference["reference_id"],
                    agent_id=reference["agent_id"],
                    memory_id=reference["memory_id"],
                    note=reference["note"],
                    created_at=reference["created_at"],
                )
            )

    @staticmethod
    def _sync_memory_fts(session: Any, snapshot: Dict[str, Any]) -> None:
        cards = list(snapshot.get("memory_cards", ()))
        enabled = bool(snapshot.get("episodic_memory_enabled", False))
        exists = session.execute(
            text(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='agent_memory_cards_fts'"
            )
        ).first()
        if not enabled:
            if exists:
                session.execute(text("DROP TABLE agent_memory_cards_fts"))
            return
        try:
            session.execute(
                text(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS agent_memory_cards_fts "
                    "USING fts5(memory_id UNINDEXED, agent_id UNINDEXED, "
                    "title, summary, tags)"
                )
            )
        except Exception as exc:
            raise RuntimeError(
                "Selective episodic memory requires SQLite FTS5 support."
            ) from exc
        if snapshot.get("full"):
            session.execute(text("DELETE FROM agent_memory_cards_fts"))
        for card in cards:
            session.execute(
                text("DELETE FROM agent_memory_cards_fts WHERE memory_id = :memory_id"),
                {"memory_id": card["memory_id"]},
            )
            if card["status"] == "active":
                session.execute(
                    text(
                        "INSERT INTO agent_memory_cards_fts "
                        "(memory_id, agent_id, title, summary, tags) "
                        "VALUES (:memory_id, :agent_id, :title, :summary, :tags)"
                    ),
                    {
                        "memory_id": card["memory_id"],
                        "agent_id": card["agent_id"],
                        "title": card["title"],
                        "summary": card["summary"],
                        "tags": " ".join(card["tags"]),
                    },
                )
