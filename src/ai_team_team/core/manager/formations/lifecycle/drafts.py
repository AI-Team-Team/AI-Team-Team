"""Optional validated artifacts prepared by the initiator, without model invocation."""

import time
import uuid
from typing import Any, Optional

from ....agent import Agent
from ....communication import ApprovalPrincipal
from ....formation import (
    FormationDraftStatus, FormationOperationResult, TeamFormationDraft,
    TeamFormationDraftCandidate, TeamFormationStatus, UnanimousAcceptanceAction,
)


class FormationDraftMixin:
    async def prepare_team_formation_draft(self, *, actor: Agent, objective: str,
            candidate: TeamFormationDraftCandidate, request_id: Optional[str] = None, parent=None):
        async with self.stage(request_id=request_id):
            return await self._prepare_team_formation_draft(actor=actor, objective=objective,
                candidate=candidate, request_id=request_id, parent=parent)

    async def _prepare_team_formation_draft(self, *, actor, objective, candidate, request_id, parent):
        self._require_active_agent(actor)
        if not isinstance(objective, str) or not objective.strip():
            raise ValueError("A draft requires its initiator's explicit objective.")
        candidate = TeamFormationDraftCandidate.model_validate(candidate, strict=True)
        team = self.manager._active_team.get()
        if team is not None and actor not in team.members:
            raise PermissionError("The current scope does not authorize this formation artifact.")
        request = self.requests.get(request_id) if request_id else None
        if request_id and (request is None or request.initiator_agent_id != actor.agent_id):
            raise PermissionError("Only the original initiator may prepare an exact-revision candidate.")
        if request is not None and parent is not None:
            raise ValueError("A revision candidate cannot change its proposal's explicit parent.")
        parent = self.manager._topology.resolve_parent(parent)
        creator_kind = request.creator_kind if request else "agent_team" if team else "agent"
        creator_id = request.creator_id if request else team.team_id if team else actor.agent_id
        now = time.time()
        current = self.manager._activity.current.get()
        draft = TeamFormationDraft(draft_id=f"TFDRAFT-{uuid.uuid4().hex}", initiator_agent_id=actor.agent_id,
            creator_kind=creator_kind, creator_id=creator_id,
            creator_team_id=creator_id if creator_kind == "agent_team" else None,
            parent_team_id=request.parent_team_id if request else getattr(parent, "team_id", None),
            parent_agent_id=request.parent_agent_id if request else parent.agent_id if isinstance(parent, Agent) else None,
            request_id=request_id, base_revision=request.proposal_revision if request else None,
            base_revision_fingerprint=request.revision_fingerprint if request else None,
            objective=objective, status=FormationDraftStatus.READY, participant_agent_ids=[actor.agent_id],
            initiator_invocation_id=current.invocation_id if current is not None and current.agent_id == actor.agent_id else None,
            candidate=candidate, created_at=now, updated_at=now)
        self._validate_draft_candidate(draft, candidate)
        if request is not None and not self._draft_base_is_current(draft):
            raise ValueError("The proposal is no longer an open exact-revision base.")
        self.drafts[draft.draft_id] = draft
        operation_id = f"FORMATION-PREPARE-{draft.draft_id}"
        try:
            await self.manager._commit_dirty_state(self._draft_dirty(draft.draft_id), operation_id=operation_id,
                authority_check=lambda: self._validate_draft_candidate(draft, candidate))
        finally:
            if operation_id in self.manager._records.receipts:
                self._emit_event("team_formation_candidate_prepared", {"draft_id": draft.draft_id,
                    "initiator_agent_id": actor.agent_id, "request_id": request_id})
        return draft.model_copy(deep=True)

    def _validate_draft_candidate(
        self,
        draft: TeamFormationDraft,
        candidate: TeamFormationDraftCandidate,
    ) -> None:
        self._require_proposal_authority(draft)
        initiator = self.manager._agents_by_id.get(draft.initiator_agent_id)
        if initiator is None:
            raise ValueError("The formation-draft initiator no longer exists.")
        invitees = self.manager._resolve_existing_team_members(
            None,
            candidate.existing_member_ids,
        )
        if any(agent.agent_id == initiator.agent_id for agent in invitees):
            raise ValueError(
                "The initiator cannot invite itself; use initiator_joins=True instead."
            )
        if not invitees and not candidate.initiator_joins:
            raise ValueError(
                "A proposal requires at least one invitee or initiator_joins=True."
            )
        creator: Any
        if draft.creator_kind == "agent_team":
            creator = self.manager.teams.get(draft.creator_id)
        else:
            creator = self.manager._agents_by_id.get(draft.creator_id)
        if creator is None:
            raise ValueError("The formation-draft creator no longer exists.")
        parent = (ApprovalPrincipal(kind="agent_team", principal_id=draft.parent_team_id) if draft.parent_team_id
            else ApprovalPrincipal(kind="agent", principal_id=draft.parent_agent_id) if draft.parent_agent_id else None)
        self.manager._team_creation.validate_creation_depth(self.manager._topology.resolve_parent(parent))
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

    def _draft_base_is_current(self, draft: TeamFormationDraft) -> bool:
        if draft.request_id is None:
            return True
        request = self.requests.get(draft.request_id)
        return bool(
            request is not None
            and request.proposal_revision == draft.base_revision
            and request.revision_fingerprint == draft.base_revision_fingerprint
            and request.status
            in {
                TeamFormationStatus.COLLECTING_RESPONSES,
                TeamFormationStatus.READY_FOR_CONFIRMATION,
            }
        )

    def _draft_dirty(
        self,
        draft_id: str,
        *,
        inbox_agent_id: Optional[str] = None,
    ) -> dict[str, Any]:
        dirty = self.manager._new_dirty_state()
        dirty["configs"] = True
        dirty["formation_drafts"].add(draft_id)
        if inbox_agent_id is not None:
            dirty["agent_inboxes"].add(inbox_agent_id)
        return dirty

    async def publish_team_formation_draft(
        self,
        draft_id: str,
        *,
        actor: Agent,
    ) -> FormationOperationResult:
        """Explicitly publishes a ready initial proposal or exact next revision."""
        self._require_active_agent(actor)
        async with self.draft_lock(draft_id):
            draft = self.drafts[draft_id]
            if actor.agent_id != draft.initiator_agent_id:
                raise PermissionError("Only the initiating Agent may publish this draft.")
            if draft.status is not FormationDraftStatus.READY or draft.candidate is None:
                raise ValueError("Only a ready validated draft can be published.")
            if draft.request_id is None:
                return await self._publish_initial_draft(draft, actor)

            async with self.request_lock(draft.request_id):
                draft = self.drafts[draft_id]
                request = self.requests[draft.request_id]
                if not self._draft_base_is_current(draft):
                    await self._mark_draft_stale(draft)
                    return self._stale_revision_result(
                        request,
                        draft.base_revision or 0,
                    )
                result = await self._revise_locked(
                    request,
                    actor=actor,
                    base_revision=draft.base_revision or 0,
                    changes=draft.candidate.as_patch(),
                    source_draft=draft,
                )
                if result.status == "UNCHANGED":
                    old_draft = draft.model_copy(deep=True)
                    draft.status = FormationDraftStatus.PUBLISHED
                    draft.reason = "The candidate matched the current proposal; no revision was created."
                    draft.updated_at = time.time()
                    try:
                        await self.manager._commit_dirty_state(
                            self._draft_dirty(draft.draft_id),
                            authority_check=lambda: self._validate_draft_candidate(draft, draft.candidate),
                        )
                    except Exception:
                        self.drafts[draft.draft_id] = old_draft
                        raise
                    self._emit_event(
                        "team_formation_draft_published",
                        {
                            "draft_id": draft.draft_id,
                            "request_id": request.request_id,
                            "proposal_revision": request.proposal_revision,
                            "created_revision": False,
                        },
                    )
                    return FormationOperationResult(
                        status="DRAFT_PUBLISHED",
                        request_id=request.request_id,
                        summary=result.summary,
                        reason=draft.reason,
                    )
                return result

    async def _publish_initial_draft(
        self,
        draft: TeamFormationDraft,
        actor: Agent,
    ) -> FormationOperationResult:
        candidate = draft.candidate
        if candidate is None:
            raise ValueError("A publishable draft must contain a candidate.")
        if not self._draft_base_is_current(draft):
            await self._mark_draft_stale(draft)
            raise ValueError("The formation draft is stale.")
        creator: Any
        if draft.creator_kind == "agent_team":
            creator = self.manager.teams.get(draft.creator_id)
        else:
            creator = self.manager._agents_by_id.get(draft.creator_id)
        if creator is None:
            raise ValueError("The formation-draft creator no longer exists.")
        self._validate_draft_candidate(draft, candidate)

        old_draft = draft.model_copy(deep=True)
        dirty = self.manager._new_dirty_state(provisional=True)
        operation_id = f"FORMATION-PUBLISH-{draft.draft_id}"
        batch_token = self.manager._persistence_batch.set(dirty)
        request = None
        try:
            try:
                request = self.propose_team_formation(
                    creator=creator,
                    member_count=candidate.member_count,
                    roles_and_presets=(
                        [tuple(item) for item in candidate.roles_and_presets]
                        if candidate.roles_and_presets is not None
                        else None
                    ),
                    preset_name=candidate.preset_name,
                    system_instructions=candidate.system_instructions,
                    team_purpose=candidate.team_purpose,
                    roles_and_models=candidate.roles_and_models,
                    member_configs=candidate.member_configs,
                    existing_member_ids=candidate.existing_member_ids,
                    is_public_visible=candidate.is_public_visible,
                    initial_docs=candidate.initial_docs,
                    initiating_agent=actor,
                    initiator_joins=candidate.initiator_joins,
                    unanimous_acceptance_action=(
                        candidate.unanimous_acceptance_action.value
                    ),
                    late_join_policy=candidate.late_join_policy.value,
                    task=candidate.task,
                    _source_draft_id=draft.draft_id,
                    _emit_event=False,
                    _schedule_auto_create=False,
                    parent=(ApprovalPrincipal(kind="agent_team", principal_id=draft.parent_team_id) if draft.parent_team_id
                        else ApprovalPrincipal(kind="agent", principal_id=draft.parent_agent_id) if draft.parent_agent_id else None),
                )
                draft.status = FormationDraftStatus.PUBLISHED
                draft.reason = "The initiator's candidate was explicitly published as revision 1."
                draft.updated_at = time.time()
                self.manager._auto_save(formation_drafts={draft.draft_id})
            finally:
                self.manager._persistence_batch.reset(batch_token)
            await self.manager._commit_dirty_state(dirty, operation_id=operation_id,
                authority_check=lambda: self._validate_draft_candidate(draft, candidate))
        except BaseException:
            if operation_id in self.manager._records.receipts:
                raise
            if request is not None:
                self.requests.pop(request.request_id, None)
                self.revisions.pop(f"{request.request_id}:1", None)
                for key in [key for key in self.invitations if key[0] == request.request_id]:
                    self.invitations.pop(key, None)
            self.drafts[draft.draft_id] = old_draft
            raise
        finally:
            accepted = operation_id in self.manager._records.receipts
            self.manager._inbox.finish_provisional(dirty, accepted=accepted)
            if (accepted and not candidate.existing_member_ids
                    and candidate.unanimous_acceptance_action is UnanimousAcceptanceAction.AUTO_CREATE):
                self._schedule_empty_auto_creation(self.requests[request.request_id])

        self._emit_event(
            "team_formation_proposed",
            {
                "request_id": request.request_id,
                "initiator_agent_id": actor.agent_id,
                "invitee_count": len(candidate.existing_member_ids),
                "source_draft_id": draft.draft_id,
            },
        )
        self._emit_event(
            "team_formation_draft_published",
            {
                "draft_id": draft.draft_id,
                "request_id": request.request_id,
                "proposal_revision": 1,
            },
        )
        return FormationOperationResult(
            status="DRAFT_PUBLISHED",
            request_id=request.request_id,
            summary=self.formation_summary(request.request_id),
            reason=draft.reason,
        )

    async def _mark_draft_stale(self, draft: TeamFormationDraft) -> None:
        old_draft = draft.model_copy(deep=True)
        draft.status = FormationDraftStatus.STALE
        draft.reason = "The proposal revision no longer matches this draft's immutable base."
        draft.updated_at = time.time()
        try:
            await self.manager._commit_dirty_state(self._draft_dirty(draft.draft_id))
        except Exception:
            self.drafts[draft.draft_id] = old_draft
            raise
