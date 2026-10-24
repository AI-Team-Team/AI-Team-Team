"""Append-only journal and personal-invocation segmentation."""

import time
import uuid
from typing import TYPE_CHECKING, Any, Dict, Optional

from ai_team_team.core.memory import AgentMemorySegment, SystemMemoryEvent
from ai_team_team.core.memory.sanitization import (
    content_digest,
    render_recall_content,
    sanitize_message_payload,
)

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
        active = executing if (
            inherit_context
            and executing is not None
            and (agent is None or agent.agent_id == executing.agent_id)
        ) else None
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
                role=role,
                payload=dict(payload or {}),
                redacted=redacted,
                created_at=time.time(),
            )
            self.events[event.event_id] = event
        if persist and executing is not None and agent is not None and agent.agent_id == executing.agent_id:
            executing.pending_event_ids.add(event.event_id)
        elif persist:
            manager._auto_save(memory_events={event.event_id})
        return event

    def discard_unpersisted_event(self, event_id: str) -> None:
        """Discards an event that was staged but never submitted for persistence."""
        with self._lock:
            event = self.events.pop(event_id, None)

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

    async def finalize_activity_invocation(self, agent, team, invocation_id):
        """Stage optional derived memory; scheduling follows its exact checkpoint."""
        self._recalled_by_invocation.pop(invocation_id, None)
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
                invocation_id=invocation_id, origin_team_id=team.team_id if team else None,
                source_event_ids=[event.event_id for event in events], recall_content=content,
                content_sha256=content_digest(content), created_at=now, updated_at=now)
            self.segments[segment.segment_id] = segment
            return segment.segment_id
