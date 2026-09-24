"""Detached collaborative formation-draft deliberation and publication."""

import asyncio
import json
import time
import uuid
from typing import Any, Optional

from pydantic import ValidationError

from ....agent import Agent
from ....formation import (
    FormationDraftStatus,
    FormationOperationResult,
    TeamFormationDraft,
    TeamFormationDraftCandidate,
    TeamFormationStatus,
    UnanimousAcceptanceAction,
)
from ....team import AgentTeam
from ....utils import generate_with_retry


def _response_text(response: Any) -> str:
    if isinstance(response, str):
        return response
    text = getattr(response, "text", None)
    if isinstance(text, str):
        return text
    raise ValueError("The proposal synthesizer returned no text response.")


def _clean_json(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[len("```json") :]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    return cleaned.strip()


class _StaleFormationDraftError(RuntimeError):
    """Signals that detached work can no longer target its immutable base."""


class FormationDraftMixin:
    async def discuss_team_formation_proposal(
        self,
        *,
        actor: Agent,
        objective: str,
        request_id: Optional[str] = None,
    ) -> TeamFormationDraft:
        """Persists and schedules advisory deliberation without waiting in the caller stack."""
        self._require_active_agent(actor)
        if not isinstance(objective, str):
            raise TypeError("objective must be a string.")
        if not objective.strip():
            raise ValueError("objective must be non-empty.")
        team = self.manager._active_team.get()
        if team is None:
            if actor is not self.manager.root_ai:
                raise PermissionError(
                    "A non-root Agent must invoke proposal deliberation from an AgentTeam context."
                )
            creator_kind = "agent"
            creator_id = actor.agent_id
            creator_team_id = None
        else:
            if self.manager.teams.get(team.team_id) is not team:
                raise ValueError("The invocation-scoped creator AgentTeam is not registered.")
            if all(member.agent_id != actor.agent_id for member in team.members):
                raise PermissionError(
                    "The initiating Agent must belong to the invocation-scoped AgentTeam."
                )
            creator_kind = "agent_team"
            creator_id = team.team_id
            creator_team_id = team.team_id

        if request_id is None:
            return await self._create_and_schedule_draft(
                actor=actor,
                objective=objective,
                creator_kind=creator_kind,
                creator_id=creator_id,
                creator_team_id=creator_team_id,
                request=None,
            )

        async with self.request_lock(request_id):
            request = self.requests.get(request_id)
            if request is None:
                raise KeyError(f"Unknown team formation request {request_id!r}.")
            self._assert_request_integrity(request)
            if actor.agent_id != request.initiator_agent_id:
                raise PermissionError(
                    "Only the initiating Agent may deliberate a proposal revision."
                )
            if request.status not in {
                TeamFormationStatus.COLLECTING_RESPONSES,
                TeamFormationStatus.READY_FOR_CONFIRMATION,
            }:
                raise ValueError("Created and abandoned formations cannot be revised.")
            if request.parent_team_id is None:
                if team is not None or actor is not self.manager.root_ai:
                    raise PermissionError(
                        "This standalone formation must be revised by its Root Agent initiator."
                    )
            elif team is None or team.team_id != request.parent_team_id:
                raise PermissionError(
                    "Proposal revision deliberation must use the immutable creator AgentTeam."
                )
            return await self._create_and_schedule_draft(
                actor=actor,
                objective=objective,
                creator_kind=creator_kind,
                creator_id=creator_id,
                creator_team_id=creator_team_id,
                request=request,
            )

    async def _create_and_schedule_draft(
        self,
        *,
        actor: Agent,
        objective: str,
        creator_kind: str,
        creator_id: str,
        creator_team_id: Optional[str],
        request: Optional[Any],
    ) -> TeamFormationDraft:
        now = time.time()
        draft = TeamFormationDraft(
            draft_id=f"TFDRAFT-{uuid.uuid4().hex}",
            initiator_agent_id=actor.agent_id,
            creator_kind=creator_kind,
            creator_id=creator_id,
            creator_team_id=creator_team_id,
            request_id=request.request_id if request is not None else None,
            base_revision=request.proposal_revision if request is not None else None,
            base_revision_fingerprint=(
                request.revision_fingerprint if request is not None else None
            ),
            objective=objective.strip(),
            created_at=now,
            updated_at=now,
        )
        self.drafts[draft.draft_id] = draft
        try:
            await self.manager._commit_dirty_state(
                self._draft_dirty(draft.draft_id)
            )
        except Exception:
            self.drafts.pop(draft.draft_id, None)
            raise
        self._schedule_formation_draft(draft.draft_id)
        self._emit_event(
            "team_formation_draft_scheduled",
            {
                "draft_id": draft.draft_id,
                "request_id": draft.request_id,
                "initiator_agent_id": actor.agent_id,
                "creator_team_id": creator_team_id,
            },
        )
        return draft.model_copy(deep=True)

    def _schedule_formation_draft(self, draft_id: str) -> None:
        self._track_task(self._run_formation_draft(draft_id))

    async def retry_team_formation_draft(
        self,
        draft_id: str,
        *,
        actor: Agent,
    ) -> TeamFormationDraft:
        """Explicitly retries restored, failed, or cancelled detached work."""
        self._require_active_agent(actor)
        async with self.draft_lock(draft_id):
            draft = self.drafts[draft_id]
            if actor.agent_id != draft.initiator_agent_id:
                raise PermissionError("Only the initiating Agent may retry this draft.")
            if draft.status not in {
                FormationDraftStatus.PENDING,
                FormationDraftStatus.FAILED,
                FormationDraftStatus.CANCELLED,
            }:
                raise ValueError(
                    f"A draft in {draft.status.value!r} status cannot be retried."
                )
            old_draft = draft.model_copy(deep=True)
            try:
                draft.status = FormationDraftStatus.PENDING
                draft.reason = ""
                draft.candidate = None
                draft.participant_agent_ids = []
                draft.source_discussion_id = None
                draft.updated_at = time.time()
                await self.manager._commit_dirty_state(
                    self._draft_dirty(draft.draft_id)
                )
            except Exception:
                self.drafts[draft_id] = old_draft
                raise
            result = draft.model_copy(deep=True)
        self._schedule_formation_draft(draft_id)
        return result

    async def _run_formation_draft(self, draft_id: str) -> None:
        async with self.draft_lock(draft_id):
            draft = self.drafts[draft_id]
            if draft.status is not FormationDraftStatus.PENDING:
                return
            old_draft = draft.model_copy(deep=True)
            try:
                draft.status = FormationDraftStatus.RUNNING
                draft.reason = ""
                draft.updated_at = time.time()
                await self.manager._commit_dirty_state(self._draft_dirty(draft_id))
            except Exception:
                self.drafts[draft_id] = old_draft
                raise

        try:
            candidate, participant_ids, discussion_id = await self._synthesize_draft(
                draft_id
            )
        except asyncio.CancelledError:
            await self._cancel_draft(draft_id)
            raise
        except _StaleFormationDraftError as exc:
            await self._stale_running_draft(draft_id, str(exc))
            return
        except Exception as exc:
            await self._fail_draft(draft_id, exc)
            return

        async with self.draft_lock(draft_id):
            draft = self.drafts[draft_id]
            if draft.status is not FormationDraftStatus.RUNNING:
                return
            old_draft = draft.model_copy(deep=True)
            if not self._draft_base_is_current(draft):
                draft.status = FormationDraftStatus.STALE
                draft.reason = "The proposal revision changed during deliberation."
            else:
                draft.status = FormationDraftStatus.READY
                draft.reason = "The validated structured draft is ready for explicit publication."
            draft.candidate = candidate
            draft.participant_agent_ids = participant_ids
            draft.source_discussion_id = discussion_id
            draft.updated_at = time.time()
            initiator = self.manager._agents_by_id.get(draft.initiator_agent_id)
            old_inboxes = self._copy_inboxes([initiator]) if initiator is not None else {}
            try:
                if initiator is not None:
                    self._notify_agent(
                        initiator.agent_id,
                        "team_formation_draft_completed",
                        {
                            "draft_id": draft.draft_id,
                            "request_id": draft.request_id,
                            "status": draft.status.value,
                            "base_revision": draft.base_revision,
                        },
                    )
                await self.manager._commit_dirty_state(
                    self._draft_dirty(
                        draft_id,
                        inbox_agent_id=(
                            initiator.agent_id if initiator is not None else None
                        ),
                    )
                )
            except Exception:
                self.drafts[draft_id] = old_draft
                if initiator is not None:
                    self._restore_inboxes([initiator], old_inboxes)
                raise
        self._emit_event(
            "team_formation_draft_completed",
            {
                "draft_id": draft_id,
                "request_id": draft.request_id,
                "status": draft.status.value,
                "source_discussion_id": discussion_id,
            },
        )

    async def _synthesize_draft(
        self,
        draft_id: str,
    ) -> tuple[TeamFormationDraftCandidate, list[str], Optional[str]]:
        draft = self.drafts[draft_id].model_copy(deep=True)
        initiator = self.manager._agents_by_id.get(draft.initiator_agent_id)
        if initiator is None:
            raise ValueError("The formation-draft initiator no longer exists.")
        self._require_active_agent(initiator)
        current_snapshot = None
        if draft.request_id is not None:
            request = self.requests.get(draft.request_id)
            if request is None or not self._draft_base_is_current(draft):
                raise _StaleFormationDraftError(
                    "The proposal revision changed before deliberation began."
                )
            current_snapshot = self._request_content(request)

        discussion_id = None
        participant_ids: list[str] = []
        transcript = ""
        if draft.creator_team_id is not None:
            team = self.manager.teams.get(draft.creator_team_id)
            if team is None:
                raise ValueError("The creator AgentTeam no longer exists.")
            prompt = self._draft_deliberation_prompt(draft, current_snapshot)
            result, participants = await self.manager._execute_team_discussion_with_members(
                team,
                prompt,
                rounds=self.manager.config.subagent_discussion_rounds,
                require_complete=True,
                process_inbox=False,
            )
            participant_ids = [agent.agent_id for agent in participants]
            if [agent.agent_id for agent in team.members] != participant_ids:
                raise RuntimeError(
                    "Creator AgentTeam membership changed during proposal deliberation."
                )
            transcript = result.transcript
            discussion_id = result.discussion_id

        if initiator.llm_client is None:
            raise RuntimeError("The initiating Agent has no available LLM client.")
        synthesis_prompt = self._draft_synthesis_prompt(
            draft,
            current_snapshot,
            transcript,
        )
        async with self.manager.agent_invocation(initiator):
            response = await generate_with_retry(
                llm_client=initiator.llm_client,
                prompt=synthesis_prompt,
                system_instruction=(
                    "You are the autonomous initiating Agent. Synthesize the advisory "
                    "discussion into one complete ATT team-formation candidate. Return "
                    "only strict JSON matching the supplied schema. Do not treat the "
                    "draft as consent from any invited Agent."
                ),
                temperature=0.1,
                require_json=True,
                retries=self.manager.config.llm_max_retries,
                backoff_factor=self.manager.config.llm_retry_backoff_factor,
                manager=self.manager,
            )
        try:
            candidate = TeamFormationDraftCandidate.model_validate_json(
                _clean_json(_response_text(response)),
                strict=True,
            )
        except (ValidationError, ValueError, TypeError) as exc:
            raise ValueError(f"The structured proposal draft is invalid: {exc}") from exc
        self._validate_draft_candidate(draft, candidate)
        if not participant_ids:
            participant_ids = [initiator.agent_id]
        return candidate, participant_ids, discussion_id

    def _draft_deliberation_prompt(
        self,
        draft: TeamFormationDraft,
        current_snapshot: Optional[dict[str, Any]],
    ) -> str:
        available_agents = [
            {
                "agent_id": agent.agent_id,
                "name": agent.name,
                "role": agent.role,
            }
            for agent in self.manager._agents_by_id.values()
            if agent.lifecycle_state == "active"
            and not self.manager.supervisor.is_supervisory_agent(agent.agent_id)
        ]
        return (
            "Collaboratively design an AgentTeam formation proposal. This discussion is "
            "advisory: it does not invite Agents, publish a proposal, or grant membership.\n\n"
            f"Initiator objective:\n{draft.objective}\n\n"
            f"Current proposal snapshot (null means a new proposal):\n"
            f"{json.dumps(current_snapshot, ensure_ascii=False, sort_keys=True)}\n\n"
            f"Active Agent identities that may be proposed as invitees:\n"
            f"{json.dumps(available_agents, ensure_ascii=False, sort_keys=True)}\n\n"
            "Discuss purpose, membership, new-Agent configurations, instructions, initial "
            "documents, initial task, visibility, completion behavior, and late-join policy."
        )

    @staticmethod
    def _draft_synthesis_prompt(
        draft: TeamFormationDraft,
        current_snapshot: Optional[dict[str, Any]],
        transcript: str,
    ) -> str:
        return (
            f"Objective:\n{draft.objective}\n\n"
            f"Current proposal snapshot:\n"
            f"{json.dumps(current_snapshot, ensure_ascii=False, sort_keys=True)}\n\n"
            f"Advisory AgentTeam transcript:\n{transcript or '[standalone formulation]'}\n\n"
            "Produce one complete candidate. Existing Agents must be referenced only by "
            "stable agent_id in existing_member_ids. The initiator must not appear there; "
            "use initiator_joins instead. Return only JSON matching this schema:\n"
            + json.dumps(
                TeamFormationDraftCandidate.model_json_schema(),
                ensure_ascii=False,
                sort_keys=True,
            )
        )

    def _validate_draft_candidate(
        self,
        draft: TeamFormationDraft,
        candidate: TeamFormationDraftCandidate,
    ) -> None:
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

    async def _fail_draft(self, draft_id: str, error: Exception) -> None:
        async with self.draft_lock(draft_id):
            draft = self.drafts[draft_id]
            if draft.status is not FormationDraftStatus.RUNNING:
                return
            old_draft = draft.model_copy(deep=True)
            draft.status = FormationDraftStatus.FAILED
            draft.reason = f"{type(error).__name__}: {error}"
            draft.updated_at = time.time()
            initiator = self.manager._agents_by_id.get(draft.initiator_agent_id)
            old_inboxes = self._copy_inboxes([initiator]) if initiator is not None else {}
            try:
                if initiator is not None:
                    self._notify_agent(
                        initiator.agent_id,
                        "team_formation_draft_failed",
                        {
                            "draft_id": draft_id,
                            "request_id": draft.request_id,
                            "error_type": type(error).__name__,
                        },
                    )
                await self.manager._commit_dirty_state(
                    self._draft_dirty(
                        draft_id,
                        inbox_agent_id=(
                            initiator.agent_id if initiator is not None else None
                        ),
                    )
                )
            except Exception:
                self.drafts[draft_id] = old_draft
                if initiator is not None:
                    self._restore_inboxes([initiator], old_inboxes)
                raise
        self._emit_event(
            "team_formation_draft_failed",
            {
                "draft_id": draft_id,
                "request_id": draft.request_id,
                "error_type": type(error).__name__,
            },
        )

    async def _stale_running_draft(self, draft_id: str, reason: str) -> None:
        async with self.draft_lock(draft_id):
            draft = self.drafts[draft_id]
            if draft.status is not FormationDraftStatus.RUNNING:
                return
            old_draft = draft.model_copy(deep=True)
            initiator = self.manager._agents_by_id.get(draft.initiator_agent_id)
            old_inboxes = self._copy_inboxes([initiator]) if initiator is not None else {}
            try:
                draft.status = FormationDraftStatus.STALE
                draft.reason = reason
                draft.updated_at = time.time()
                if initiator is not None:
                    self._notify_agent(
                        initiator.agent_id,
                        "team_formation_draft_completed",
                        {
                            "draft_id": draft.draft_id,
                            "request_id": draft.request_id,
                            "status": draft.status.value,
                            "base_revision": draft.base_revision,
                        },
                    )
                await self.manager._commit_dirty_state(
                    self._draft_dirty(
                        draft_id,
                        inbox_agent_id=(
                            initiator.agent_id if initiator is not None else None
                        ),
                    )
                )
            except Exception:
                self.drafts[draft_id] = old_draft
                if initiator is not None:
                    self._restore_inboxes([initiator], old_inboxes)
                raise
        self._emit_event(
            "team_formation_draft_completed",
            {
                "draft_id": draft_id,
                "request_id": draft.request_id,
                "status": FormationDraftStatus.STALE.value,
                "source_discussion_id": None,
            },
        )

    async def _cancel_draft(self, draft_id: str) -> None:
        draft = self.drafts.get(draft_id)
        if draft is None or draft.status not in {
            FormationDraftStatus.PENDING,
            FormationDraftStatus.RUNNING,
        }:
            return
        draft.status = FormationDraftStatus.CANCELLED
        draft.reason = "The detached proposal deliberation was cancelled."
        draft.updated_at = time.time()
        initiator = self.manager._agents_by_id.get(draft.initiator_agent_id)
        if initiator is not None:
            self._notify_agent(
                initiator.agent_id,
                "team_formation_draft_cancelled",
                {"draft_id": draft_id, "request_id": draft.request_id},
            )
        self.manager._auto_save(
            formation_drafts={draft_id},
            agent_inboxes=(
                {initiator.agent_id} if initiator is not None else set()
            ),
        )

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
                            self._draft_dirty(draft.draft_id)
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

        affected_ids = set(candidate.existing_member_ids) | {actor.agent_id}
        affected_agents = [
            self.manager._agents_by_id[agent_id]
            for agent_id in affected_ids
            if agent_id in self.manager._agents_by_id
        ]
        old_inboxes = self._copy_inboxes(affected_agents)
        old_draft = draft.model_copy(deep=True)
        dirty = self.manager._new_dirty_state()
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
                    _deliberated=True,
                    _source_draft_id=draft.draft_id,
                    _emit_event=False,
                    _schedule_auto_create=False,
                    _parent_team=(
                        creator if draft.creator_kind == "agent_team" else None
                    ),
                )
                draft.status = FormationDraftStatus.PUBLISHED
                draft.reason = "The collaborative draft was explicitly published as revision 1."
                draft.updated_at = time.time()
                self.manager._auto_save(formation_drafts={draft.draft_id})
            finally:
                self.manager._persistence_batch.reset(batch_token)
            await self.manager._commit_dirty_state(dirty)
        except Exception:
            if request is not None:
                self.requests.pop(request.request_id, None)
                self.revisions.pop(f"{request.request_id}:1", None)
                for key in [key for key in self.invitations if key[0] == request.request_id]:
                    self.invitations.pop(key, None)
            self.drafts[draft.draft_id] = old_draft
            self._restore_inboxes(affected_agents, old_inboxes)
            raise

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
        if (
            not candidate.existing_member_ids
            and candidate.unanimous_acceptance_action
            is UnanimousAcceptanceAction.AUTO_CREATE
        ):
            self._schedule_empty_auto_creation(self.requests[request.request_id])
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
