"""Identity-owned email delivery, read receipts, and normal-context notices."""

import asyncio
import json
import time
import uuid
from typing import Any, Dict, Iterable, List, Optional

from ..agent import Agent
from ..formation import AgentInboxMessage


class PersonalInboxService:
    def __init__(self, manager: Any) -> None:
        self.manager = manager
        self._read_lock = asyncio.Lock()

    def notify(self, agent_id: str, message_type: str, payload: Dict[str, Any]) -> str:
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

    def list(self, agent_id: str, *, unread_only: bool = True) -> List[AgentInboxMessage]:
        agent = self.manager._agents_by_id.get(agent_id)
        if agent is None:
            raise KeyError(f"Unknown Agent ID {agent_id!r}.")
        with agent.inbox_lock:
            rows = [dict(item) for item in agent.agent_inbox]
        messages = [AgentInboxMessage.model_validate(row, strict=False) for row in rows]
        return [item for item in messages if item.read_at is None] if unread_only else messages

    async def mark_read(self, agent_id: str, message_ids: Optional[Iterable[str]] = None) -> int:
        async with self._read_lock:
            if self.manager._closing or self.manager._restore_in_progress:
                raise RuntimeError("ATTManager cannot change email receipts during shutdown or restore.")
            return await self._mark_read(agent_id, message_ids)

    async def _mark_read(self, agent_id: str, message_ids: Optional[Iterable[str]]) -> int:
        agent = self.manager._agents_by_id.get(agent_id)
        if agent is None:
            raise KeyError(f"Unknown Agent ID {agent_id!r}.")
        selected = set(message_ids) if message_ids is not None else None
        with agent.inbox_lock:
            previous = {item["message_id"]: item.get("read_at") for item in agent.agent_inbox}
            changed = 0
            for item in agent.agent_inbox:
                if item.get("read_at") is None and (
                    selected is None or item["message_id"] in selected
                ):
                    item["read_at"] = time.time()
                    changed += 1
        if changed:
            dirty = self.manager._new_dirty_state()
            dirty["agent_inboxes"].add(agent_id)
            try:
                await self.manager._commit_dirty_state(dirty)
            except Exception:
                with agent.inbox_lock:
                    for item in agent.agent_inbox:
                        if item["message_id"] in previous:
                            item["read_at"] = previous[item["message_id"]]
                raise
        return changed

    def open(self, agent: Agent, message_id: str) -> Dict[str, Any]:
        """Inspects an owned email without marking it read or submitting a choice."""
        if (
            self.manager._agents_by_id.get(agent.agent_id) is not agent
            or agent.lifecycle_state != "active"
        ):
            raise PermissionError("Opening personal email requires an active registered Agent.")
        message = next(
            (
                item
                for item in self.list(agent.agent_id, unread_only=False)
                if item.message_id == message_id
            ),
            None,
        )
        if message is None:
            raise PermissionError("The email does not belong to the current Agent.")
        result = message.model_dump(mode="json")
        if message.message_type == "governance_choice_request":
            result["governance"] = self.manager._governance.inspect(
                agent, message.payload["round_id"]
            )
        return result

    def render(self, agent_id: str, *, limit: int = 20) -> str:
        if agent_id not in self.manager._agents_by_id:
            return ""
        visible = []
        for message in self.list(agent_id, unread_only=False):
            outstanding = (
                message.message_type == "governance_choice_request"
                and self.manager._governance.is_outstanding(
                    agent_id, message.payload.get("round_id")
                )
            )
            if message.read_at is None or outstanding:
                visible.append(message)
        if not visible:
            return ""
        lines = [
            "## PERSONAL AGENT INBOX",
            "These emails belong to your continuing Agent identity across all AgentTeams.",
        ]
        for message in visible[-limit:]:
            if message.message_type == "governance_choice_request":
                lines.append(
                    f"- You received a governance voting email `{message.message_id}` for round `{message.payload['round_id']}`. You may use `open_agent_mail` to inspect it and independently decide whether to use `submit_governance_choice`. Reading is not voting."
                )
            else:
                lines.append(
                    f"- `{message.message_id}` `{message.message_type}`: {json.dumps(message.payload, ensure_ascii=False, sort_keys=True)}"
                )
        lines.append(
            "Email read receipts and domain choices are independent. You may read without choosing or answer later; no default ballot is supplied."
        )
        return "\n".join(lines) + "\n\n"
