"""Append-only journal and Agent-turn segmentation."""

import time
import uuid
from typing import TYPE_CHECKING, Any, Dict, Optional

from ai_team_team.core.memory import AgentMemorySegment, SystemMemoryEvent
from ai_team_team.core.memory.sanitization import (
    content_digest,
    render_recall_content,
    sanitize_message_payload,
)
from ai_team_team.core.response import AgentTurnResult

if TYPE_CHECKING:
    from ai_team_team.core.agent import Agent
    from ai_team_team.core.team import AgentTeam


class MemoryJournalMixin:
    def record_event(
        self,
        event_type: str,
        *,
        agent: Optional["Agent"] = None,
        team: Optional["AgentTeam"] = None,
        invocation_id: Optional[str] = None,
        source_execution_id: Optional[str] = None,
        source_chat_message_id: Optional[str] = None,
        discussion_id: Optional[str] = None,
        turn_id: Optional[str] = None,
        role: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        redacted: bool = False,
        persist: bool = True,
        inherit_context: bool = True,
    ) -> SystemMemoryEvent:
        """Appends one immutable event and records an append-only persistence delta."""
        manager = self.manager
        activity = getattr(manager, "_activity", None)
        executing = activity.current.get() if activity is not None else None
        active = executing if inherit_context else None
        with self._lock:
            self._sequence += 1
            event = SystemMemoryEvent(
                event_id=f"EVT-{uuid.uuid4().hex}",
                sequence=self._sequence,
                event_type=event_type,
                agent_id=agent.agent_id if agent else None,
                agent_name_snapshot=agent.name if agent else None,
                team_id=team.team_id if team else None,
                invocation_id=invocation_id or (active.invocation_id if active is not None else None),
                source_execution_id=source_execution_id,
                source_chat_message_id=source_chat_message_id,
                discussion_id=(
                    discussion_id
                    if discussion_id is not None
                    else (
                        manager._active_discussion_id.get()
                        if inherit_context
                        else None
                    )
                ),
                turn_id=(
                    turn_id
                    if turn_id is not None
                    else (
                        manager._active_agent_turn_id.get()
                        if inherit_context and active is None
                        else None
                    )
                ),
                role=role,
                payload=dict(payload or {}),
                redacted=redacted,
                created_at=time.time(),
            )
            self.events[event.event_id] = event
            if event.turn_id:
                self._event_ids_by_turn.setdefault(event.turn_id, []).append(
                    event.event_id
                )
        if persist and executing is not None and agent is not None and agent.agent_id == executing.agent_id:
            executing.pending_event_ids.add(event.event_id)
        elif persist:
            manager._auto_save(memory_events={event.event_id})
        return event

    def discard_unpersisted_event(self, event_id: str) -> None:
        """Discards an event that was staged but never submitted for persistence."""
        with self._lock:
            event = self.events.pop(event_id, None)
            if event is None or not event.turn_id:
                return
            turn_events = self._event_ids_by_turn.get(event.turn_id)
            if turn_events is None:
                return
            self._event_ids_by_turn[event.turn_id] = [
                identifier for identifier in turn_events if identifier != event_id
            ]
            if not self._event_ids_by_turn[event.turn_id]:
                self._event_ids_by_turn.pop(event.turn_id, None)

    def record_message(
        self,
        agent: "Agent",
        team: Optional["AgentTeam"],
        message: Dict[str, Any],
        *,
        capture_content: bool = True,
    ) -> SystemMemoryEvent:
        payload, redacted = sanitize_message_payload(
            message, capture_content=capture_content
        )
        return self.record_event(
            "message",
            agent=agent,
            team=team,
            role=str(message.get("role", "user")),
            source_execution_id=message.get("source_execution_id"),
            source_chat_message_id=message.get("source_chat_message_id"),
            payload=payload,
            redacted=redacted,
        )

    def start_turn(self, agent: "Agent", team: Optional["AgentTeam"], turn_id: str) -> None:
        self.record_event(
            "agent_turn_started",
            agent=agent,
            team=team,
            turn_id=turn_id,
            payload={"round_number": self.manager._active_round_number.get()},
        )

    async def finalize_turn(
        self,
        agent: "Agent",
        team: Optional["AgentTeam"],
        result: AgentTurnResult,
    ) -> None:
        """Closes a terminal turn and optionally queues exactly one Memory Card."""
        turn_id = result.turn_id
        if not turn_id:
            raise RuntimeError("A terminal Agent turn must have a stable turn ID.")
        self.record_event(
            "agent_turn_finished",
            agent=agent,
            team=team,
            turn_id=turn_id,
            payload={
                "status": result.status.value,
                "error_kind": result.error_kind,
                "round_number": result.round_number,
            },
        )
        self._recalled_by_turn.pop(turn_id, None)
        if team is not None and team.team_kind == "supervisory":
            # Audit-scoped Agents leave durable Journal evidence, but never
            # create Agent-owned retrieval jobs that can outlive their team.
            return
        if not self.manager.config.episodic_memory.enabled:
            self.ensure_enabled()
            return
        self.ensure_enabled()
        with self._lock:
            if any(segment.turn_id == turn_id for segment in self.segments.values()):
                return
            source_event_ids = [
                event_id
                for event_id in self._event_ids_by_turn.get(turn_id, ())
                if event_id in self.events
                and self.events[event_id].agent_id == agent.agent_id
            ]
            source_events = [
                self.events[event_id]
                for event_id in source_event_ids
                if event_id in self.events
            ]
            recall_content = render_recall_content(source_events)
            now = time.time()
            segment = AgentMemorySegment(
                segment_id=f"SEG-{uuid.uuid4().hex}",
                agent_id=agent.agent_id,
                turn_id=turn_id,
                origin_team_id=team.team_id if team else None,
                discussion_id=result.discussion_id,
                source_event_ids=source_event_ids,
                recall_content=recall_content,
                content_sha256=content_digest(recall_content),
                created_at=now,
                updated_at=now,
            )
            self.segments[segment.segment_id] = segment
        self.manager._auto_save(memory_segments={segment.segment_id})
        self.record_event(
            "memory_segment_created",
            agent=agent,
            team=team,
            turn_id=turn_id,
            payload={"segment_id": segment.segment_id},
        )
        self._schedule_segment(segment.segment_id)

    def cancel_turn(
        self, agent: "Agent", team: Optional["AgentTeam"], turn_id: str, reason: str
    ) -> None:
        self._recalled_by_turn.pop(turn_id, None)
        self.record_event(
            "agent_turn_cancelled",
            agent=agent,
            team=team,
            turn_id=turn_id,
            payload={"reason": reason},
            redacted=True,
        )

    async def finalize_activity_invocation(self, agent, team, invocation_id):
        """Stage optional derived memory; scheduling follows its exact checkpoint."""
        self._recalled_by_turn.pop(invocation_id, None)
        if not self.manager.config.episodic_memory.enabled:
            return None
        with self._lock:
            previous = next((item for item in self.segments.values() if item.invocation_id == invocation_id), None)
            if previous is not None:
                return previous.segment_id
            events = sorted((event for event in self.events.values()
                             if event.agent_id == agent.agent_id and event.invocation_id == invocation_id),
                            key=lambda event: event.sequence)
            if not events:
                return None
            content = render_recall_content(events)
            now = time.time()
            segment = AgentMemorySegment(segment_id=f"SEG-{uuid.uuid4().hex}", agent_id=agent.agent_id,
                turn_id=invocation_id, invocation_id=invocation_id, origin_team_id=team.team_id if team else None,
                source_event_ids=[event.event_id for event in events], recall_content=content,
                content_sha256=content_digest(content), created_at=now, updated_at=now)
            self.segments[segment.segment_id] = segment
            return segment.segment_id
