"""Invitation response handling before AgentTeam creation."""

import time
import uuid
from typing import Optional

from ....agent import Agent
from ....formation import (
    FormationOperationResult,
    InvitationAttitude,
    TeamFormationInvitationDecision,
    TeamFormationStatus,
    UnanimousAcceptanceAction,
)


class FormationInvitationResponseMixin:
    async def respond_team_invitation(
        self,
        request_id: str,
        *,
        actor: Agent,
        proposal_revision: int,
        attitude: Optional[str],
    ) -> FormationOperationResult:
        self._require_active_agent(actor)
        async with self.request_lock(request_id):
            self._require_active_agent(actor)
            request = self.requests.get(request_id)
            invitation = self.invitations.get((request_id, actor.agent_id))
            if request is None or invitation is None:
                raise PermissionError("The acting Agent is not invited to this formation.")
            self._assert_request_integrity(request)
            if (
                not isinstance(proposal_revision, int)
                or isinstance(proposal_revision, bool)
                or proposal_revision < 1
            ):
                raise TypeError("proposal_revision must be a positive integer.")
            if proposal_revision != request.proposal_revision:
                return self._stale_revision_result(request, proposal_revision)
            if request.status is TeamFormationStatus.ABANDONED:
                raise ValueError("An abandoned formation cannot receive responses.")
            normalized = (
                InvitationAttitude.NO_RESPONSE
                if attitude is None
                else InvitationAttitude(attitude)
            )
            if request.status is TeamFormationStatus.CREATED:
                return await self._respond_after_creation(
                    request,
                    invitation,
                    actor,
                    normalized,
                    explicit_no_response=attitude is None,
                )
            explicit_no_response = (
                attitude is None
                and normalized is InvitationAttitude.NO_RESPONSE
                and invitation.attitude is InvitationAttitude.NO_RESPONSE
            )
            if normalized is invitation.attitude and not explicit_no_response:
                return FormationOperationResult(
                    status="INVITATION_UPDATED",
                    request_id=request_id,
                    summary=self.formation_summary(request_id),
                    reason="The public invitation attitude is unchanged.",
                )

            old_request = request.model_copy(deep=True)
            old_invitation = invitation.model_copy(deep=True)
            decision = TeamFormationInvitationDecision(
                decision_id=f"TFD-{uuid.uuid4().hex}",
                request_id=request_id,
                proposal_revision=request.proposal_revision,
                agent_id=actor.agent_id,
                attitude=normalized,
                created_at=time.time(),
            )
            self.decisions[decision.decision_id] = decision
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
                try:
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
                except Exception:
                    self.requests[request_id] = old_request
                    self.invitations[(request_id, actor.agent_id)] = old_invitation
                    self.decisions.pop(decision.decision_id, None)
                    self._restore_inboxes((initiator, actor), inbox_copies)
                    raise

            if (
                all_accepted
                and request.unanimous_acceptance_action
                is UnanimousAcceptanceAction.AUTO_CREATE
            ):
                try:
                    result = await self._finalize_locked(
                        request,
                        automatic=True,
                        extra_dirty=self._dirty(
                            request_id,
                            inbox_agent_ids=(
                                {initiator.agent_id} if attitude_changed else set()
                            ),
                            decision_history=True,
                        ),
                    )
                except ValueError as exc:
                    request = self.requests[request_id]
                    request.status = TeamFormationStatus.COLLECTING_RESPONSES
                    request.decision_reason = f"Automatic creation could not commit: {exc}"
                except Exception:
                    self.requests[request_id] = old_request
                    self.invitations[(request_id, actor.agent_id)] = old_invitation
                    self.decisions.pop(decision.decision_id, None)
                    self._restore_inboxes((initiator, actor), inbox_copies)
                    raise
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
                        decision_history=True,
                    )
                )
            except Exception:
                self.requests[request_id] = old_request
                self.invitations[(request_id, actor.agent_id)] = old_invitation
                self.decisions.pop(decision.decision_id, None)
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
                reason=(
                    "The Agent explicitly chose not to publish an attitude; the public "
                    "state remains NO_RESPONSE."
                    if explicit_no_response and not attitude_changed
                    else request.decision_reason
                ),
            )
