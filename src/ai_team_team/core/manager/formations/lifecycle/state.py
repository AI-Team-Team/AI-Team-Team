"""Shared state and validation helpers for formation lifecycles."""

from typing import Any, Dict, Iterable, Optional

from ....agent import Agent
from ....formation import (
    FormationDraftStatus,
    FormationOperationResult,
    FormationStatusSummary,
    InvitationAttitude,
    TeamFormationInvitation,
    TeamFormationInspection,
    TeamFormationRequest,
    TeamFormationStatus,
)
from ....team import AgentTeam


class FormationStateMixin:
    def _stale_ready_drafts(
        self,
        request_id: str,
        *,
        exclude_draft_ids: Iterable[str] = (),
        reason: str,
        updated_at: float,
    ) -> Dict[str, Any]:
        """Invalidates completed candidates superseded by a request transition."""
        excluded = set(exclude_draft_ids)
        previous = {}
        for draft in self.drafts.values():
            if (
                draft.request_id != request_id
                or draft.draft_id in excluded
                or draft.status is not FormationDraftStatus.READY
            ):
                continue
            previous[draft.draft_id] = draft.model_copy(deep=True)
            draft.status = FormationDraftStatus.STALE
            draft.reason = reason
            draft.updated_at = updated_at
        return previous

    def _assert_request_integrity(self, request: TeamFormationRequest) -> None:
        content_fingerprint = self._proposal_fingerprint(
            self._request_content(request)
        )
        if content_fingerprint != request.content_fingerprint:
            raise ValueError(
                "The formation proposal content failed runtime fingerprint validation."
            )
        revision_fingerprint = self._revision_fingerprint(
            request.request_id,
            request.proposal_revision,
            content_fingerprint,
        )
        if revision_fingerprint != request.revision_fingerprint:
            raise ValueError(
                "The formation proposal revision failed runtime fingerprint validation."
            )
        invitations = self._request_invitations(request.request_id)
        if any(
            invitation.proposal_revision != request.proposal_revision
            for invitation in invitations
        ):
            raise ValueError(
                "The formation contains invitation state from a stale proposal revision."
            )
        revision = self.revisions.get(
            f"{request.request_id}:{request.proposal_revision}"
        )
        if (
            revision is None
            or revision.content_fingerprint != content_fingerprint
            or revision.revision_fingerprint != revision_fingerprint
            or revision.proposal_snapshot != self._request_content(request)
        ):
            raise ValueError(
                "The formation proposal has no matching immutable revision snapshot."
            )

    def _stale_revision_result(
        self,
        request: TeamFormationRequest,
        expected_revision: int,
    ) -> FormationOperationResult:
        return FormationOperationResult(
            status="STALE_REVISION",
            request_id=request.request_id,
            summary=self.formation_summary(request.request_id),
            team_id=request.created_team_id,
            reason=(
                f"Expected proposal revision {expected_revision}, but the current "
                f"revision is {request.proposal_revision}."
            ),
        )

    def _request_invitations(
        self,
        request_id: str,
    ) -> list[TeamFormationInvitation]:
        return [
            self.invitations[(request_id, agent_id)]
            for agent_id in self.requests[request_id].invitee_agent_ids
        ]

    @staticmethod
    def _new_member_count(request: TeamFormationRequest) -> int:
        if request.member_configs:
            return len(request.member_configs)
        if request.roles_and_presets:
            return len(request.roles_and_presets)
        return 0

    def _live_creation_error(self, request: TeamFormationRequest) -> str:
        if request.status not in {
            TeamFormationStatus.COLLECTING_RESPONSES,
            TeamFormationStatus.READY_FOR_CONFIRMATION,
        }:
            return f"A formation in {request.status.value!r} status cannot be created."
        try:
            creator = self._resolve_request_creator(request)
            parent = self._resolve_request_parent(request)
            initiator = self.manager._agents_by_id.get(request.initiator_agent_id)
            if initiator is None or initiator.lifecycle_state != "active":
                raise ValueError("The initiating Agent is no longer active.")
            self._require_active_agent(initiator)
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
            accepted = []
            for invitation in self._request_invitations(request.request_id):
                if invitation.attitude is not InvitationAttitude.ACCEPTED:
                    continue
                agent = self.manager._agents_by_id.get(invitation.agent_id)
                if agent is None:
                    raise ValueError(
                        f"Accepted Agent identity {invitation.agent_id!r} is no longer registered."
                    )
                self._require_active_agent(agent)
                accepted.append(agent)
            if request.initiator_joins:
                accepted.append(initiator)
            if len({agent.agent_id for agent in accepted}) != len(accepted):
                raise ValueError("The resolved founding membership contains duplicate Agents.")
            self.manager._validate_team_creation_inputs(
                creator=creator,
                member_count=request.member_count,
                roles_and_presets=(
                    [tuple(item) for item in request.roles_and_presets]
                    if request.roles_and_presets is not None
                    else None
                ),
                roles_and_models=request.roles_and_models,
                member_configs=request.member_configs,
                existing_members=accepted,
                existing_member_ids=None,
                initial_docs=request.initial_docs,
                preset_name=request.preset_name,
                system_instructions=request.system_instructions,
                team_purpose=request.team_purpose,
                is_public_visible=request.is_public_visible,
            )
        except (KeyError, PermissionError, TypeError, ValueError) as exc:
            return str(exc)
        return ""

    def formation_summary(self, request_id: str) -> FormationStatusSummary:
        request = self.requests.get(request_id)
        if request is None:
            raise KeyError(f"Unknown team formation request {request_id!r}.")
        invitations = self._request_invitations(request_id)
        counts = {attitude: 0 for attitude in InvitationAttitude}
        for invitation in invitations:
            counts[invitation.attitude] += 1
        eligible = (
            self._new_member_count(request)
            + counts[InvitationAttitude.ACCEPTED]
            + int(request.initiator_joins)
        )
        minimum = self.manager.config.min_subagent_team_size
        size_eligible = eligible >= minimum
        live_error = self._live_creation_error(request) if size_eligible else ""
        return FormationStatusSummary(
            request_id=request_id,
            status=request.status,
            accepted=counts[InvitationAttitude.ACCEPTED],
            declined=counts[InvitationAttitude.DECLINED],
            explicitly_ignored=counts[InvitationAttitude.EXPLICITLY_IGNORED],
            no_response=counts[InvitationAttitude.NO_RESPONSE],
            eligible_member_count=eligible,
            minimum_member_count=minimum,
            can_create=size_eligible and not live_error,
            eligibility_reason=(
                live_error
                if live_error
                else ""
                if size_eligible
                else (
                    f"The accepted founding membership has {eligible} members; "
                    f"at least {minimum} are required."
                )
            ),
            created_team_id=request.created_team_id,
        )

    def inspect_team_formation(
        self,
        request_id: str,
        *,
        actor: Agent,
    ) -> TeamFormationInspection:
        self._require_active_agent(actor)
        request = self.requests.get(request_id)
        if request is None:
            raise KeyError(f"Unknown team formation request {request_id!r}.")
        if actor.agent_id != request.initiator_agent_id and actor.agent_id not in request.invitee_agent_ids:
            raise PermissionError("Only the initiator or an invitee may inspect this formation.")
        return TeamFormationInspection(
            request=request.model_copy(deep=True),
            summary=self.formation_summary(request_id),
        )

    def _dirty(
        self,
        request_id: str,
        *,
        inbox_agent_ids: Iterable[str] = (),
        team_ids: Iterable[str] = (),
        revision_history: bool = False,
        decision_history: bool = False,
        draft_ids: Iterable[str] = (),
    ) -> Dict[str, Any]:
        dirty = self.manager._new_dirty_state()
        dirty["formation_requests"].add(request_id)
        dirty["formation_invitations"].add(request_id)
        dirty["agent_inboxes"].update(inbox_agent_ids)
        dirty["teams"].update(team_ids)
        if revision_history:
            dirty["formation_revisions"].add(request_id)
        if decision_history:
            dirty["formation_decisions"].add(request_id)
        dirty["formation_drafts"].update(draft_ids)
        return dirty

    def _emit_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        self.manager._emit_callback("on_system_event", event_type, payload)

    @staticmethod
    def _copy_inboxes(agents: Iterable[Agent]) -> Dict[str, list[dict[str, Any]]]:
        copies = {}
        for agent in agents:
            with agent.inbox_lock:
                copies[agent.agent_id] = [dict(message) for message in agent.agent_inbox]
        return copies

    @staticmethod
    def _restore_inboxes(agents: Iterable[Agent], copies: Dict[str, list[dict[str, Any]]]) -> None:
        for agent in agents:
            if agent.agent_id not in copies:
                continue
            with agent.inbox_lock:
                agent.agent_inbox = [dict(message) for message in copies[agent.agent_id]]

    def _require_active_agent(self, actor: Agent) -> None:
        if (
            self.manager._agents_by_id.get(actor.agent_id) is not actor
            or self.manager.agents.get(actor.name) is not actor
            or actor.lifecycle_state != "active"
        ):
            raise PermissionError("The acting Agent must be active and registered.")
