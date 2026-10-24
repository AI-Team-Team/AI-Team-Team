import asyncio
import json
import os
import shutil
import tempfile
import unittest

from ai_team_team import (
    ATTConfig,
    ATTManager,
    Agent,
    FormationDraftStatus,
    InvitationAttitude,
    TeamFormationRevisionPatch,
    TeamFormationDraftCandidate,
    LateJoinPolicy,
    UnanimousAcceptanceAction,
)


class DraftClient:
    def __init__(self):
        self.candidate = {}
        self.prompts = []

    async def generate(self, prompt, require_json=False, **kwargs):
        self.prompts.append(str(prompt))
        if require_json and "Return only JSON matching this schema" in str(prompt):
            return json.dumps(self.candidate)
        if require_json:
            return '{"is_healthy":true,"reason":"Synthetic audit."}'
        if "Activity continues by default." in (kwargs.get("system_instruction") or ""):
            return "Action: set_activity_intent(intent={'kind': 'idle'})"
        return "Final Answer: Advisory formation design."

    def supports_native_tool_calling(self):
        return False


class HangingDraftClient:
    def __init__(self):
        self.started = asyncio.Event()

    async def generate(self, prompt, require_json=False, **kwargs):
        self.started.set()
        await asyncio.Event().wait()

    def supports_native_tool_calling(self):
        return False


class TestFormationRevisionsAndDeliberation(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="att-formation-revision-")
        self.client = DraftClient()
        self.root = Agent("Root", "Architect", self.client)
        self.manager = ATTManager(
            self.root,
            ATTConfig(
                workspace_root=self.tmpdir,
            ),
            persistence_mode="volatile",
        )
        self.manager.register_llm_client("draft", self.client)
        self.invitees = [
            Agent(f"Invitee{index}", "Researcher", self.client)
            for index in range(3)
        ]
        for invitee in self.invitees:
            self.manager.register_agent(invitee)

    async def asyncTearDown(self):
        await self.manager.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _proposal(self):
        return self.manager.create_agent_team(
            self.root, parent=self.root,
            member_configs={"NewAnalyst": {"model": "draft"}},
            existing_members=self.invitees[:2],
            team_purpose="Original purpose",
        )

    async def test_material_revision_resets_exact_consent_and_rejects_stale_actions(self):
        request = self._proposal()
        await self.manager.respond_team_invitation(
            request.request_id,
            actor=self.invitees[0],
            proposal_revision=1,
            attitude="accepted",
        )

        result = await self.manager.revise_team_formation(
            request.request_id,
            actor=self.root,
            base_revision=1,
            changes=TeamFormationRevisionPatch(
                team_purpose="Revised purpose",
                existing_member_ids=[
                    self.invitees[0].agent_id,
                    self.invitees[2].agent_id,
                ],
            ),
        )

        self.assertEqual(result.status, "REVISED")
        revised = self.manager.get_team_formation(request.request_id)
        self.assertEqual(revised.proposal_revision, 2)
        self.assertEqual(len(self.manager.list_team_formation_revisions(request.request_id)), 2)
        self.assertEqual(
            self.manager.get_team_formation_invitation(
                request.request_id,
                self.invitees[0].agent_id,
            ).attitude,
            InvitationAttitude.NO_RESPONSE,
        )
        with self.assertRaises(KeyError):
            self.manager.get_team_formation_invitation(
                request.request_id,
                self.invitees[1].agent_id,
            )
        stale = await self.manager.respond_team_invitation(
            request.request_id,
            actor=self.invitees[0],
            proposal_revision=1,
            attitude="accepted",
        )
        self.assertEqual(stale.status, "STALE_REVISION")

        unchanged = await self.manager.revise_team_formation(
            request.request_id,
            actor=self.root,
            base_revision=2,
            changes=TeamFormationRevisionPatch(team_purpose="Revised purpose"),
        )
        self.assertEqual(unchanged.status, "UNCHANGED")
        self.assertEqual(
            self.manager.get_team_formation(request.request_id).proposal_revision,
            2,
        )

    async def test_public_reads_cannot_mutate_authoritative_proposal(self):
        request = self._proposal()
        authoritative = self.manager._formations.requests[request.request_id]
        authoritative_revision = self.manager._formations.revisions[
            f"{request.request_id}:1"
        ]
        for field in ("member_configs", "invitee_agent_ids"):
            self.assertIsNot(
                getattr(authoritative, field),
                authoritative_revision.proposal_snapshot[field],
            )
        detached = self.manager.get_team_formation(request.request_id)
        detached.team_purpose = "Tampered copy"
        detached.invitee_agent_ids.clear()
        revision = self.manager.list_team_formation_revisions(request.request_id)[0]
        revision.proposal_snapshot["team_purpose"] = "Tampered history copy"

        authoritative = self.manager.get_team_formation(request.request_id)
        self.assertEqual(authoritative.team_purpose, "Original purpose")
        self.assertEqual(len(authoritative.invitee_agent_ids), 2)
        self.assertEqual(
            self.manager.list_team_formation_revisions(request.request_id)[0]
            .proposal_snapshot["team_purpose"],
            "Original purpose",
        )

    async def test_no_op_revision_remains_unchanged_when_live_minimum_increases(self):
        request = self._proposal()
        self.manager.config.min_subagent_team_size = 10

        result = await self.manager.revise_team_formation(
            request.request_id,
            actor=self.root,
            base_revision=request.proposal_revision,
            changes=TeamFormationRevisionPatch(team_purpose=request.team_purpose),
        )

        self.assertEqual(result.status, "UNCHANGED")
        self.assertEqual(
            len(self.manager.list_team_formation_revisions(request.request_id)),
            1,
        )

    async def test_revision_persistence_failure_rolls_back_every_authoritative_projection(self):
        request = self._proposal()
        await self.manager.respond_team_invitation(
            request.request_id,
            actor=self.invitees[0],
            proposal_revision=1,
            attitude="accepted",
        )
        request_before = self.manager.get_team_formation(request.request_id)
        invitation_before = self.manager.get_team_formation_invitation(
            request.request_id,
            self.invitees[0].agent_id,
        )
        revisions_before = self.manager.list_team_formation_revisions(request.request_id)
        inboxes_before = {
            agent.agent_id: [dict(message) for message in agent.agent_inbox]
            for agent in [self.root, *self.invitees]
        }
        original_commit = self.manager._commit_dirty_state

        async def fail_commit(_dirty, **_kwargs):
            raise OSError("Injected revision persistence failure.")

        self.manager._commit_dirty_state = fail_commit
        try:
            with self.assertRaisesRegex(OSError, "revision persistence"):
                await self.manager.revise_team_formation(
                    request.request_id,
                    actor=self.root,
                    base_revision=1,
                    changes=TeamFormationRevisionPatch(
                        team_purpose="Must not become authoritative"
                    ),
                )
        finally:
            self.manager._commit_dirty_state = original_commit

        self.assertEqual(
            self.manager.get_team_formation(request.request_id),
            request_before,
        )
        self.assertEqual(
            self.manager.get_team_formation_invitation(
                request.request_id,
                self.invitees[0].agent_id,
            ),
            invitation_before,
        )
        self.assertEqual(
            self.manager.list_team_formation_revisions(request.request_id),
            revisions_before,
        )
        self.assertEqual(
            {
                agent.agent_id: [dict(message) for message in agent.agent_inbox]
                for agent in [self.root, *self.invitees]
            },
            inboxes_before,
        )

    def test_public_proposal_api_rejects_internal_publication_controls(self):
        with self.assertRaisesRegex(TypeError, "not public API"):
            self.manager.propose_team_formation(
                creator=self.root,
                member_configs={"NewAnalyst": {"model": "draft"}},
                existing_members=self.invitees[:2],
                _deliberated=True,
            )

    async def test_collaborative_draft_is_detached_advisory_work_until_publication(self):
        peers = [
            Agent(f"CreatorPeer{index}", "Designer", self.client)
            for index in range(2)
        ]
        for peer in peers:
            self.manager.register_agent(peer)
        creator_team = self.manager.bootstrap_agent_team(
            self.root, parent=self.root,
            existing_members=[self.root, *peers],
        )
        unrelated_inbox_item = {
            "type": "unrelated_creator_work",
            "from": "test",
            "message": "Do not consume this during proposal design.",
        }
        creator_team.receive_message(unrelated_inbox_item)
        self.client.candidate = {
            "task": None,
            "member_count": 3,
            "roles_and_presets": None,
            "preset_name": "custom",
            "system_instructions": "Investigate carefully.",
            "team_purpose": "Collaboratively designed purpose",
            "roles_and_models": None,
            "member_configs": {"NewAnalyst": {"model": "draft"}},
            "existing_member_ids": [
                self.invitees[0].agent_id,
                self.invitees[1].agent_id,
            ],
            "initial_docs": {"brief.md": "Validated brief"},
            "is_public_visible": False,
            "initiator_joins": False,
            "unanimous_acceptance_action": "require_confirmation",
            "late_join_policy": "disabled",
        }

        agent_token = self.manager._active_tool_agent.set(self.root)
        team_token = self.manager._active_team.set(creator_team)
        try:
            draft = await self.manager.prepare_team_formation_draft(
                actor=self.root,
                objective="Design an incident investigation team.",
                candidate=TeamFormationDraftCandidate.model_validate_json(json.dumps(self.client.candidate)),
                parent=creator_team,
            )
        finally:
            self.manager._active_team.reset(team_token)
            self.manager._active_tool_agent.reset(agent_token)

        self.assertEqual(draft.status, FormationDraftStatus.READY)
        self.assertFalse(self.manager._formations.requests)
        self.assertIn(unrelated_inbox_item, creator_team.message_inbox)
        ready = self.manager.get_team_formation_draft(draft.draft_id, actor=self.root)
        self.assertEqual(ready.status, FormationDraftStatus.READY)
        self.assertEqual(
            set(ready.participant_agent_ids),
            {self.root.agent_id},
        )
        self.assertIsNone(ready.initiator_invocation_id)
        self.assertEqual(
            ready.candidate.team_purpose,
            "Collaboratively designed purpose",
        )
        self.assertFalse(self.client.prompts)
        self.assertFalse(self.manager._formations.requests)

        published = await self.manager.publish_team_formation_draft(
            ready.draft_id,
            actor=self.root,
        )
        self.assertEqual(published.status, "DRAFT_PUBLISHED")
        request = self.manager.get_team_formation(published.request_id)
        self.assertEqual(request.proposal_revision, 1)
        self.assertEqual(request.parent_team_id, creator_team.team_id)
        self.assertEqual(
            self.manager.get_team_formation_draft(ready.draft_id, actor=self.root).status,
            FormationDraftStatus.PUBLISHED,
        )
        self.assertTrue(
            all(
                self.manager.get_team_formation_invitation(
                    request.request_id,
                    invitee.agent_id,
                ).attitude
                is InvitationAttitude.NO_RESPONSE
                for invitee in self.invitees[:2]
            )
        )

    async def test_team_scoped_design_needs_no_compulsory_draft(self):
        creator_team = self.manager.bootstrap_agent_team(
            self.root, parent=self.root,
            member_configs={"PeerA": {}, "PeerB": {}, "PeerC": {}},
        )
        request = self.manager.create_agent_team(
            creator_team, parent=creator_team,
            member_configs={"NewAnalyst": {"model": "draft"}},
            existing_members=self.invitees[:2],
            initiating_agent=creator_team.members[0],
        )
        self.assertEqual(request.status.value, "collecting_responses")
        self.assertFalse(self.manager._formations.drafts)
        self.assertTrue(all(
            self.manager.get_team_formation_invitation(request.request_id, person.agent_id).attitude
            is InvitationAttitude.NO_RESPONSE for person in self.invitees[:2]
        ))
        self.assertFalse(self.client.prompts)

    async def test_team_scoped_revision_fails_after_initiator_leaves_creator_team(self):
        creator_team = self.manager.bootstrap_agent_team(
            self.root, parent=self.root,
            member_configs={"CreatorPeerA": {}, "CreatorPeerB": {}},
            existing_members=[self.root],
        )
        request = self.manager.create_agent_team(
            creator_team, parent=creator_team,
            member_configs={"NewAnalyst": {"model": "draft"}},
            existing_members=self.invitees[:2],
            initiating_agent=self.root,
        )
        creator_team.members.remove(self.root)

        with self.assertRaisesRegex(PermissionError, "no longer a member"):
            await self.manager.revise_team_formation(
                request.request_id,
                actor=self.root,
                base_revision=request.proposal_revision,
                changes=TeamFormationRevisionPatch(team_purpose="Unauthorized revision"),
            )

        current = self.manager.get_team_formation(request.request_id)
        self.assertEqual(current.proposal_revision, 1)
        self.assertNotEqual(current.team_purpose, "Unauthorized revision")

    async def test_collaborative_revision_publishes_exact_successor_and_renews_consent(self):
        peers = [
            Agent(f"RevisionPeer{index}", "Designer", self.client)
            for index in range(2)
        ]
        for peer in peers:
            self.manager.register_agent(peer)
        creator_team = self.manager.bootstrap_agent_team(
            self.root, parent=self.root,
            existing_members=[self.root, *peers],
        )
        request = self.manager.create_agent_team(
            creator_team, parent=creator_team,
            member_configs={"NewAnalyst": {"model": "draft"}},
            existing_members=self.invitees[:2],
            initiating_agent=self.root,
            team_purpose="Initial collaborative purpose",
        )
        await self.manager.respond_team_invitation(
            request.request_id,
            actor=self.invitees[0],
            proposal_revision=1,
            attitude="accepted",
        )
        self.client.candidate = {
            "task": None,
            "member_count": 3,
            "roles_and_presets": None,
            "preset_name": "custom",
            "system_instructions": "Investigate the revised scope.",
            "team_purpose": "Revised collaborative purpose",
            "roles_and_models": None,
            "member_configs": {"NewAnalyst": {"model": "draft"}},
            "existing_member_ids": [
                self.invitees[0].agent_id,
                self.invitees[1].agent_id,
            ],
            "initial_docs": None,
            "is_public_visible": False,
            "initiator_joins": False,
            "unanimous_acceptance_action": "require_confirmation",
            "late_join_policy": "disabled",
        }

        agent_token = self.manager._active_tool_agent.set(self.root)
        team_token = self.manager._active_team.set(creator_team)
        try:
            draft = await self.manager.prepare_team_formation_draft(
                actor=self.root,
                objective="Revise the investigation scope collaboratively.",
                candidate=TeamFormationDraftCandidate.model_validate_json(json.dumps(self.client.candidate)),
                request_id=request.request_id,
            )
        finally:
            self.manager._active_team.reset(team_token)
            self.manager._active_tool_agent.reset(agent_token)
        await asyncio.gather(*tuple(self.manager._formations.tasks))

        published = await self.manager.publish_team_formation_draft(
            draft.draft_id,
            actor=self.root,
        )

        self.assertEqual(published.status, "DRAFT_PUBLISHED")
        revised = self.manager.get_team_formation(request.request_id)
        self.assertEqual(revised.proposal_revision, 2)
        self.assertEqual(revised.team_purpose, "Revised collaborative purpose")
        self.assertTrue(
            all(
                self.manager.get_team_formation_invitation(
                    request.request_id,
                    invitee.agent_id,
                ).attitude
                is InvitationAttitude.NO_RESPONSE
                for invitee in self.invitees[:2]
            )
        )
        published_draft = self.manager.get_team_formation_draft(
            draft.draft_id,
            actor=self.root,
        )
        self.assertEqual(published_draft.status, FormationDraftStatus.PUBLISHED)
        self.assertIn("revision 2", published_draft.reason)
        self.assertEqual(
            self.manager.list_team_formation_revisions(request.request_id)[-1]
            .source_draft_id,
            draft.draft_id,
        )

    async def test_zero_invitee_auto_creation_has_a_trigger(self):
        request = self.manager.create_agent_team(
            self.root, parent=self.root,
            member_configs={"NewA": {}, "NewB": {}},
            initiator_joins=True,
            unanimous_acceptance_action="auto_create",
        )
        await asyncio.gather(*tuple(self.manager._formations.tasks))
        restored = self.manager.get_team_formation(request.request_id)
        self.assertEqual(restored.status.value, "created")
        self.assertIn(self.root, self.manager.teams[restored.created_team_id].members)

    async def test_draft_whose_exact_base_changes_becomes_stale(self):
        request = self._proposal()
        candidate = TeamFormationDraftCandidate(
            member_count=3, preset_name="custom", system_instructions="A personal candidate.",
            team_purpose="Candidate scope", member_configs={"NewAnalyst": {"model": "draft"}},
            existing_member_ids=[person.agent_id for person in self.invitees[:2]],
            is_public_visible=False, initiator_joins=False,
            unanimous_acceptance_action=UnanimousAcceptanceAction.REQUIRE_CONFIRMATION,
            late_join_policy=LateJoinPolicy.DISABLED,
        )
        draft = await self.manager.prepare_team_formation_draft(
            actor=self.root, objective="Consider an optional revision.",
            candidate=candidate, request_id=request.request_id,
        )
        await self.manager.revise_team_formation(
            request.request_id, actor=self.root, base_revision=request.proposal_revision,
            changes=TeamFormationRevisionPatch(team_purpose="A different committed revision"),
        )
        stale = self.manager.get_team_formation_draft(draft.draft_id, actor=self.root)
        self.assertEqual(stale.status, FormationDraftStatus.STALE)
        self.assertEqual(stale.candidate, candidate)
        with self.assertRaisesRegex(ValueError, "ready"):
            await self.manager.publish_team_formation_draft(stale.draft_id, actor=self.root)
        self.assertFalse(hasattr(self.manager, "retry_team_formation_draft"))
        db_path = os.path.join(self.tmpdir, "stale-candidate.db")
        await self.manager.save_state(db_path)
        await self.manager.close()
        restored = ATTManager(
            Agent("TemporaryStaleRoot", "Temporary", self.client),
            ATTConfig(workspace_root=self.tmpdir), persistence_mode="volatile",
        )
        restored.register_llm_client("draft", self.client)
        try:
            await restored.load_state(db_path)
            loaded = restored.get_team_formation_draft(stale.draft_id, actor=restored.root_ai)
            self.assertEqual(loaded.status, FormationDraftStatus.STALE)
            self.assertEqual(loaded.candidate, candidate)
        finally:
            await restored.close()

    async def test_zero_invitee_confirmation_proposal_is_immediately_ready(self):
        request = self.manager.create_agent_team(
            self.root, parent=self.root,
            member_configs={"NewA": {}, "NewB": {}},
            initiator_joins=True,
            unanimous_acceptance_action="require_confirmation",
        )

        self.assertEqual(request.status.value, "ready_for_confirmation")
        current = self.manager.get_team_formation(request.request_id)
        self.assertEqual(current.status.value, "ready_for_confirmation")
        self.assertTrue(
            self.manager.inspect_team_formation(
                request.request_id,
                actor=self.root,
            ).summary.can_create
        )

    async def test_revision_to_zero_invitees_triggers_auto_creation(self):
        request = self._proposal()
        result = await self.manager.revise_team_formation(
            request.request_id,
            actor=self.root,
            base_revision=1,
            changes=TeamFormationRevisionPatch(
                existing_member_ids=[],
                member_configs={"NewA": {}, "NewB": {}},
                initiator_joins=True,
                unanimous_acceptance_action=UnanimousAcceptanceAction.AUTO_CREATE,
            ),
        )
        self.assertEqual(result.status, "REVISED")
        await asyncio.gather(*tuple(self.manager._formations.tasks))
        revised = self.manager.get_team_formation(request.request_id)
        self.assertEqual(revised.status.value, "created")
        self.assertIn(self.root, self.manager.teams[revised.created_team_id].members)

    async def test_revision_to_zero_invitees_can_require_final_confirmation(self):
        request = self._proposal()
        result = await self.manager.revise_team_formation(
            request.request_id,
            actor=self.root,
            base_revision=1,
            changes=TeamFormationRevisionPatch(
                existing_member_ids=[],
                member_configs={"NewA": {}, "NewB": {}},
                initiator_joins=True,
                unanimous_acceptance_action=(
                    UnanimousAcceptanceAction.REQUIRE_CONFIRMATION
                ),
            ),
        )

        self.assertEqual(result.status, "REVISED")
        revised = self.manager.get_team_formation(request.request_id)
        self.assertEqual(revised.status.value, "ready_for_confirmation")
        self.assertFalse(self.manager._formations.tasks)

    async def test_published_draft_and_revision_provenance_restore(self):
        workspace = os.path.join(self.tmpdir, "draft-persistence")
        os.makedirs(workspace)
        db_path = os.path.join(workspace, "state.db")
        client = DraftClient()
        root = Agent("PersistentRoot", "Architect", client)
        manager = ATTManager(
            root,
            ATTConfig(workspace_root=workspace),
            db_path=db_path,
            persistence_mode=("durable" if (db_path) else "volatile"),
        )
        manager.register_llm_client("draft-persist", client)
        manager.bootstrap_agent_team(
            root, parent=root,
            existing_members=[root],
            member_configs={"RootPeerA": {}, "RootPeerB": {}},
        )
        manager.bootstrap_agent_team(
            root, parent=root,
            existing_members=[root],
            member_configs={"RootPeerC": {}, "RootPeerD": {}},
        )
        invitees = [
            manager.register_agent(
                Agent(f"PersistentInvitee{index}", "Researcher", client)
            )
            for index in range(2)
        ]
        client.candidate = {
            "task": None,
            "member_count": 3,
            "roles_and_presets": None,
            "preset_name": "custom",
            "system_instructions": "Persist the exact draft provenance.",
            "team_purpose": "Persistent collaborative draft",
            "roles_and_models": None,
            "member_configs": {"NewAnalyst": {"model": "draft-persist"}},
            "existing_member_ids": [agent.agent_id for agent in invitees],
            "initial_docs": None,
            "is_public_visible": False,
            "initiator_joins": False,
            "unanimous_acceptance_action": "require_confirmation",
            "late_join_policy": "disabled",
        }
        try:
            draft = await manager.prepare_team_formation_draft(
                actor=root,
                objective="Formulate a persistent proposal.",
                candidate=TeamFormationDraftCandidate.model_validate_json(json.dumps(client.candidate)),
            )
            await asyncio.gather(*tuple(manager._formations.tasks))
            published = await manager.publish_team_formation_draft(
                draft.draft_id,
                actor=root,
            )
            self.assertIsNone(
                manager.get_team_formation(published.request_id).parent_team_id
            )
            stale_draft = await manager.prepare_team_formation_draft(
                actor=root,
                objective="Consider a competing next revision.",
                candidate=TeamFormationDraftCandidate.model_validate_json(json.dumps(client.candidate)),
                request_id=published.request_id,
            )
            await asyncio.gather(*tuple(manager._formations.tasks))
            self.assertEqual(
                manager.get_team_formation_draft(
                    stale_draft.draft_id,
                    actor=root,
                ).status,
                FormationDraftStatus.READY,
            )
            revised = await manager.revise_team_formation(
                published.request_id,
                actor=root,
                base_revision=1,
                changes=TeamFormationRevisionPatch(
                    team_purpose="A directly committed competing revision"
                ),
            )
            self.assertEqual(revised.status, "REVISED")
            self.assertEqual(
                manager.get_team_formation_draft(
                    stale_draft.draft_id,
                    actor=root,
                ).status,
                FormationDraftStatus.STALE,
            )
            await manager.save_state()
        finally:
            await manager.close()

        restored = ATTManager(
            Agent("TemporaryPersistentRoot", "Temporary", client),
            ATTConfig(workspace_root=workspace),
            persistence_mode="volatile",
        )
        restored.register_llm_client("draft-persist", client)
        try:
            await restored.load_state(db_path)
            loaded_draft = restored.get_team_formation_draft(
                draft.draft_id,
                actor=restored.root_ai,
            )
            self.assertEqual(loaded_draft.status, FormationDraftStatus.PUBLISHED)
            revisions = restored.list_team_formation_revisions(published.request_id)
            self.assertEqual(len(revisions), 2)
            self.assertEqual(revisions[0].source_draft_id, draft.draft_id)
            self.assertIsNone(revisions[1].source_draft_id)
            self.assertIsNone(
                restored.get_team_formation(published.request_id).parent_team_id
            )
            self.assertEqual(
                revisions[0].proposal_snapshot["team_purpose"],
                loaded_draft.candidate.team_purpose,
            )
            self.assertEqual(
                restored.get_team_formation_draft(
                    stale_draft.draft_id,
                    actor=restored.root_ai,
                ).status,
                FormationDraftStatus.STALE,
            )
        finally:
            await restored.close()

    async def test_preparing_candidate_never_invokes_a_hanging_provider(self):
        workspace = os.path.join(self.tmpdir, "cancelled-draft")
        os.makedirs(workspace)
        db_path = os.path.join(workspace, "state.db")
        client = HangingDraftClient()
        root = Agent("HangingDraftRoot", "Architect", client)
        manager = ATTManager(
            root,
            ATTConfig(workspace_root=workspace),
            db_path=db_path,
            persistence_mode=("durable" if (db_path) else "volatile"),
        )
        manager.register_llm_client("hanging-draft", client)
        draft = await manager.prepare_team_formation_draft(
            actor=root,
            objective="Validate my design without an extra model call.",
            candidate=TeamFormationDraftCandidate(
                member_count=3, preset_name="custom", system_instructions="Validate locally.",
                team_purpose="Personal design", member_configs={"PeerOne": {}, "PeerTwo": {}},
                is_public_visible=False, initiator_joins=True,
                unanimous_acceptance_action=UnanimousAcceptanceAction.REQUIRE_CONFIRMATION,
                late_join_policy=LateJoinPolicy.DISABLED,
            ),
        )
        self.assertFalse(client.started.is_set())
        self.assertEqual(draft.status, FormationDraftStatus.READY)
        await asyncio.wait_for(manager.close(), timeout=1)

        replacement = DraftClient()
        restored = ATTManager(
            Agent("TemporaryCancelledRoot", "Temporary", replacement),
            ATTConfig(workspace_root=workspace),
            persistence_mode="volatile",
        )
        restored.register_llm_client("hanging-draft", replacement)
        try:
            await restored.load_state(db_path)
            loaded = restored.get_team_formation_draft(
                draft.draft_id,
                actor=restored.root_ai,
            )
            self.assertEqual(loaded.status, FormationDraftStatus.READY)
        finally:
            await restored.close()


if __name__ == "__main__":
    unittest.main()
