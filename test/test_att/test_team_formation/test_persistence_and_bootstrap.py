import asyncio
from contextlib import closing
import os
import shutil
import sqlite3
import tempfile
import unittest

from ai_team_team import ATTConfig, ATTManager, Agent, StateRestoreError


class EchoClient:
    async def generate(self, prompt, require_json=False, **kwargs):
        if require_json:
            return '{"is_healthy":true,"reason":"Synthetic audit."}'
        return "Final Answer: completed"

    def supports_native_tool_calling(self):
        return False


class TestFormationPersistenceAndBootstrap(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="att-formation-state-")
        self.db_path = os.path.join(self.tmpdir, "state.db")
        self.client = EchoClient()
        self.root = Agent("Root", "Architect", self.client)
        self.manager = ATTManager(
            self.root,
            ATTConfig(workspace_root=self.tmpdir),
            db_path=self.db_path,
        )
        self.manager.register_llm_client("echo", self.client)

    async def asyncTearDown(self):
        if not self.manager._closed:
            await self.manager.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    async def test_request_attitudes_and_agent_inboxes_restore(self):
        first = Agent("First", "Researcher", self.client)
        second = Agent("Second", "Reviewer", self.client)
        self.manager.register_agent(first)
        self.manager.register_agent(second)
        request = self.manager.create_agent_team(
            self.root,
            member_configs={"NewMember": {"model": "echo"}},
            existing_members=[first, second],
            late_join_policy="open",
        )
        await self.manager.respond_team_invitation(
            request.request_id,
            actor=first,
            attitude="accepted",
        )
        await self.manager.save_state()
        await self.manager.close()

        restored = ATTManager(
            Agent("Temporary", "Temporary", self.client),
            ATTConfig(workspace_root=self.tmpdir),
        )
        restored.register_llm_client("echo", self.client)
        try:
            await restored.load_state(self.db_path)
            loaded = restored.get_team_formation(request.request_id)
            self.assertEqual(loaded.status.value, "collecting_responses")
            self.assertEqual(
                restored.team_formation_invitations[
                    (request.request_id, first.agent_id)
                ].attitude.value,
                "accepted",
            )
            self.assertTrue(restored.list_agent_inbox(first.agent_id))
            self.assertTrue(restored.list_agent_inbox(second.agent_id))
        finally:
            await restored.close()

    async def test_explicit_empty_optional_maps_preserve_their_restore_fingerprint(self):
        invitees = [
            Agent(f"EmptyMapInvitee{index}", "Researcher", self.client)
            for index in range(3)
        ]
        for invitee in invitees:
            self.manager.register_agent(invitee)
        request = self.manager.create_agent_team(
            self.root,
            existing_members=invitees,
            member_configs={},
            roles_and_models={},
            initial_docs={},
        )
        await self.manager.save_state()
        await self.manager.close()

        restored = ATTManager(
            Agent("Temporary", "Temporary", self.client),
            ATTConfig(workspace_root=self.tmpdir),
        )
        restored.register_llm_client("echo", self.client)
        try:
            await restored.load_state(self.db_path)
            loaded = restored.get_team_formation(request.request_id)
            self.assertEqual(loaded.member_configs, {})
            self.assertEqual(loaded.roles_and_models, {})
            self.assertEqual(loaded.initial_docs, {})
        finally:
            await restored.close()

    async def test_corrupt_missing_invitation_fails_before_mutating_manager(self):
        invitees = [
            Agent(f"Invitee{index}", "Researcher", self.client)
            for index in range(3)
        ]
        for invitee in invitees:
            self.manager.register_agent(invitee)
        request = self.manager.create_agent_team(
            self.root,
            existing_members=invitees,
        )
        await self.manager.save_state()
        await self.manager.close()
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.execute(
                "DELETE FROM team_formation_invitations WHERE request_id = ? AND agent_id = ?",
                (request.request_id, invitees[0].agent_id),
            )
            connection.commit()

        target = ATTManager(
            Agent("TargetRoot", "Architect", self.client),
            ATTConfig(workspace_root=self.tmpdir),
        )
        target.register_llm_client("echo", self.client)
        baseline_root = target.root_ai
        baseline_agents = dict(target._agents_by_id)
        try:
            with self.assertRaises(StateRestoreError):
                await target.load_state(self.db_path)
            self.assertIs(target.root_ai, baseline_root)
            self.assertEqual(target._agents_by_id, baseline_agents)
            self.assertFalse(target.team_formation_requests)
        finally:
            await target.close()

    async def test_corrupt_non_boolean_formation_flag_is_not_coerced_during_restore(self):
        invitees = [
            Agent(f"BooleanInvitee{index}", "Researcher", self.client)
            for index in range(3)
        ]
        for invitee in invitees:
            self.manager.register_agent(invitee)
        request = self.manager.create_agent_team(
            self.root,
            existing_members=invitees,
        )
        await self.manager.save_state()
        await self.manager.close()
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.execute("PRAGMA ignore_check_constraints = ON")
            connection.execute(
                "UPDATE team_formation_requests SET initiator_joins = 2 WHERE request_id = ?",
                (request.request_id,),
            )
            connection.commit()

        target = ATTManager(
            Agent("TargetRoot", "Architect", self.client),
            ATTConfig(workspace_root=self.tmpdir),
        )
        target.register_llm_client("echo", self.client)
        try:
            with self.assertRaisesRegex(StateRestoreError, "team formation record"):
                await target.load_state(self.db_path)
            self.assertFalse(target.team_formation_requests)
        finally:
            await target.close()

    async def test_trusted_bootstrap_is_explicit_audited_and_not_agent_callable(self):
        member = Agent("Provisioned", "Researcher", self.client)
        self.manager.register_agent(member)
        identity_before = (
            member.name,
            member.role,
            member.llm_client,
            member.private_doc_library_id,
            member.lifecycle_state,
        )
        team = self.manager.bootstrap_agent_team(
            self.root,
            member_configs={"PeerOne": {}, "PeerTwo": {}},
            existing_members=[member],
        )
        self.assertIn(member, team.members)
        self.assertEqual(
            identity_before,
            (
                member.name,
                member.role,
                member.llm_client,
                member.private_doc_library_id,
                member.lifecycle_state,
            ),
        )
        events = [
            event
            for event in self.manager._memory.events.values()
            if event.event_type == "trusted_team_bootstrap"
            and event.team_id == team.team_id
        ]
        self.assertEqual(len(events), 1)
        self.assertIsNone(events[0].agent_id)
        self.assertNotIn("bootstrap_agent_team", team.tools)

    async def test_created_formation_rejects_corrupt_creator_provenance(self):
        invitees = [
            Agent(f"ProvenanceFounder{index}", "Researcher", self.client)
            for index in range(3)
        ]
        for invitee in invitees:
            self.manager.register_agent(invitee)
        request = self.manager.create_agent_team(
            self.root,
            existing_members=invitees,
        )
        for invitee in invitees:
            await self.manager.respond_team_invitation(
                request.request_id,
                actor=invitee,
                attitude="accepted",
            )
        created = await self.manager.create_team_from_formation(
            request.request_id,
            actor=self.root,
        )
        await self.manager.save_state()
        await self.manager.close()
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.execute(
                "UPDATE teams SET creator_agent_id = ? WHERE team_id = ?",
                (invitees[0].agent_id, created.team_id),
            )
            connection.commit()

        target = ATTManager(
            Agent("TargetRoot", "Architect", self.client),
            ATTConfig(workspace_root=self.tmpdir),
        )
        target.register_llm_client("echo", self.client)
        try:
            with self.assertRaisesRegex(StateRestoreError, "creator provenance"):
                await target.load_state(self.db_path)
            self.assertFalse(target.team_formation_requests)
        finally:
            await target.close()

    async def test_failed_authoritative_formation_commit_rolls_back_runtime_and_files(self):
        invitees = [
            Agent(f"RollbackFounder{index}", "Researcher", self.client)
            for index in range(3)
        ]
        for invitee in invitees:
            self.manager.register_agent(invitee)
        request = self.manager.create_agent_team(
            self.root,
            existing_members=invitees,
        )
        for invitee in invitees:
            await self.manager.respond_team_invitation(
                request.request_id,
                actor=invitee,
                attitude="accepted",
            )
        await self.manager.save_state()
        teams_before = set(self.manager.teams)
        agents_before = set(self.manager._agents_by_id)
        libraries_before = set(self.manager.libraries)
        managed_root = os.path.join(self.tmpdir, ".att_doc_libs")
        directories_before = set(os.listdir(managed_root))
        original_commit = self.manager._commit_dirty_state

        async def fail_commit(_dirty):
            raise OSError("Injected authoritative formation failure.")

        self.manager._commit_dirty_state = fail_commit
        try:
            with self.assertRaisesRegex(OSError, "authoritative formation"):
                await self.manager.create_team_from_formation(
                    request.request_id,
                    actor=self.root,
                )
        finally:
            self.manager._commit_dirty_state = original_commit

        self.assertEqual(set(self.manager.teams), teams_before)
        self.assertEqual(set(self.manager._agents_by_id), agents_before)
        self.assertEqual(set(self.manager.libraries), libraries_before)
        self.assertEqual(set(os.listdir(managed_root)), directories_before)
        restored_request = self.manager.get_team_formation(request.request_id)
        self.assertEqual(restored_request.status.value, "ready_for_confirmation")
        self.assertIsNone(restored_request.created_team_id)

    async def test_leaving_after_consent_does_not_rewrite_invitation_history(self):
        invitees = [
            Agent(f"Founder{index}", "Researcher", self.client)
            for index in range(3)
        ]
        for invitee in invitees:
            self.manager.register_agent(invitee)
        request = self.manager.create_agent_team(
            self.root,
            existing_members=invitees,
        )
        for invitee in invitees:
            await self.manager.respond_team_invitation(
                request.request_id,
                actor=invitee,
                attitude="accepted",
            )
        result = await self.manager.create_team_from_formation(
            request.request_id,
            actor=self.root,
        )
        team = self.manager.teams[result.team_id]
        team.members.remove(invitees[0])
        self.manager._auto_save(teams={team.team_id})
        await self.manager.save_state()
        joined_at = self.manager.team_formation_invitations[
            (request.request_id, invitees[0].agent_id)
        ].joined_at
        await self.manager.close()

        restored = ATTManager(
            Agent("Temporary", "Temporary", self.client),
            ATTConfig(workspace_root=self.tmpdir),
        )
        restored.register_llm_client("echo", self.client)
        try:
            await restored.load_state(self.db_path)
            restored_team = restored.teams[team.team_id]
            self.assertNotIn(invitees[0].agent_id, {agent.agent_id for agent in restored_team.members})
            self.assertEqual(
                restored.team_formation_invitations[
                    (request.request_id, invitees[0].agent_id)
                ].joined_at,
                joined_at,
            )
        finally:
            await restored.close()

    async def test_migration_after_formation_does_not_rewrite_formation_provenance(self):
        original_parent = self.manager.create_agent_team(self.root)
        target_parent = self.manager.create_agent_team(self.root)
        invitees = [
            Agent(f"Migrant{index}", "Researcher", self.client)
            for index in range(3)
        ]
        for invitee in invitees:
            self.manager.register_agent(invitee)
        request = self.manager.create_agent_team(
            original_parent,
            existing_members=invitees,
            initiating_agent=original_parent.members[0],
        )
        for invitee in invitees:
            await self.manager.respond_team_invitation(
                request.request_id,
                actor=invitee,
                attitude="accepted",
            )
        result = await self.manager.create_team_from_formation(
            request.request_id,
            actor=original_parent.members[0],
        )
        formed_team = self.manager.teams[result.team_id]
        self.manager.config.migration_policy = "permissive"
        migrated, reason = await self.manager.negotiate_and_execute_migration(
            formed_team,
            target_parent,
            "Move the established AgentTeam.",
        )
        self.assertTrue(migrated, reason)
        self.assertIs(formed_team.parent_team, target_parent)
        self.assertEqual(request.parent_team_id, original_parent.team_id)
        await self.manager.save_state()
        await self.manager.close()

        restored = ATTManager(
            Agent("Temporary", "Temporary", self.client),
            ATTConfig(workspace_root=self.tmpdir),
        )
        restored.register_llm_client("echo", self.client)
        try:
            await restored.load_state(self.db_path)
            restored_request = restored.get_team_formation(request.request_id)
            restored_team = restored.teams[formed_team.team_id]
            self.assertEqual(restored_request.parent_team_id, original_parent.team_id)
            self.assertEqual(restored_team.parent_team.team_id, target_parent.team_id)
        finally:
            await restored.close()

    async def test_self_membership_returns_before_deferred_discussion_needs_the_agent(self):
        parent = self.manager.create_agent_team(self.root)
        initiator = parent.members[0]
        request = self.manager.create_agent_team(
            parent,
            member_configs={"PeerOne": {}, "PeerTwo": {}},
            initiating_agent=initiator,
            initiator_joins=True,
            task="Complete deferred work.",
        )
        async with self.manager.agent_invocation(initiator):
            result = await asyncio.wait_for(
                self.manager.create_team_from_formation(
                    request.request_id,
                    actor=initiator,
                ),
                timeout=2,
            )
            self.assertEqual(result.status, "CREATED")
            self.assertIn(initiator, self.manager.teams[result.team_id].members)
        if self.manager._formations.tasks:
            await asyncio.wait_for(
                asyncio.gather(*tuple(self.manager._formations.tasks)),
                timeout=5,
            )

    async def test_failed_restore_rolls_back_the_original_agent_inbox(self):
        invitee = Agent("PersistedInvitee", "Researcher", self.client)
        self.manager.register_agent(invitee)
        self.manager.create_agent_team(
            self.root,
            member_configs={"PeerOne": {}, "PeerTwo": {}},
            existing_members=[invitee],
        )
        await self.manager.save_state()
        await self.manager.close()

        target_root = Agent("TargetRoot", "Architect", self.client)
        target = ATTManager(
            target_root,
            ATTConfig(workspace_root=self.tmpdir),
        )
        target.register_llm_client("echo", self.client)
        target._formations._notify_agent(
            target_root.agent_id,
            "preexisting_notification",
            {"stable": True},
        )
        original_inbox = [dict(message) for message in target_root.agent_inbox]
        original_restore = target._formations.restore
        failed_once = False

        def fail_after_inbox_switch(requests, invitations, agent_inboxes):
            nonlocal failed_once
            original_restore(requests, invitations, agent_inboxes)
            if not failed_once:
                failed_once = True
                raise RuntimeError("Injected post-inbox restore failure.")

        target._formations.restore = fail_after_inbox_switch
        try:
            with self.assertRaises(StateRestoreError):
                await target.load_state(self.db_path)
            self.assertIs(target.root_ai, target_root)
            self.assertEqual(target_root.agent_inbox, original_inbox)
        finally:
            target._formations.restore = original_restore
            await target.close()
