"""Persistent Agent inbox notifications for formation workflows."""

import json
import time
import uuid
from typing import Any, Dict, Iterable, List, Optional

from ...formation import AgentInboxMessage


class FormationNotificationMixin:
    def _notify_agent(
        self,
        agent_id: str,
        message_type: str,
        payload: Dict[str, Any],
    ) -> str:
        agent = self.manager._agents_by_id.get(agent_id)
        if agent is None:
            raise ValueError(f"Cannot notify missing Agent {agent_id!r}.")
        message = AgentInboxMessage(
            message_id=f"AIN-{uuid.uuid4().hex}",
            agent_id=agent_id,
            message_type=message_type,
            payload=dict(payload),
            created_at=time.time(),
        ).model_dump(mode="json")
        with agent.inbox_lock:
            agent.agent_inbox.append(message)
        return message["message_id"]

    def list_agent_inbox(
        self,
        agent_id: str,
        *,
        unread_only: bool = True,
    ) -> List[AgentInboxMessage]:
        agent = self.manager._agents_by_id.get(agent_id)
        if agent is None:
            raise KeyError(f"Unknown Agent ID {agent_id!r}.")
        with agent.inbox_lock:
            rows = [dict(item) for item in agent.agent_inbox]
        messages = [AgentInboxMessage.model_validate(row, strict=False) for row in rows]
        if unread_only:
            messages = [message for message in messages if message.read_at is None]
        return messages

    async def mark_agent_inbox_read(
        self,
        agent_id: str,
        message_ids: Optional[Iterable[str]] = None,
    ) -> int:
        agent = self.manager._agents_by_id.get(agent_id)
        if agent is None:
            raise KeyError(f"Unknown Agent ID {agent_id!r}.")
        selected = set(message_ids) if message_ids is not None else None
        now = time.time()
        changed = 0
        with agent.inbox_lock:
            previous_read_times = {
                message["message_id"]: message.get("read_at")
                for message in agent.agent_inbox
            }
            for message in agent.agent_inbox:
                if message.get("read_at") is not None:
                    continue
                if selected is not None and message.get("message_id") not in selected:
                    continue
                message["read_at"] = now
                changed += 1
        if changed:
            dirty = self.manager._new_dirty_state()
            dirty["agent_inboxes"].add(agent_id)
            try:
                await self.manager._commit_dirty_state(dirty)
            except Exception:
                with agent.inbox_lock:
                    for message in agent.agent_inbox:
                        message_id = message["message_id"]
                        if message_id in previous_read_times:
                            message["read_at"] = previous_read_times[message_id]
                raise
        return changed

    def render_agent_inbox(self, agent_id: str, *, limit: int = 20) -> str:
        # Governance auditors and other framework-owned runtime Agents are
        # deliberately not registered identities and therefore have no durable
        # personal inbox. Their prompts must remain usable without fabricating
        # ownership or silently registering them.
        if agent_id not in self.manager._agents_by_id:
            return ""
        messages = self.list_agent_inbox(agent_id, unread_only=True)[-limit:]
        if not messages:
            return ""
        lines = [
            "## PERSONAL AGENT INBOX",
            "These notifications belong to your Agent identity across all AgentTeams.",
        ]
        for message in messages:
            lines.append(
                f"- `{message.message_id}` `{message.message_type}`: "
                f"{json.dumps(message.payload, ensure_ascii=False, sort_keys=True)}"
            )
        lines.append(
            "Use the formation tools to inspect and respond. A no-response invitation never adds you to a team."
        )
        return "\n".join(lines) + "\n\n"
