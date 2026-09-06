"""Snapshot, restore, and derived-state deletion for Agent memory."""

import time
from typing import Any, Dict, Iterable, List

from ai_team_team.core.memory import (
    AgentMemoryCard,
    AgentMemorySegment,
    MemoryIndexStatus,
    RetainedMemoryReference,
    SystemMemoryEvent,
)


class MemoryStateMixin:
    def snapshot(self) -> Dict[str, List[Dict[str, Any]]]:
        with self._lock:
            return {
                "memory_events": [
                    event.model_dump(mode="json")
                    for event in sorted(self.events.values(), key=lambda item: item.sequence)
                ],
                "memory_segments": [
                    segment.model_dump(mode="json") for segment in self.segments.values()
                ],
                "memory_cards": [
                    card.model_dump(mode="json") for card in self.cards.values()
                ],
                "memory_references": [
                    reference.model_dump(mode="json")
                    for reference in self.references.values()
                ],
            }

    def restore(
        self,
        events: Iterable[Dict[str, Any]],
        segments: Iterable[Dict[str, Any]],
        cards: Iterable[Dict[str, Any]],
        references: Iterable[Dict[str, Any]],
    ) -> None:
        parsed_events = [
            SystemMemoryEvent.model_validate(item, strict=False) for item in events
        ]
        parsed_segments = [
            AgentMemorySegment.model_validate(item, strict=False)
            for item in segments
        ]
        parsed_cards = [
            AgentMemoryCard.model_validate(item, strict=False) for item in cards
        ]
        parsed_references = [
            RetainedMemoryReference.model_validate(item, strict=False)
            for item in references
        ]
        with self._lock:
            self.events = {item.event_id: item for item in parsed_events}
            self.segments = {item.segment_id: item for item in parsed_segments}
            self.cards = {item.memory_id: item for item in parsed_cards}
            self.references = {
                item.reference_id: item for item in parsed_references
            }
            self._event_ids_by_turn = {}
            for event in sorted(parsed_events, key=lambda item: item.sequence):
                if event.turn_id:
                    self._event_ids_by_turn.setdefault(event.turn_id, []).append(
                        event.event_id
                    )
            self._card_id_by_turn = {
                card.turn_id: card.memory_id for card in parsed_cards
            }
            self._recalled_by_turn = {}
            self._sequence = max((item.sequence for item in parsed_events), default=0)
            self._fts_sync_active = False
            for segment in self.segments.values():
                if segment.status is MemoryIndexStatus.PROCESSING:
                    segment.status = MemoryIndexStatus.PENDING
                    segment.updated_at = time.time()

    def remove_agent_derived_state(self, agent_id: str) -> Dict[str, set[str]]:
        """Removes deletable derived memory while leaving journal events intact."""
        if not self.manager.config.episodic_memory.enabled:
            self._fts_sync_active = False
        segment_ids = {
            item.segment_id for item in self.segments.values() if item.agent_id == agent_id
        }
        card_ids = {
            item.memory_id for item in self.cards.values() if item.agent_id == agent_id
        }
        reference_ids = {
            item.reference_id for item in self.references.values() if item.agent_id == agent_id
        }
        for identifier in segment_ids:
            self.segments.pop(identifier, None)
        for identifier in card_ids:
            self.cards.pop(identifier, None)
        for identifier in reference_ids:
            self.references.pop(identifier, None)
        self._card_id_by_turn = {
            turn_id: memory_id
            for turn_id, memory_id in self._card_id_by_turn.items()
            if memory_id not in card_ids
        }
        return {
            "segments": segment_ids,
            "cards": card_ids,
            "references": reference_ids,
        }
