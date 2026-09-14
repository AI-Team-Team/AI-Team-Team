"""Post-creation invitation responses and explicit late joining."""

import asyncio
import time
import uuid
from typing import Any, Dict, Optional

from ....agent import Agent
from ....formation import (
    FormationOperationResult,
    InvitationAttitude,
    LateJoinPolicy,
    TeamFormationInvitation,
    TeamFormationInvitationDecision,
    TeamFormationRequest,
    TeamFormationStatus,
)
from ....team import AgentTeam


class FormationLateJoinMixin:
    async def _respond_after_creation(
        self,
        request: TeamFormationRequest,
        invitation: TeamFormationInvitation,
        actor: Agent,
        attitude: InvitationAttitude,
        *,
        explicit_no_response: bool = False,
    ) -> FormationOperationResult:
        if invitation.joined_at is not None:
            raise ValueError(
                "A founding member must use the normal leave workflow instead of changing its invitation."
            )
        if request.late_join_policy is LateJoinPolicy.DISABLED:
            raise PermissionError("This formation does not allow late joining.")
        if (
            attitude is invitation.attitude
            and attitude is not InvitationAttitude.ACCEPTED
            and not explicit_no_response
        ):
            return FormationOperationResult(
                status="INVITATION_UPDATED",
                request_id=request.request_id,
                summary=self.formation_summary(request.request_id),
                team_id=request.created_team_id,
                reason="The public invitation attitude is unchanged.",
            )
        old_invitation = invitation.model_copy(deep=True)
        decision = TeamFormationInvitationDecision(
            decision_id=f"TFD-{uuid.uuid4().hex}",
            request_id=request.request_id,
            proposal_revision=request.proposal_revision,
            agent_id=actor.agent_id,
            attitude=attitude,
            created_at=time.time(),
        )
        self.decisions[decision.decision_id] = decision
        initiator = self.manager._agents_by_id[request.initiator_agent_id]
        old_inboxes = self._copy_inboxes((initiator, actor))
        invitation.attitude = attitude
        invitation.responded_at = (
            time.time() if attitude is not InvitationAttitude.NO_RESPONSE else None
        )
        invitation.late_join_pending = False
        invitation.late_join_requested_at = None
        invitation.late_join_decision = None
        if attitude is not InvitationAttitude.ACCEPTED:
            attitude_changed = attitude is not old_invitation.attitude
            try:
                if attitude_changed:
                    self._notify_agent(
                        initiator.agent_id,
                        "team_formation_attitude_changed",
                        {
                            "request_id": request.request_id,
                            "invitee_agent_id": actor.agent_id,
                            "attitude": attitude.value,
                            "summary": self.formation_summary(request.request_id).model_dump(mode="json"),
                        },
                    )
                await self.manager._commit_dirty_state(
                    self._dirty(
                        request.request_id,
                        inbox_agent_ids=(
                            {initiator.agent_id} if attitude_changed else set()
                        ),
                        decision_history=True,
                    )
                )
            except Exception:
                self.invitations[(request.request_id, actor.agent_id)] = old_invitation
                self.decisions.pop(decision.decision_id, None)
                self._restore_inboxes((initiator, actor), old_inboxes)
                raise
            if attitude_changed:
                self._emit_event(
                    "team_formation_invitation_responded",
                    {
                        "request_id": request.request_id,
                        "agent_id": actor.agent_id,
                        "attitude": attitude.value,
                    },
                )
            return FormationOperationResult(
                status="INVITATION_UPDATED",
                request_id=request.request_id,
                summary=self.formation_summary(request.request_id),
                reason=(
                    "The Agent explicitly chose not to publish an attitude; the public "
                    "state remains NO_RESPONSE."
                    if explicit_no_response
                    else ""
                ),
            )
        if request.late_join_policy is LateJoinPolicy.REQUIRE_INITIATOR_CONFIRMATION:
            invitation.late_join_pending = True
            invitation.late_join_requested_at = time.time()
            try:
                self._notify_agent(
                    initiator.agent_id,
                    "team_formation_late_join_requested",
                    {
                        "request_id": request.request_id,
                        "agent_id": actor.agent_id,
                        "summary": self.formation_summary(request.request_id).model_dump(mode="json"),
                    },
                )
                await self.manager._commit_dirty_state(
                    self._dirty(
                        request.request_id,
                        inbox_agent_ids={initiator.agent_id},
                        decision_history=True,
                    )
                )
            except Exception:
                self.invitations[(request.request_id, actor.agent_id)] = old_invitation
                self.decisions.pop(decision.decision_id, None)
                self._restore_inboxes((initiator, actor), old_inboxes)
                raise
            self._emit_event(
                "team_formation_late_join_requested",
                {"request_id": request.request_id, "agent_id": actor.agent_id},
            )
            return FormationOperationResult(
                status="LATE_JOIN_PENDING",
                request_id=request.request_id,
                summary=self.formation_summary(request.request_id),
                team_id=request.created_team_id,
            )
        return await self._commit_late_join(
            request,
            invitation,
            actor,
            rollback_invitation=old_invitation,
            rollback_inboxes=old_inboxes,
            decision_id=decision.decision_id,
        )

    async def decide_late_join(
        self,
        request_id: str,
        invitee_agent_id: str,
        *,
        actor: Agent,
        proposal_revision: int,
        approved: bool,
    ) -> FormationOperationResult:
        if type(approved) is not bool:
            raise TypeError("approved must be a boolean.")
        self._require_active_agent(actor)
        async with self.request_lock(request_id):
            self._require_active_agent(actor)
            request = self.requests.get(request_id)
            invitation = self.invitations.get((request_id, invitee_agent_id))
            if request is None or invitation is None:
                raise KeyError("The formation or invitee was not found.")
            if actor.agent_id != request.initiator_agent_id:
                raise PermissionError("Only the initiating Agent may decide this late join.")
            self._assert_request_integrity(request)
            if (
                not isinstance(proposal_revision, int)
                or isinstance(proposal_revision, bool)
                or proposal_revision < 1
            ):
                raise TypeError("proposal_revision must be a positive integer.")
            if proposal_revision != request.proposal_revision:
                return self._stale_revision_result(request, proposal_revision)
            if request.status is not TeamFormationStatus.CREATED:
                raise ValueError("Late joining is available only after AgentTeam creation.")
            if not invitation.late_join_pending:
                raise ValueError("This invitee has no pending late-join request.")
            invitee = self.manager._agents_by_id.get(invitee_agent_id)
            if invitee is None:
                raise ValueError("The invited Agent no longer exists.")
            if not approved:
                old = invitation.model_copy(deep=True)
                old_inboxes = self._copy_inboxes((invitee,))
                invitation.late_join_pending = False
                invitation.late_join_decision = "denied"
                try:
                    self._notify_agent(
                        invitee.agent_id,
                        "team_formation_late_join_denied",
                        {"request_id": request_id, "team_id": request.created_team_id},
                    )
                    await self.manager._commit_dirty_state(
                        self._dirty(request_id, inbox_agent_ids={invitee.agent_id})
                    )
                except Exception:
                    self.invitations[(request_id, invitee_agent_id)] = old
                    self._restore_inboxes((invitee,), old_inboxes)
                    raise
                self._emit_event(
                    "team_formation_late_join_denied",
                    {"request_id": request_id, "agent_id": invitee.agent_id},
                )
                return FormationOperationResult(
                    status="DENIED",
                    request_id=request_id,
                    summary=self.formation_summary(request_id),
                    team_id=request.created_team_id,
                )
            return await self._commit_late_join(request, invitation, invitee)

    async def _commit_late_join(
        self,
        request: TeamFormationRequest,
        invitation: TeamFormationInvitation,
        invitee: Agent,
        *,
        rollback_invitation: Optional[TeamFormationInvitation] = None,
        rollback_inboxes: Optional[Dict[str, list[dict[str, Any]]]] = None,
        decision_id: Optional[str] = None,
    ) -> FormationOperationResult:
        old_invitation = rollback_invitation or invitation.model_copy(deep=True)
        old_inboxes = rollback_inboxes or self._copy_inboxes((invitee,))
        team: Optional[AgentTeam] = None
        commit_started = False
        try:
            self._require_active_agent(invitee)
            team = self.manager.teams.get(request.created_team_id or "")
            if team is None:
                raise ValueError("The created AgentTeam no longer exists.")
            async with team.state_lock:
                self._require_active_agent(invitee)
                old_members = list(team.members)
                try:
                    if any(member.agent_id == invitee.agent_id for member in team.members):
                        raise ValueError(
                            "The invited Agent is already a member of this AgentTeam."
                        )
                    team.members.append(invitee)
                    now = time.time()
                    invitation.joined_at = now
                    invitation.late_join_pending = False
                    invitation.late_join_requested_at = None
                    invitation.late_join_decision = "approved"
                    self._notify_agent(
                        invitee.agent_id,
                        "team_formation_late_joined",
                        {"request_id": request.request_id, "team_id": team.team_id},
                    )
                    commit_started = True
                    await self.manager._commit_dirty_state(
                        self._dirty(
                            request.request_id,
                            inbox_agent_ids={invitee.agent_id},
                            team_ids={team.team_id},
                            decision_history=decision_id is not None,
                        )
                    )
                except Exception:
                    team.members = old_members
                    raise
        except asyncio.CancelledError:
            if not commit_started:
                self.invitations[(request.request_id, invitee.agent_id)] = old_invitation
                restored_agents = [
                    self.manager._agents_by_id[agent_id]
                    for agent_id in old_inboxes
                    if agent_id in self.manager._agents_by_id
                ]
                self._restore_inboxes(restored_agents, old_inboxes)
                if decision_id is not None:
                    self.decisions.pop(decision_id, None)
            raise
        except Exception:
            self.invitations[(request.request_id, invitee.agent_id)] = old_invitation
            restored_agents = [
                self.manager._agents_by_id[agent_id]
                for agent_id in old_inboxes
                if agent_id in self.manager._agents_by_id
            ]
            self._restore_inboxes(restored_agents, old_inboxes)
            if decision_id is not None:
                self.decisions.pop(decision_id, None)
            raise
        if team is None:
            raise RuntimeError("Late-join validation completed without an AgentTeam.")
        self._emit_event(
            "team_formation_late_joined",
            {
                "request_id": request.request_id,
                "team_id": team.team_id,
                "agent_id": invitee.agent_id,
            },
        )
        return FormationOperationResult(
            status="JOINED",
            request_id=request.request_id,
            summary=self.formation_summary(request.request_id),
            team_id=team.team_id,
        )
