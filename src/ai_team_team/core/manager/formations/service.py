"""Composed formation service."""

from typing import TYPE_CHECKING

from .lifecycle import FormationLifecycleMixin
from .notifications import FormationNotificationMixin
from .proposals import FormationProposalMixin

if TYPE_CHECKING:
    from ..facade import ATTManager


class FormationService(
    FormationProposalMixin,
    FormationLifecycleMixin,
    FormationNotificationMixin,
):
    """Owns Agent invitations, formation commits, and identity inboxes."""

    def __init__(self, manager: "ATTManager") -> None:
        import asyncio
        import threading

        self.manager = manager
        self.requests = {}
        self.invitations = {}
        self._state_lock = threading.RLock()
        self._request_locks = {}
        self.tasks: set[asyncio.Task[object]] = set()

    def request_lock(self, request_id: str):
        import asyncio

        with self._state_lock:
            if request_id not in self.requests:
                raise KeyError(f"Unknown team formation request {request_id!r}.")
            return self._request_locks.setdefault(request_id, asyncio.Lock())

    def restore(self, requests, invitations, agent_inboxes) -> None:
        """Replaces all formation state after strict staging validation."""
        from ...formation import AgentInboxMessage, TeamFormationInvitation, TeamFormationRequest

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
        for agent in self.manager._agents_by_id.values():
            restored = []
            for row in agent_inboxes.get(agent.agent_id, []):
                restored.append(
                    AgentInboxMessage.model_validate(row, strict=False).model_dump(mode="json")
                )
            with agent.inbox_lock:
                agent.agent_inbox = restored
        self._request_locks = {}
