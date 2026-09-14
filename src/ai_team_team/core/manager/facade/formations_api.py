"""Public ATTManager APIs for consensual AgentTeam formation."""

import asyncio
from contextlib import asynccontextmanager
from typing import Any, Iterable, Optional

from ...agent import Agent


class FormationAPI:
    @asynccontextmanager
    async def _formation_operation(self):
        task = asyncio.current_task()
        async with self._runtime_gate:
            if self._closing:
                raise RuntimeError("ATTManager is closing and rejects team formation operations.")
            self._active_formation_operations += 1
            if task is not None:
                self._formation_operation_tasks.add(task)
        try:
            yield
        finally:
            async with self._runtime_gate:
                self._active_formation_operations -= 1
                if task is not None:
                    self._formation_operation_tasks.discard(task)

    def propose_team_formation(self, **kwargs: Any):
        """Creates a persistent invitation workflow without adding any invitee."""
        return self._formations.propose_team_formation(**kwargs)

    def get_team_formation(self, request_id: str):
        try:
            return self._formations.requests[request_id].model_copy(deep=True)
        except KeyError as exc:
            raise KeyError(f"Unknown team formation request {request_id!r}.") from exc

    def inspect_team_formation(self, request_id: str, *, actor: Agent):
        return self._formations.inspect_team_formation(request_id, actor=actor)

    async def respond_team_invitation(
        self,
        request_id: str,
        *,
        actor: Agent,
        attitude: Optional[str],
    ):
        async with self._formation_operation():
            return await self._formations.respond_team_invitation(
                request_id,
                actor=actor,
                attitude=attitude,
            )

    async def create_team_from_formation(self, request_id: str, *, actor: Agent):
        async with self._formation_operation():
            return await self._formations.create_team_from_formation(
                request_id,
                actor=actor,
            )

    async def abandon_team_formation(
        self,
        request_id: str,
        *,
        actor: Agent,
        reason: str = "",
    ):
        async with self._formation_operation():
            return await self._formations.abandon_team_formation(
                request_id,
                actor=actor,
                reason=reason,
            )

    async def decide_team_formation_late_join(
        self,
        request_id: str,
        invitee_agent_id: str,
        *,
        actor: Agent,
        approved: bool,
    ):
        async with self._formation_operation():
            return await self._formations.decide_late_join(
                request_id,
                invitee_agent_id,
                actor=actor,
                approved=approved,
            )

    def list_agent_inbox(self, agent_id: str, *, unread_only: bool = True):
        return self._formations.list_agent_inbox(agent_id, unread_only=unread_only)

    async def mark_agent_inbox_read(
        self,
        agent_id: str,
        message_ids: Optional[Iterable[str]] = None,
    ) -> int:
        async with self._formation_operation():
            return await self._formations.mark_agent_inbox_read(agent_id, message_ids)
