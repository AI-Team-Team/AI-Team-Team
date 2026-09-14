"""Atomic proposal revision and renewed-consent lifecycle."""

import time
from typing import Any, Optional

from ....agent import Agent
from ....formation import (
    FormationDraftStatus,
    FormationOperationResult,
    InvitationAttitude,
    TeamFormationDraft,
    TeamFormationInvitation,
    TeamFormationRequest,
    TeamFormationRevisionPatch,
    TeamFormationStatus,
    UnanimousAcceptanceAction,
)
from ....team import AgentTeam


class FormationRevisionMixin:
    async def revise_team_formation(
        self,
        request_id: str,
        *,
        actor: Agent,
        base_revision: int,
        changes: TeamFormationRevisionPatch,
    ) -> FormationOperationResult:
        self._require_active_agent(actor)
        if not isinstance(changes, TeamFormationRevisionPatch):
            changes = TeamFormationRevisionPatch.model_validate(changes, strict=True)
        async with self.request_lock(request_id):
            self._require_active_agent(actor)
            request = self.requests.get(request_id)
            if request is None:
                raise KeyError(f"Unknown team formation request {request_id!r}.")
            if actor.agent_id != request.initiator_agent_id:
                raise PermissionError("Only the initiating Agent may revise this formation.")
            if (
                request.parent_team_id is not None
                and self.manager.config.formation_deliberation_policy
                == "required_when_team_scoped"
            ):
                raise PermissionError(
                    "Team-scoped formation revision requires a published collaborative draft."
                )
            return await self._revise_locked(
                request,
                actor=actor,
                base_revision=base_revision,
                changes=changes,
            )

    async def _revise_locked(
        self,
        request: TeamFormationRequest,
        *,
        actor: Agent,
        base_revision: int,
        changes: TeamFormationRevisionPatch,
        source_draft: Optional[TeamFormationDraft] = None,
    ) -> FormationOperationResult:
        self._assert_request_integrity(request)
        if (
            not isinstance(base_revision, int)
            or isinstance(base_revision, bool)
            or base_revision < 1
        ):
            raise TypeError("base_revision must be a positive integer.")
        if base_revision != request.proposal_revision:
            return self._stale_revision_result(request, base_revision)
        if request.status not in {
            TeamFormationStatus.COLLECTING_RESPONSES,
            TeamFormationStatus.READY_FOR_CONFIRMATION,
        }:
            raise ValueError("Created and abandoned formations are immutable.")

        candidate = request.model_copy(deep=True)
        update = changes.model_dump(mode="python", exclude_unset=True)
        invitee_ids = update.pop("existing_member_ids", None)
        for field, value in update.items():
            setattr(candidate, field, value)
        if invitee_ids is not None:
            candidate.invitee_agent_ids = list(invitee_ids)

        initiator = self.manager._agents_by_id.get(request.initiator_agent_id)
        if initiator is None:
            raise ValueError("The initiating Agent no longer exists.")
        self._require_active_agent(initiator)
        creator = self._resolve_request_creator(request)
        parent = self._resolve_request_parent(request)
        if isinstance(creator, AgentTeam) and all(
            member.agent_id != actor.agent_id for member in creator.members
        ):
            raise PermissionError(
                "The initiating Agent is no longer a member of the creator AgentTeam."
            )
        if isinstance(creator, Agent) and parent is not None and all(
            member.agent_id != actor.agent_id for member in parent.members
        ):
            raise PermissionError(
                "The initiating Agent is no longer a member of the intended parent AgentTeam."
            )

        content_fingerprint = self._proposal_fingerprint(
            self._request_content(candidate)
        )
        if content_fingerprint == request.content_fingerprint:
            return FormationOperationResult(
                status="UNCHANGED",
                request_id=request.request_id,
                summary=self.formation_summary(request.request_id),
                reason="The normalized proposal content is unchanged.",
            )

        invitees = self.manager._resolve_existing_team_members(
            None,
            candidate.invitee_agent_ids,
        )
        if any(agent.agent_id == initiator.agent_id for agent in invitees):
            raise ValueError(
                "The initiator cannot invite itself; use initiator_joins=True instead."
            )
        if not invitees and not candidate.initiator_joins:
            raise ValueError(
                "A formation request requires at least one existing invitee or initiator_joins=True."
            )
        proposed_existing = list(invitees)
        if candidate.initiator_joins:
            proposed_existing.append(initiator)
        self.manager._validate_team_creation_inputs(
            creator=creator,
            member_count=candidate.member_count,
            roles_and_presets=(
                [tuple(item) for item in candidate.roles_and_presets]
                if candidate.roles_and_presets is not None
                else None
            ),
            roles_and_models=candidate.roles_and_models,
            member_configs=candidate.member_configs,
            existing_members=proposed_existing,
            existing_member_ids=None,
            initial_docs=candidate.initial_docs,
            preset_name=candidate.preset_name,
            system_instructions=candidate.system_instructions,
            team_purpose=candidate.team_purpose,
            is_public_visible=candidate.is_public_visible,
        )

        now = time.time()
        candidate.proposal_revision = request.proposal_revision + 1
        candidate.content_fingerprint = content_fingerprint
        candidate.revision_fingerprint = self._revision_fingerprint(
            request.request_id,
            candidate.proposal_revision,
            content_fingerprint,
        )
        candidate.status = (
            TeamFormationStatus.READY_FOR_CONFIRMATION
            if not candidate.invitee_agent_ids
            and candidate.unanimous_acceptance_action
            is UnanimousAcceptanceAction.REQUIRE_CONFIRMATION
            else TeamFormationStatus.COLLECTING_RESPONSES
        )
        candidate.decision_reason = ""
        candidate.updated_at = now
        candidate.resolved_at = None

        old_request = request
        old_invitations = {
            key: value.model_copy(deep=True)
            for key, value in self.invitations.items()
            if key[0] == request.request_id
        }
        old_invitee_ids = set(request.invitee_agent_ids)
        new_invitee_ids = set(candidate.invitee_agent_ids)
        notification_ids = old_invitee_ids | new_invitee_ids | {actor.agent_id}
        notification_agents = [
            self.manager._agents_by_id[agent_id]
            for agent_id in notification_ids
            if agent_id in self.manager._agents_by_id
        ]
        old_inboxes = self._copy_inboxes(notification_agents)
        old_draft = source_draft.model_copy(deep=True) if source_draft is not None else None
        stale_drafts = {}
        revision = self._revision_record(
            candidate,
            revised_by_agent_id=actor.agent_id,
            source_draft_id=source_draft.draft_id if source_draft is not None else None,
        )

        try:
            self.requests[request.request_id] = candidate
            for agent_id in old_invitee_ids - new_invitee_ids:
                self.invitations.pop((request.request_id, agent_id), None)
            for agent_id in candidate.invitee_agent_ids:
                key = (request.request_id, agent_id)
                invitation = self.invitations.get(key)
                if invitation is None:
                    invitation = TeamFormationInvitation(
                        request_id=request.request_id,
                        agent_id=agent_id,
                        proposal_revision=candidate.proposal_revision,
                    )
                    self.invitations[key] = invitation
                else:
                    invitation.proposal_revision = candidate.proposal_revision
                    invitation.attitude = InvitationAttitude.NO_RESPONSE
                    invitation.responded_at = None
                    invitation.joined_at = None
                    invitation.late_join_pending = False
                    invitation.late_join_requested_at = None
                    invitation.late_join_decision = None
            self.revisions[revision.revision_id] = revision
            stale_drafts = self._stale_ready_drafts(
                request.request_id,
                exclude_draft_ids=(
                    {source_draft.draft_id} if source_draft is not None else set()
                ),
                reason="A newer proposal revision superseded this draft's immutable base.",
                updated_at=now,
            )
            if source_draft is not None:
                source_draft.status = FormationDraftStatus.PUBLISHED
                source_draft.reason = (
                    "The collaborative draft was explicitly published as proposal "
                    f"revision {candidate.proposal_revision}."
                )
                source_draft.updated_at = now

            for agent_id in old_invitee_ids - new_invitee_ids:
                self._notify_agent(
                    agent_id,
                    "team_formation_invitation_removed",
                    {
                        "request_id": request.request_id,
                        "proposal_revision": candidate.proposal_revision,
                    },
                )
            for agent_id in new_invitee_ids - old_invitee_ids:
                self._notify_agent(
                    agent_id,
                    "team_formation_invitation",
                    {
                        "request_id": request.request_id,
                        "initiator_agent_id": actor.agent_id,
                        "team_purpose": candidate.team_purpose,
                        "proposal_revision": candidate.proposal_revision,
                        "revision_fingerprint": candidate.revision_fingerprint,
                    },
                )
            for agent_id in old_invitee_ids & new_invitee_ids:
                self._notify_agent(
                    agent_id,
                    "team_formation_revised",
                    {
                        "request_id": request.request_id,
                        "proposal_revision": candidate.proposal_revision,
                        "revision_fingerprint": candidate.revision_fingerprint,
                    },
                )
            self._notify_agent(
                actor.agent_id,
                "team_formation_revised",
                {
                    "request_id": request.request_id,
                    "proposal_revision": candidate.proposal_revision,
                    "revision_fingerprint": candidate.revision_fingerprint,
                },
            )
            await self.manager._commit_dirty_state(
                self._dirty(
                    request.request_id,
                    inbox_agent_ids=notification_ids,
                    revision_history=True,
                    draft_ids=(
                        set(stale_drafts)
                        | ({source_draft.draft_id} if source_draft is not None else set())
                    ),
                )
            )
        except Exception:
            self.requests[request.request_id] = old_request
            for key in [key for key in self.invitations if key[0] == request.request_id]:
                self.invitations.pop(key, None)
            self.invitations.update(old_invitations)
            self.revisions.pop(revision.revision_id, None)
            if source_draft is not None and old_draft is not None:
                self.drafts[source_draft.draft_id] = old_draft
            for draft_id, previous in stale_drafts.items():
                self.drafts[draft_id] = previous
            self._restore_inboxes(notification_agents, old_inboxes)
            raise

        self._emit_event(
            "team_formation_revised",
            {
                "request_id": request.request_id,
                "proposal_revision": candidate.proposal_revision,
                "initiator_agent_id": actor.agent_id,
                "source_draft_id": source_draft.draft_id if source_draft is not None else None,
            },
        )
        if source_draft is not None:
            self._emit_event(
                "team_formation_draft_published",
                {
                    "draft_id": source_draft.draft_id,
                    "request_id": request.request_id,
                    "proposal_revision": candidate.proposal_revision,
                },
            )
        if (
            not candidate.invitee_agent_ids
            and candidate.initiator_joins
            and candidate.unanimous_acceptance_action
            is UnanimousAcceptanceAction.AUTO_CREATE
        ):
            self._schedule_empty_auto_creation(candidate)
        return FormationOperationResult(
            status=("DRAFT_PUBLISHED" if source_draft is not None else "REVISED"),
            request_id=request.request_id,
            summary=self.formation_summary(request.request_id),
            reason="The proposal revision committed and retained invitees must consent again.",
        )
