"""Atomic formation creation and abandonment."""

import time
from typing import Any, Dict, Optional

from ....agent import Agent
from ....formation import (
    FormationOperationResult,
    InvitationAttitude,
    TeamFormationRequest,
    TeamFormationStatus,
)
from ....team import AgentTeam


class FormationCreationMixin:
    async def create_team_from_formation(
        self,
        request_id: str,
        *,
        actor: Agent,
        proposal_revision: int,
    ) -> FormationOperationResult:
        self._require_active_agent(actor)
        async with self.request_lock(request_id):
            self._require_active_agent(actor)
            request = self.requests.get(request_id)
            if request is None:
                raise KeyError(f"Unknown team formation request {request_id!r}.")
            if actor.agent_id != request.initiator_agent_id:
                raise PermissionError("Only the initiating Agent may create this AgentTeam.")
            self._assert_request_integrity(request)
            if (
                not isinstance(proposal_revision, int)
                or isinstance(proposal_revision, bool)
                or proposal_revision < 1
            ):
                raise TypeError("proposal_revision must be a positive integer.")
            if proposal_revision != request.proposal_revision:
                return self._stale_revision_result(request, proposal_revision)
            try:
                return await self._finalize_locked(request, automatic=False)
            except ValueError as exc:
                request = self.requests[request_id]
                old_decision_reason = request.decision_reason
                old_updated_at = request.updated_at
                request.decision_reason = str(exc)
                request.updated_at = time.time()
                try:
                    await self.manager._commit_dirty_state(self._dirty(request_id))
                except Exception:
                    request.decision_reason = old_decision_reason
                    request.updated_at = old_updated_at
                    raise
                raise

    def _resolve_request_creator(self, request: TeamFormationRequest) -> Any:
        if request.creator_kind == "agent":
            creator = self.manager._agents_by_id.get(request.creator_id)
        else:
            creator = self.manager.teams.get(request.creator_id)
        if creator is None:
            raise ValueError("The formation creator no longer exists.")
        return creator

    def _resolve_request_parent(self, request: TeamFormationRequest) -> Optional[AgentTeam]:
        if request.parent_team_id is None:
            return None
        parent = self.manager.teams.get(request.parent_team_id)
        if parent is None:
            raise ValueError("The intended parent AgentTeam no longer exists.")
        return parent

    async def _finalize_locked(
        self,
        request: TeamFormationRequest,
        *,
        automatic: bool,
        extra_dirty: Optional[Dict[str, Any]] = None,
    ) -> FormationOperationResult:
        manager = self.manager
        self._assert_request_integrity(request)
        if request.status is TeamFormationStatus.CREATED:
            return FormationOperationResult(
                status="CREATED",
                request_id=request.request_id,
                summary=self.formation_summary(request.request_id),
                team_id=request.created_team_id,
                reason="The AgentTeam was already created.",
            )
        if request.status is TeamFormationStatus.ABANDONED:
            raise ValueError("An abandoned formation cannot be created.")
        summary = self.formation_summary(request.request_id)
        if not summary.can_create:
            raise ValueError(summary.eligibility_reason or "The formation is not eligible for creation.")
        creator = self._resolve_request_creator(request)
        parent = self._resolve_request_parent(request)
        initiator = manager._agents_by_id.get(request.initiator_agent_id)
        if initiator is None or initiator.lifecycle_state != "active":
            raise ValueError("The initiating Agent is no longer active.")
        if isinstance(creator, AgentTeam) and all(
            member.agent_id != initiator.agent_id for member in creator.members
        ):
            raise ValueError(
                "The initiating Agent is no longer a member of the creator AgentTeam."
            )
        if isinstance(creator, Agent) and parent is not None and all(
            member.agent_id != creator.agent_id for member in parent.members
        ):
            raise ValueError(
                "The initiating Agent is no longer a member of the intended parent AgentTeam."
            )
        accepted_invitations = [
            item
            for item in self._request_invitations(request.request_id)
            if item.attitude is InvitationAttitude.ACCEPTED
        ]
        missing_accepted = [
            item.agent_id
            for item in accepted_invitations
            if item.agent_id not in manager._agents_by_id
        ]
        if missing_accepted:
            raise ValueError(
                "Accepted Agent identities are no longer registered: "
                + ", ".join(sorted(missing_accepted))
            )
        accepted = [manager._agents_by_id[item.agent_id] for item in accepted_invitations]
        if request.initiator_joins:
            accepted.append(initiator)
        if len({agent.agent_id for agent in accepted}) != len(accepted):
            raise ValueError("The resolved founding membership contains duplicate Agents.")
        for agent in accepted:
            self._require_active_agent(agent)

        old_runtime = manager._team_creation_snapshot()
        old_request = request.model_copy(deep=True)
        old_invitations = {
            item.agent_id: item.model_copy(deep=True)
            for item in self._request_invitations(request.request_id)
        }
        notified_agents = [
            manager._agents_by_id[agent_id]
            for agent_id in {request.initiator_agent_id, *request.invitee_agent_ids}
            if agent_id in manager._agents_by_id
        ]
        old_inboxes = self._copy_inboxes(notified_agents)
        stale_drafts = {}
        team = None
        dirty = manager._new_dirty_state()
        if extra_dirty is not None:
            manager._merge_dirty_state(dirty, extra_dirty)
        batch_token = manager._persistence_batch.set(dirty)
        try:
            try:
                team = manager._team_creation.create_immediate(
                    creator=creator,
                    member_count=request.member_count,
                    roles_and_presets=(
                        [tuple(item) for item in request.roles_and_presets]
                        if request.roles_and_presets is not None
                        else None
                    ),
                    preset_name=request.preset_name,
                    system_instructions=request.system_instructions,
                    team_purpose=request.team_purpose,
                    roles_and_models=request.roles_and_models,
                    member_configs=request.member_configs,
                    existing_members=accepted,
                    existing_member_ids=None,
                    is_public_visible=request.is_public_visible,
                    initial_docs=request.initial_docs,
                    authorized_existing=True,
                    parent_override=parent,
                    parent_override_provided=True,
                    required_creator_member_agent_id=request.initiator_agent_id,
                    record_registration_events=False,
                )
                now = time.time()
                request.status = TeamFormationStatus.CREATED
                request.created_team_id = team.team_id
                request.updated_at = now
                request.resolved_at = now
                request.decision_reason = (
                    "Created automatically after unanimous acceptance."
                    if automatic
                    else "Created by the initiating Agent."
                )
                stale_drafts = self._stale_ready_drafts(
                    request.request_id,
                    reason="The AgentTeam was created before this draft was published.",
                    updated_at=now,
                )
                founding_ids = {agent.agent_id for agent in accepted}
                for invitation in self._request_invitations(request.request_id):
                    if invitation.agent_id in founding_ids:
                        invitation.joined_at = now
                        invitation.late_join_pending = False
                for agent in notified_agents:
                    self._notify_agent(
                        agent.agent_id,
                        "team_formation_created",
                        {
                            "request_id": request.request_id,
                            "team_id": team.team_id,
                            "joined": agent.agent_id in founding_ids,
                        },
                    )
                manager._auto_save(
                    formation_requests={request.request_id},
                    formation_invitations={request.request_id},
                    formation_drafts=set(stale_drafts),
                    agent_inboxes={agent.agent_id for agent in notified_agents},
                )
            finally:
                manager._persistence_batch.reset(batch_token)
            await manager._commit_dirty_state(dirty)
        except Exception:
            self.requests[request.request_id] = old_request
            for agent_id, invitation in old_invitations.items():
                self.invitations[(request.request_id, agent_id)] = invitation
            for draft_id, previous in stale_drafts.items():
                self.drafts[draft_id] = previous
            self._restore_inboxes(notified_agents, old_inboxes)
            if team is not None:
                with manager._topology_lock:
                    manager._rollback_team_creation(old_runtime)
            raise

        manager._emit_callback(
            "on_system_event",
            "team_formation_created",
            {
                "request_id": request.request_id,
                "team_id": team.team_id,
                "initiator_agent_id": request.initiator_agent_id,
            },
        )
        registration_event_ids = {
            manager._memory.record_event(
                "agent_registered",
                agent=agent,
                payload={"lifecycle_state": "active"},
                persist=False,
                inherit_context=False,
            ).event_id
            for agent in team.members
            if agent.agent_id not in {member.agent_id for member in accepted}
        }
        if registration_event_ids:
            manager._auto_save(memory_events=registration_event_ids)
        self._schedule_initial_task(request, team)
        return FormationOperationResult(
            status="CREATED",
            request_id=request.request_id,
            summary=self.formation_summary(request.request_id),
            team_id=team.team_id,
            reason=request.decision_reason,
        )

    async def abandon_team_formation(
        self,
        request_id: str,
        *,
        actor: Agent,
        proposal_revision: int,
        reason: str = "",
    ) -> FormationOperationResult:
        self._require_active_agent(actor)
        async with self.request_lock(request_id):
            self._require_active_agent(actor)
            request = self.requests.get(request_id)
            if request is None:
                raise KeyError(f"Unknown team formation request {request_id!r}.")
            if actor.agent_id != request.initiator_agent_id:
                raise PermissionError("Only the initiating Agent may abandon this formation.")
            self._assert_request_integrity(request)
            if (
                not isinstance(proposal_revision, int)
                or isinstance(proposal_revision, bool)
                or proposal_revision < 1
            ):
                raise TypeError("proposal_revision must be a positive integer.")
            if proposal_revision != request.proposal_revision:
                return self._stale_revision_result(request, proposal_revision)
            if request.status is TeamFormationStatus.CREATED:
                raise ValueError("A created AgentTeam cannot be abandoned through its formation.")
            if request.status is TeamFormationStatus.ABANDONED:
                return FormationOperationResult(
                    status="ABANDONED",
                    request_id=request_id,
                    summary=self.formation_summary(request_id),
                    reason=request.decision_reason,
                )
            old_request = request.model_copy(deep=True)
            recipients = [
                self.manager._agents_by_id[agent_id]
                for agent_id in {request.initiator_agent_id, *request.invitee_agent_ids}
                if agent_id in self.manager._agents_by_id
            ]
            old_inboxes = self._copy_inboxes(recipients)
            stale_drafts = {}
            now = time.time()
            try:
                request.status = TeamFormationStatus.ABANDONED
                request.decision_reason = reason
                request.updated_at = now
                request.resolved_at = now
                stale_drafts = self._stale_ready_drafts(
                    request_id,
                    reason="The formation was abandoned before this draft was published.",
                    updated_at=now,
                )
                for recipient in recipients:
                    self._notify_agent(
                        recipient.agent_id,
                        "team_formation_abandoned",
                        {"request_id": request_id, "reason": reason},
                    )
                await self.manager._commit_dirty_state(
                    self._dirty(
                        request_id,
                        inbox_agent_ids={agent.agent_id for agent in recipients},
                        draft_ids=set(stale_drafts),
                    )
                )
            except Exception:
                self.requests[request_id] = old_request
                for draft_id, previous in stale_drafts.items():
                    self.drafts[draft_id] = previous
                self._restore_inboxes(recipients, old_inboxes)
                raise
            self._emit_event(
                "team_formation_abandoned",
                {"request_id": request_id, "initiator_agent_id": actor.agent_id},
            )
            return FormationOperationResult(
                status="ABANDONED",
                request_id=request_id,
                summary=self.formation_summary(request_id),
                reason=reason,
            )
