import asyncio
from contextlib import closing
import os
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from ai_team_team import (
    ATTConfig,
    ATTManager,
    Agent,
    AuditResult,
    AuditStatus,
    StateRestoreError,
)
from ai_team_team.database.persistence import DatabaseStore
from ai_team_team.tool import get_default_tools


class TestATTHardening(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="att_hardening_")
        self.client = MagicMock()
        self.client.generate = AsyncMock(return_value="Final Answer: Done")
        self.root = Agent("Root", "Architect", llm_client=self.client)
        self.manager = ATTManager(
            self.root,
            ATTConfig(
                max_delegation_depth=6,
                migration_policy="permissive",
                enable_membership_voting=True,
                workspace_root=self.tmpdir,
            ),
        )

    async def asyncTearDown(self):
        await self.manager.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_config_rejects_unknown_policies(self):
        cases = {
            "communication_policy": "open",
            "migration_policy": "silent",
            "failover_policy": "random",
            "tool_calling_mode": "maybe",
            "audit_unknown_escalation_mode": "ignore",
            "agent_private_data_policy": "expose",
        }
        for name, value in cases.items():
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    ATTConfig(**{name: value})

    def test_builtin_tools_have_manager_context_immediately(self):
        team = self.manager.create_agent_team(self.root)
        self.assertIs(
            self.manager.tools_context["att_manager"], self.manager
        )
        self.assertIn("dispatch_subagent", team.tools)
        self.manager.register_tools_context(
            {"att_manager": object(), "service": "value"}
        )
        self.assertIs(
            self.manager.tools_context["att_manager"], self.manager
        )

    async def test_migration_invalidates_all_descendant_depths(self):
        left = self.manager.create_agent_team(self.root)
        moving = self.manager.create_agent_team(left)
        descendant = self.manager.create_agent_team(moving)
        right = self.manager.create_agent_team(self.root)
        right_child = self.manager.create_agent_team(right)

        self.assertEqual(moving.depth, 2)
        self.assertEqual(descendant.depth, 3)
        self.assertEqual(right_child.depth, 2)

        success, _ = await self.manager.negotiate_and_execute_migration(
            moving, right_child, "Move the complete branch."
        )

        self.assertTrue(success)
        self.assertEqual(moving.depth, 3)
        self.assertEqual(descendant.depth, 4)

    async def test_parallel_votes_are_atomic_and_execute_once(self):
        team = self.manager.create_agent_team(self.root)
        first, second, third = team.members
        first_tools = get_default_tools(
            {"att_manager": self.manager}, first
        )
        response = await first_tools["initiate_membership_vote"](
            action="add",
            target="Verifier",
            rationale="Need independent verification.",
            proposed_details={"model": "default"},
        )
        proposal_id = response.split("'")[1]
        second_vote = get_default_tools(
            {"att_manager": self.manager}, second
        )["cast_vote"]
        third_vote = get_default_tools(
            {"att_manager": self.manager}, third
        )["cast_vote"]

        await asyncio.gather(
            second_vote(proposal_id, "Agree"),
            third_vote(proposal_id, "Agree"),
        )

        self.assertEqual(
            sum(
                member.name == "Dynamic_Verifier"
                for member in team.members
            ),
            1,
        )
        self.assertTrue(
            team.proposals[proposal_id]["proposed_details"]["executed"]
        )
        duplicate = await second_vote(proposal_id, "Agree")
        self.assertIn("already closed", duplicate)

        outsider = Agent("Outsider", "Observer", llm_client=self.client)
        outsider_vote = get_default_tools(
            {"att_manager": self.manager}, team
        )["cast_vote"]
        token = self.manager._active_tool_agent.set(outsider)
        try:
            rejected = await outsider_vote(proposal_id, "Agree")
        finally:
            self.manager._active_tool_agent.reset(token)
        self.assertIn("Only an active team member", rejected)

    async def test_concurrent_nested_suppression_keeps_batches_separate(self):
        first = self.manager.create_agent_team(self.root)
        second = self.manager.create_agent_team(self.root)
        submitted = []
        self.manager.db_path = os.path.join(self.tmpdir, "unused.db")
        self.manager._submit_dirty_state = submitted.append
        rendezvous = asyncio.Event()

        async def mutate(team, wait):
            async with self.manager.suppress_auto_save():
                self.manager._auto_save(teams={team.team_id})
                async with self.manager.suppress_auto_save():
                    self.manager._auto_save(teams={team.team_id})
                if wait:
                    rendezvous.set()
                else:
                    await rendezvous.wait()

        await asyncio.gather(
            mutate(first, True),
            mutate(second, False),
        )

        self.assertEqual(len(submitted), 2)
        self.assertEqual(
            {frozenset(batch["teams"]) for batch in submitted},
            {
                frozenset({first.team_id}),
                frozenset({second.team_id}),
            },
        )

    async def test_incremental_agent_write_preserves_other_messages(self):
        db_path = os.path.join(self.tmpdir, "state.db")
        manager = ATTManager(
            self.root,
            ATTConfig(workspace_root=self.tmpdir),
            db_path=db_path,
        )
        manager.register_llm_client("test", self.client)
        team = manager.create_agent_team(self.root)
        await manager.save_state()
        untouched = team.members[1]
        changed = team.members[0]

        with closing(sqlite3.connect(db_path)) as connection:
            before = connection.execute(
                "SELECT id FROM agent_messages WHERE agent_id = ?",
                (untouched.agent_id,),
            ).fetchall()

        changed.messages.append({"role": "user", "content": "delta"})
        manager._auto_save(agents={changed.name})
        await manager.flush_state()

        with closing(sqlite3.connect(db_path)) as connection:
            after = connection.execute(
                "SELECT id FROM agent_messages WHERE agent_id = ?",
                (untouched.agent_id,),
            ).fetchall()
        self.assertEqual(before, after)
        await manager.close()

    async def test_slow_database_write_does_not_block_heartbeat(self):
        db_path = os.path.join(self.tmpdir, "slow.db")
        manager = ATTManager(
            self.root,
            ATTConfig(workspace_root=self.tmpdir),
            db_path=db_path,
        )
        manager.register_llm_client("test", self.client)
        original_write = DatabaseStore.write

        def slow_write(store, snapshot):
            import time

            time.sleep(0.15)
            return original_write(store, snapshot)

        heartbeats = 0

        async def heartbeat():
            nonlocal heartbeats
            for _ in range(5):
                await asyncio.sleep(0.02)
                heartbeats += 1

        with patch.object(DatabaseStore, "write", slow_write):
            manager._auto_save(configs=True)
            await heartbeat()
            self.assertEqual(heartbeats, 5)
            await manager.flush_state()
        await manager.close()

    async def test_incremental_doc_file_restore_and_missing_binding(self):
        db_path = os.path.join(self.tmpdir, "files.db")
        manager = ATTManager(
            self.root,
            ATTConfig(workspace_root=self.tmpdir),
            db_path=db_path,
        )
        manager.register_llm_client("test", self.client)
        team = manager.create_agent_team(self.root)
        await manager.save_state()
        team.doc_library.write_file("delta/note.txt", "persisted delta")
        await manager.flush_state()
        shutil.rmtree(team.doc_library.root_dir)
        await manager.close()

        restored = ATTManager(
            Agent("Root", "Architect", llm_client=self.client),
            ATTConfig(workspace_root=self.tmpdir),
        )
        restored.register_llm_client("test", self.client)
        await restored.load_state(db_path)
        restored_team = restored.teams[team.team_id]
        self.assertIn(
            "persisted delta",
            restored_team.doc_library.read_file("delta/note.txt"),
        )
        await restored.close()

        rebinder = ATTManager(
            Agent("Root", "Architect", llm_client=self.client),
            ATTConfig(workspace_root=self.tmpdir),
            db_path=db_path,
        )
        rebinder.register_llm_client("test", self.client)
        await rebinder.load_state(db_path)
        rebinder.llm_clients.pop("test")
        rebinder.register_llm_client("named", self.client)
        await rebinder.save_state()
        await rebinder.close()
        missing = ATTManager(
            Agent("Root", "Architect", llm_client=self.client),
            ATTConfig(workspace_root=self.tmpdir),
        )
        with self.assertRaisesRegex(StateRestoreError, "named"):
            await missing.load_state(db_path)
        await missing.close()

    async def test_incremental_inbox_and_proposal_restore(self):
        db_path = os.path.join(self.tmpdir, "governance.db")
        manager = ATTManager(
            self.root,
            ATTConfig(
                enable_membership_voting=True,
                workspace_root=self.tmpdir,
            ),
            db_path=db_path,
        )
        manager.register_llm_client("test", self.client)
        team = manager.create_agent_team(self.root)
        await manager.flush_state()
        tools = get_default_tools(
            {"att_manager": manager}, team.members[0]
        )
        response = await tools["initiate_membership_vote"](
            "add", "Reviewer", "Need review."
        )
        proposal_id = response.split("'")[1]
        team.receive_message(
            {
                "type": "peer_message",
                "from": "peer",
                "objective": "incremental inbox",
            }
        )
        await manager.flush_state()
        await manager.close()

        restored = ATTManager(
            Agent("Root", "Architect", llm_client=self.client),
            ATTConfig(workspace_root=self.tmpdir),
        )
        restored.register_llm_client("test", self.client)
        await restored.load_state(db_path)
        restored_team = restored.teams[team.team_id]
        self.assertIn(proposal_id, restored_team.proposals)
        self.assertEqual(
            restored_team.message_inbox[0]["objective"],
            "incremental inbox",
        )
        await restored.close()

    async def test_unknown_wake_queue_and_deduplication(self):
        parent = self.manager.create_agent_team(self.root)
        child = self.manager.create_agent_team(parent)
        self.manager.execute_emergency_discussion = AsyncMock(
            return_value="handled"
        )
        result = AuditResult(
            AuditStatus.UNKNOWN,
            "Audit unavailable.",
            "TimeoutError: timeout",
        )

        await asyncio.gather(
            self.manager.supervisor.report_unknown(
                child, result, self.manager
            ),
            self.manager.supervisor.report_unknown(
                child, result, self.manager
            ),
        )
        await asyncio.sleep(0)
        self.manager.execute_emergency_discussion.assert_awaited_once()
        self.assertTrue(
            self.manager.execute_emergency_discussion.await_args.kwargs[
                "skip_audit"
            ]
        )

        self.manager.execute_emergency_discussion.reset_mock()
        self.manager.config.audit_unknown_escalation_mode = "queue"
        await self.manager.supervisor.report_unknown(
            child, result, self.manager
        )
        await asyncio.sleep(0)
        self.manager.execute_emergency_discussion.assert_not_awaited()
        self.assertTrue(
            any(
                message.get("type") == "audit_unknown_escalation"
                for message in parent.message_inbox
            )
        )

    async def test_unhealthy_keeps_emergency_escalation(self):
        parent = self.manager.create_agent_team(self.root)
        child = self.manager.create_agent_team(parent)
        self.manager.execute_emergency_discussion = AsyncMock(
            return_value="handled"
        )

        await self.manager.supervisor.report_anomaly(
            child, "Confirmed deadlock.", self.manager
        )
        await asyncio.sleep(0)

        self.manager.execute_emergency_discussion.assert_awaited_once()
        alert = (
            self.manager.execute_emergency_discussion
            .await_args.args[1]
        )
        self.assertEqual(alert["type"], "child_failure_escalation")
        self.assertFalse(
            self.manager.execute_emergency_discussion.await_args.kwargs[
                "skip_audit"
            ]
        )

    async def test_async_context_flushes_and_closes(self):
        db_path = os.path.join(self.tmpdir, "context.db")
        scoped = ATTManager(
            Agent("ScopedRoot", "Architect", llm_client=self.client),
            ATTConfig(workspace_root=self.tmpdir),
            db_path=db_path,
        )
        scoped.register_llm_client("test", self.client)
        async with scoped:
            scoped.create_agent_team(scoped.root_ai)
        self.assertTrue(scoped._persistence._closed)
        self.assertTrue(os.path.exists(db_path))
