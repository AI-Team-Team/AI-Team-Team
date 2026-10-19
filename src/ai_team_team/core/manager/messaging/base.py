"""Invocation authority and exact-receipt chat operations over immutable values."""

import asyncio
import json
import uuid
from contextlib import AsyncExitStack, asynccontextmanager
from functools import wraps

from ai_team_team.core.activity.contracts import SourceDeliveryReceipt
from ai_team_team.core.chat import ChatOperationResult, _command_digest
from ai_team_team.core.exceptions import ToolArgumentError
from ai_team_team.database.persistence.records import thaw
from ..activity.values import capture


def identity(prefix):
    return f"{prefix}-{uuid.uuid4().hex}"


def inspected(function):
    """Keep Host-thread identity checks and COW query capture in one generation."""
    @wraps(function)
    def query(self, *args, **kwargs):
        with self.manager._resources.mutation():
            return function(self, *args, **kwargs)
    return query


class ChatBase:
    def __init__(self, manager):
        self.manager = manager
        self.pair_locks = {}
        self.cursors = {}
        self.read_deliveries = set()

    @property
    def clock(self):
        return self.manager._activity.clock

    def actor(self, actor=None):
        self.manager._resources.check_authority()
        current = self.manager._active_tool_agent.get()
        if current is not None:
            if actor is not None and actor is not current:
                raise PermissionError("The invocation cannot select another chat actor.")
            actor = current
        if actor is None or self.manager._agents_by_id.get(actor.agent_id) is not actor:
            raise PermissionError("Chat requires an explicit registered actor.")
        return self.manager._activity.require_agent(actor.agent_id)

    def team(self, team_id, actor):
        team = self.manager.teams.get(team_id)
        if (team is None or team.team_kind != "ordinary"
                or getattr(team, "_publication_pending", False)
                or getattr(team, "_lifecycle_state", "active") != "active" or actor not in team.members):
            raise PermissionError("Publishing requires current active team membership.")
        if self.manager._active_tool_agent.get() is not None and self.manager._active_team.get() is not team:
            raise PermissionError("Publishing requires the captured current AgentTeam.")
        return team

    def operation(self, actor, command, arguments, operation_key):
        key = operation_key if operation_key is not None else self.manager._active_tool_invocation_id.get() or identity("HOST")
        if type(key) is not str or not key.strip():
            raise ToolArgumentError("An operation key must be nonblank text.")
        if self.manager._active_tool_agent.get() is not None and operation_key is not None:
            if key != self.manager._active_tool_invocation_id.get():
                raise PermissionError("A tool cannot override its execution identity.")
        digest = _command_digest(command, arguments)
        return key, digest, f"CHAT-{actor.agent_id}-{key}"

    async def replay(self, actor, command, operation):
        key, digest, commit_id = operation
        record = self.manager._records.index.get(("chat_operations", (actor.agent_id, key)))
        if record is None:
            return None
        if record.values["command"] != command or record.values["request_digest"] != digest:
            raise ToolArgumentError("This operation key already identifies different chat input.")
        receipt = self.manager._records.receipts.get(commit_id)
        receipt = receipt[0] if receipt else None
        if receipt is None and self.manager.db_path:
            receipt = await self.manager._persistence.receipt(self.manager.db_path, commit_id)
        result = thaw(record.values["result"])
        result.update(durability=receipt.durability if receipt else self.manager.persistence_mode,
                      state_version=receipt.state_version if receipt else max(1, self.manager._state_version))
        if result["status"] == "DELIVERED":
            return SourceDeliveryReceipt.model_validate_json(json.dumps(result))
        return ChatOperationResult.model_validate(result)

    async def finish(self, actor, command, operation, records, result, *, dirty=None, notifications=(), team_memberships=None):
        key, digest, commit_id = operation
        session = self.manager._activity.current.get()
        evidence = capture(self.manager, "chat_operations", agent_id=actor.agent_id, operation_key=key,
                           command=command, request_digest=digest, result=result,
                           invocation_id=session.invocation_id if session is not None else None,
                           created_at=self.clock.wall_time())
        try:
            receipt = await self.manager._records.commit((*records, evidence), operation_id=commit_id,
                dirty=dirty, notifications=notifications, team_memberships=team_memberships)
        finally:
            if commit_id in self.manager._records.receipts:
                for notice_id in notifications:
                    self.manager._activity.schedule_notice(notice_id)
        self.manager._emit_callback("on_system_event", "chat_operation_committed", {
            "agent_id": actor.agent_id, "command": command, "operation_id": commit_id,
            **{key: value for key, value in result.items() if key in {"message_id", "request_id", "relationship_id", "status", "version"}},
        })
        values = {**result, "durability": receipt.durability, "state_version": receipt.state_version}
        if result["status"] == "DELIVERED":
            return SourceDeliveryReceipt.model_validate(values)
        return ChatOperationResult.model_validate(values)

    def pair_lock(self, left, right):
        return self.pair_locks.setdefault(tuple(sorted((left, right))), asyncio.Lock())

    @asynccontextmanager
    async def contact_lock(self, left, right):
        """Serialize admission with both endpoint lifecycle decisions."""
        async with self.pair_lock(left, right), AsyncExitStack() as stack:
            for owner in sorted({left, right}):
                agent = self.manager._agents_by_id.get(owner)
                if agent is None:
                    raise PermissionError("A direct endpoint is not registered.")
                await stack.enter_async_context(agent.lifecycle_lock)
            yield

    def rows(self, table):
        return tuple(row for row in self.manager._records.snapshot() if row.table_name == table)
