"""Composed formation service."""

from typing import TYPE_CHECKING
from contextlib import asynccontextmanager

from .lifecycle import FormationLifecycleMixin
from .notifications import FormationNotificationMixin
from .proposals import FormationProposalMixin
from .publication import FormationPublicationMixin

if TYPE_CHECKING:
    from ..facade import ATTManager


class FormationService(
    FormationPublicationMixin,
    FormationProposalMixin,
    FormationLifecycleMixin,
    FormationNotificationMixin,
):
    """Owns Agent invitations, formation commits, and identity inboxes."""

    def __init__(self, manager: "ATTManager") -> None:
        import asyncio
        import threading

        self.manager = manager
        self._initialize_publication()
        self._state_lock = threading.RLock()
        self._request_locks = {}
        self._draft_locks = {}
        self.tasks: set[asyncio.Task[object]] = set()

    @asynccontextmanager
    async def request_lock(self, request_id: str):
        import asyncio

        with self._state_lock:
            if request_id not in self.requests:
                raise KeyError(f"Unknown team formation request {request_id!r}.")
            lock = self._request_locks.setdefault(request_id, asyncio.Lock())
        async with lock, self.stage(request_id=request_id):
            yield

    @asynccontextmanager
    async def draft_lock(self, draft_id: str):
        import asyncio

        with self._state_lock:
            if draft_id not in self.drafts:
                raise KeyError(f"Unknown team formation draft {draft_id!r}.")
            lock = self._draft_locks.setdefault(draft_id, asyncio.Lock())
        async with lock, self.stage(draft_id=draft_id):
            yield

    def restore(
        self,
        requests,
        invitations,
        revisions,
        decisions,
        drafts,
        agent_inboxes,
    ) -> None:
        """Replaces all formation state after strict staging validation."""
        from ...formation import (
            AgentInboxMessage,
            FormationDraftStatus,
            TeamFormationDraft,
            TeamFormationInvitation,
            TeamFormationInvitationDecision,
            TeamFormationRequest,
            TeamFormationRevision,
        )

        self.requests.clear()
        self.requests.update(
            {
                item.request_id: item
                for item in (
                    TeamFormationRequest.model_validate(row, strict=False)
                    for row in requests
                )
            }
        )
        self.invitations.clear()
        self.invitations.update(
            {
                (item.request_id, item.agent_id): item
                for item in (
                    TeamFormationInvitation.model_validate(row, strict=False)
                    for row in invitations
                )
            }
        )
        self.revisions.clear()
        self.revisions.update(
            {
                item.revision_id: item
                for item in (
                    TeamFormationRevision.model_validate(row, strict=False)
                    for row in revisions
                )
            }
        )
        self.decisions.clear()
        self.decisions.update(
            {
                item.decision_id: item
                for item in (
                    TeamFormationInvitationDecision.model_validate(row, strict=False)
                    for row in decisions
                )
            }
        )
        self.drafts.clear()
        self.drafts.update(
            {
                item.draft_id: item
                for item in (
                    TeamFormationDraft.model_validate(row, strict=False)
                    for row in drafts
                )
            }
        )
        for agent in self.manager._agents_by_id.values():
            restored = []
            for row in agent_inboxes.get(agent.agent_id, []):
                restored.append(
                    AgentInboxMessage.model_validate(row, strict=False).model_dump(mode="json")
                )
            with agent.inbox_lock:
                agent.agent_inbox = restored
        self._request_locks = {}
        self._draft_locks = {}
