"""Invitation response handling before AgentTeam creation."""

import time
from typing import Optional

from ....agent import Agent
from ....formation import (
    FormationOperationResult,
    InvitationAttitude,
    TeamFormationStatus,
    UnanimousAcceptanceAction,
)


class FormationInvitationResponseMixin:
    async def respond_team_invitation(
        self,
        request_id: str,
        *,
        actor: Agent,
        attitude: Optional[str],
    ) -> FormationOperationResult:
        self._require_active_agent(actor)
        async with self.request_lock(request_id):
            self._require_active_agent(actor)
            request = self.requests.get(request_id)
            invitation = self.invitations.get((request_id, actor.agent_id))
            if request is None or invitation is None:
                raise PermissionError("The acting Agent is not invited to this formation.")
            if request.status is TeamFormationStatus.ABANDONED:
                raise ValueError("An abandoned formation cannot receive responses.")
            normalized = (
                InvitationAttitude.NO_RESPONSE
                if attitude is None
                else InvitationAttitude(attitude)
            )
            if request.status is TeamFormationStatus.CREATED:
                return await self._respond_after_creation(request, invitation, actor, normalized)
            if normalized is invitation.attitude:
                return FormationOperationResult(
                    status="INVITATION_UPDATED",
                    request_id=request_id,
                    summary=self.formation_summary(request_id),
                    reason="The public invitation attitude is unchanged.",
                )

            old_request = request.model_copy(deep=True)
            old_invitation = invitation.model_copy(deep=True)
            attitude_changed = normalized is not old_invitation.attitude
            initiator = self.manager._agents_by_id[request.initiator_agent_id]
            inbox_copies = self._copy_inboxes((initiator, actor))
            now = time.time()
            invitation.attitude = normalized
            invitation.responded_at = now if normalized is not InvitationAttitude.NO_RESPONSE else None
            invitation.proposal_revision = request.proposal_revision
            request.updated_at = now
            all_accepted = all(
                item.attitude is InvitationAttitude.ACCEPTED
                for item in self._request_invitations(request_id)
            )
            if (
                all_accepted
                and request.unanimous_acceptance_action
                is UnanimousAcceptanceAction.REQUIRE_CONFIRMATION
            ):
                request.status = TeamFormationStatus.READY_FOR_CONFIRMATION
            else:
                request.status = TeamFormationStatus.COLLECTING_RESPONSES
            if attitude_changed:
                self._notify_agent(
                    initiator.agent_id,
                    "team_formation_attitude_changed",
                    {
                        "request_id": request_id,
                        "invitee_agent_id": actor.agent_id,
                        "attitude": normalized.value,
                        "summary": self.formation_summary(request_id).model_dump(mode="json"),
                    },
                )

            if (
                all_accepted
                and request.unanimous_acceptance_action
                is UnanimousAcceptanceAction.AUTO_CREATE
            ):
                try:
                    result = await self._finalize_locked(request, automatic=True)
                except ValueError as exc:
                    request = self.requests[request_id]
                    request.status = TeamFormationStatus.COLLECTING_RESPONSES
                    request.decision_reason = f"Automatic creation could not commit: {exc}"
                else:
                    self._emit_event(
                        "team_formation_invitation_responded",
                        {
                            "request_id": request_id,
                            "agent_id": actor.agent_id,
                            "attitude": normalized.value,
                        },
                    )
                    return result

            try:
                await self.manager._commit_dirty_state(
                    self._dirty(
                        request_id,
                        inbox_agent_ids=(
                            {initiator.agent_id} if attitude_changed else set()
                        ),
                    )
                )
            except Exception:
                self.requests[request_id] = old_request
                self.invitations[(request_id, actor.agent_id)] = old_invitation
                self._restore_inboxes((initiator, actor), inbox_copies)
                raise
            if attitude_changed:
                self._emit_event(
                    "team_formation_invitation_responded",
                    {
                        "request_id": request_id,
                        "agent_id": actor.agent_id,
                        "attitude": normalized.value,
                    },
                )
            summary = self.formation_summary(request_id)
            status = (
                "READY_FOR_CONFIRMATION"
                if request.status is TeamFormationStatus.READY_FOR_CONFIRMATION
                else "INVITATION_UPDATED"
            )
            return FormationOperationResult(
                status=status,
                request_id=request_id,
                summary=summary,
                reason=request.decision_reason,
            )
