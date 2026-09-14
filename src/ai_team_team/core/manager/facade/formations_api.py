"""Public ATTManager APIs for consensual AgentTeam formation."""

import asyncio
from contextlib import asynccontextmanager
from typing import Any, Iterable, Optional

from ...agent import Agent
from ...formation import TeamFormationRevisionPatch


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
        reserved = sorted(key for key in kwargs if key.startswith("_"))
        if reserved:
            raise TypeError(
                "Internal formation publication controls are not public API arguments: "
                + ", ".join(reserved)
            )
        return self._formations.propose_team_formation(**kwargs)

    def get_team_formation(self, request_id: str):
        try:
            return self._formations.requests[request_id].model_copy(deep=True)
        except KeyError as exc:
            raise KeyError(f"Unknown team formation request {request_id!r}.") from exc

    def inspect_team_formation(self, request_id: str, *, actor: Agent):
        return self._formations.inspect_team_formation(request_id, actor=actor)

    def get_team_formation_invitation(self, request_id: str, agent_id: str):
        try:
            return self._formations.invitations[(request_id, agent_id)].model_copy(deep=True)
        except KeyError as exc:
            raise KeyError("Unknown team formation invitation.") from exc

    def list_team_formation_revisions(self, request_id: str):
        return [
            revision.model_copy(deep=True)
            for revision in sorted(
                (
                    item
                    for item in self._formations.revisions.values()
                    if item.request_id == request_id
                ),
                key=lambda item: item.proposal_revision,
            )
        ]

    def list_team_formation_decisions(self, request_id: str):
        return [
            decision.model_copy(deep=True)
            for decision in sorted(
                (
                    item
                    for item in self._formations.decisions.values()
                    if item.request_id == request_id
                ),
                key=lambda item: item.created_at,
            )
        ]

    def get_team_formation_draft(self, draft_id: str, *, actor: Agent):
        self._formations._require_active_agent(actor)
        try:
            draft = self._formations.drafts[draft_id]
        except KeyError as exc:
            raise KeyError(f"Unknown team formation draft {draft_id!r}.") from exc
        if draft.initiator_agent_id != actor.agent_id:
            raise PermissionError("Only the initiating Agent may inspect this draft.")
        return draft.model_copy(deep=True)

    def list_team_formation_drafts(self, *, actor: Agent):
        """Returns detached drafts owned by one active initiating Agent."""
        self._formations._require_active_agent(actor)
        return [
            draft.model_copy(deep=True)
            for draft in sorted(
                (
                    item
                    for item in self._formations.drafts.values()
                    if item.initiator_agent_id == actor.agent_id
                ),
                key=lambda item: item.created_at,
            )
        ]

    async def discuss_team_formation_proposal(
        self,
        *,
        actor: Agent,
        objective: str,
        request_id: Optional[str] = None,
    ):
        async with self._formation_operation():
            return await self._formations.discuss_team_formation_proposal(
                actor=actor,
                objective=objective,
                request_id=request_id,
            )

    async def retry_team_formation_draft(self, draft_id: str, *, actor: Agent):
        async with self._formation_operation():
            return await self._formations.retry_team_formation_draft(
                draft_id,
                actor=actor,
            )

    async def publish_team_formation_draft(self, draft_id: str, *, actor: Agent):
        async with self._formation_operation():
            return await self._formations.publish_team_formation_draft(
                draft_id,
                actor=actor,
            )

    async def respond_team_invitation(
        self,
        request_id: str,
        *,
        actor: Agent,
        proposal_revision: int,
        attitude: Optional[str],
    ):
        async with self._formation_operation():
            return await self._formations.respond_team_invitation(
                request_id,
                actor=actor,
                proposal_revision=proposal_revision,
                attitude=attitude,
            )

    async def create_team_from_formation(
        self,
        request_id: str,
        *,
        actor: Agent,
        proposal_revision: int,
    ):
        async with self._formation_operation():
            return await self._formations.create_team_from_formation(
                request_id,
                actor=actor,
                proposal_revision=proposal_revision,
            )

    async def revise_team_formation(
        self,
        request_id: str,
        *,
        actor: Agent,
        base_revision: int,
        changes: TeamFormationRevisionPatch,
    ):
        async with self._formation_operation():
            return await self._formations.revise_team_formation(
                request_id,
                actor=actor,
                base_revision=base_revision,
                changes=changes,
            )

    async def abandon_team_formation(
        self,
        request_id: str,
        *,
        actor: Agent,
        proposal_revision: int,
        reason: str = "",
    ):
        async with self._formation_operation():
            return await self._formations.abandon_team_formation(
                request_id,
                actor=actor,
                proposal_revision=proposal_revision,
                reason=reason,
            )

    async def decide_team_formation_late_join(
        self,
        request_id: str,
        invitee_agent_id: str,
        *,
        actor: Agent,
        proposal_revision: int,
        approved: bool,
    ):
        async with self._formation_operation():
            return await self._formations.decide_late_join(
                request_id,
                invitee_agent_id,
                actor=actor,
                proposal_revision=proposal_revision,
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
