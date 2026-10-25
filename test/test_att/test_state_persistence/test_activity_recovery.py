"""Recovery preserves evidence and publishes once before scheduling a person."""

import asyncio
import sqlite3
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock, patch

from ai_team_team import Agent, StateRestoreError
from ai_team_team.core.activity.contracts import SuppressionPreference, WakeDuration
from ai_team_team.core.manager.restore import transaction
from test.test_att.test_agent_activity._support import ActivityTestCase, call, idle
from test.test_att.test_autonomous_activity_phase0._fixtures import AsyncBarrier, ModelStep, ScriptedModelClient
from test.test_att.test_background_tasks._support import contract


class RecoveryTests(ActivityTestCase):
    async def durable(self):
        await self.manager.close()
        self.manager = self.make_manager(self.root, durable=True)
        self.manager.register_runtime_clock(self.clock)

    def backup(self, destination):
        with closing(sqlite3.connect(self.manager.db_path)) as source:
            with closing(sqlite3.connect(destination)) as target:
                source.backup(target)

    def factual_rows(self, path):
        with closing(sqlite3.connect(path)) as source:
            return {table: source.execute(f'SELECT * FROM "{table}" ORDER BY 1').fetchall()
                for table in ("model_requests", "model_token_claims", "activity_admissions", "activity_invocations", "executions")}

    async def interrupted_model(self):
        await self.durable()
        barrier = AsyncBarrier()
        self.client.steps.append(ModelStep(idle(), barrier))
        await self.manager.activate_agent(self.root.agent_id)
        await barrier.wait_entered()
        await self.manager.save_state()
        path = str(Path(self.workspace.name) / "crash-model.sqlite")
        self.backup(path)
        owner = self.root.agent_id
        await self.manager.close()
        barrier.release()
        client = ScriptedModelClient(ModelStep(idle()))
        self.manager = self.make_manager(Agent("UnchangedHost", "Architect", client))
        return path, owner, client

    async def test_runtime_switch_failure_restores_existing_request_and_quota_rows_exactly(self):
        path, _owner, client = await self.interrupted_model()
        original_root = self.manager.root_ai
        before = self.factual_rows(path)
        resolve = transaction.resolve_manifest
        async def reject(manager, manifest, status):
            result = await resolve(manager, manifest, status)
            if status == "published":
                with closing(sqlite3.connect(path)) as database:
                    self.assertNotIn(("pending",), database.execute("SELECT outcome FROM model_requests").fetchall())
                raise RuntimeError("Injected failure after required recovery commit")
            return result
        with patch.object(transaction, "resolve_manifest", reject):
            with self.assertRaises(StateRestoreError):
                await self.manager.load_state(path)
        self.assertIs(self.manager.root_ai, original_root)
        self.assertEqual(self.factual_rows(path), before)
        self.assertFalse(client.requests)
        self.assertFalse(self.manager._activity.sessions)
        await self.manager.load_state(path)
        await self.settle()
        self.assertEqual(len(client.requests), 1)

    async def test_unfinished_host_execution_wakes_a_never_activated_owner_once_without_replay(self):
        await self.durable()
        self.manager._activity.schedule_notice = Mock()
        started, release = asyncio.Event(), asyncio.Event()
        async def operation():
            started.set()
            await release.wait()
            return "external operation"
        self.manager.register_tool("host_operation", func=operation, execution_contract=contract())
        handle = await self.manager.start_background_task("host_operation", {}, actor=self.root)
        await asyncio.wait_for(started.wait(), 10)
        await self.manager.save_state()
        self.assertFalse(self.records("model_requests"))
        path = str(Path(self.workspace.name) / "crash-execution.sqlite")
        self.backup(path)
        owner = self.root.agent_id
        await self.manager.close()
        release.set()
        client = ScriptedModelClient(ModelStep(idle()))
        self.manager = self.make_manager(Agent("Host", "Architect", client))
        replay = Mock(side_effect=AssertionError("An old execution must never be dispatched"))
        async def replay_operation():
            return replay()
        self.manager.register_tool("host_operation", func=replay_operation, execution_contract=contract())
        await self.manager.load_state(path)
        await self.settle()
        self.assertEqual(self.manager.root_ai.agent_id, owner)
        self.assertEqual(len(client.requests), 1)
        self.assertTrue(self.manager._records.index[("executions", (handle.execution_id,))].values["outcome_unconfirmed"])
        incidents = tuple(self.records("recovery_incidents"))
        await self.manager.load_state(path)
        await self.settle()
        self.assertEqual(tuple(self.records("recovery_incidents")), incidents)
        self.assertEqual(len(client.requests), 1)
        replay.assert_not_called()

    async def test_timed_suppression_and_sleep_exclude_offline_time_and_keep_source_unread(self):
        await self.durable()
        preference = await self.manager.set_notification_suppression(
            SuppressionPreference(scope="all", countdown=WakeDuration(minutes=5)), actor=self.root)
        self.steps(call("set_activity_intent", {"intent": {"kind": "sleep", "countdown": {"minutes": 10}}}))
        admission = await self.manager.activate_agent(self.root.agent_id)
        await self.wait(admission, "sleep")
        await self.manager.deliver_agent_mail(self.root.agent_id, message_type="ordinary", payload={"private": "NOT_IN_SUMMARY"})
        self.clock.advance(60)
        await self.manager.save_state()
        path, owner = self.manager.db_path, self.root.agent_id
        await self.manager.close()
        clock = self.clock.restarted(offline_seconds=3600)
        self.addCleanup(clock.close)
        client = ScriptedModelClient(ModelStep(idle()))
        self.manager = self.make_manager(Agent("NewHost", "Architect", client))
        self.manager.register_runtime_clock(clock)
        await self.manager.load_state(path)
        self.assertFalse(client.requests)
        self.assertEqual(self.manager.list_notification_suppressions(actor=self.manager.root_ai)[0]["remaining_seconds"], 240)
        timer = self.manager._activity.suppression_timers[preference["preference_id"]]
        clock.advance(240)
        await asyncio.wait_for(timer, 10)
        self.assertEqual(self.manager.inspect_agent_activity(owner).intent, "sleep")
        self.assertFalse(client.requests)
        clock.advance(300)
        async with asyncio.timeout(10):
            while not client.requests:
                await asyncio.sleep(0)
        await self.settle()
        self.assertEqual(len(client.requests), 1)
        self.assertNotIn("NOT_IN_SUMMARY", str(client.requests[-1].prompt))
        self.assertIsNone(self.manager.root_ai.agent_inbox[-1]["read_at"])

    async def test_interrupted_owned_execution_wakes_a_sleeping_owner_without_replay(self):
        await self.durable()
        self.manager.register_runtime_clock(self.clock)
        self.manager._activity.schedule_notice = Mock()
        self.steps(call("set_activity_intent", {"intent": {"kind": "sleep", "countdown": {"minutes": 10}}}))
        admission = await self.manager.activate_agent(self.root.agent_id)
        await self.wait(admission, "sleep")
        started, release = asyncio.Event(), asyncio.Event()
        async def operation():
            started.set()
            await release.wait()
            return "external result"
        self.manager.register_tool("sleeping_owner_work", func=operation, execution_contract=contract())
        handle = await self.manager.start_background_task("sleeping_owner_work", {}, actor=self.root)
        await asyncio.wait_for(started.wait(), 10)
        await self.manager.save_state()
        path = str(Path(self.workspace.name) / "sleeping-owner.sqlite")
        self.backup(path)
        owner = self.root.agent_id
        await self.manager.close()
        release.set()
        client = ScriptedModelClient(ModelStep(idle()))
        self.manager = self.make_manager(Agent("ReplacementHost", "Architect", client))
        replay = Mock(side_effect=AssertionError("Recovery cannot replay external work"))
        async def replay_operation():
            return replay()
        self.manager.register_tool("sleeping_owner_work", func=replay_operation, execution_contract=contract())
        await self.manager.load_state(path)
        await self.settle()
        self.assertEqual(self.manager.root_ai.agent_id, owner)
        self.assertEqual(len(client.requests), 1)
        self.assertEqual(self.manager.inspect_agent_activity(owner).intent, "idle")
        self.assertTrue(self.manager._records.index[("executions", (handle.execution_id,))].values["outcome_unconfirmed"])
        replay.assert_not_called()

    async def test_archived_sleep_does_not_activate_until_explicit_reactivation(self):
        await self.durable()
        self.manager.register_runtime_clock(self.clock)
        person = self.manager.register_agent(Agent("Sleeper", "Researcher", self.client))
        self.steps(call("set_activity_intent", {"intent": {"kind": "sleep", "countdown": {"minutes": 5}}}))
        admitted = await self.manager.activate_agent(person.agent_id)
        await self.wait(admitted, "sleep")
        await self.manager.retire_agent(person.agent_id, policy="archive")
        self.assertNotIn(person.agent_id, self.manager._activity.timers)
        await self.manager.save_state()
        path, owner, private_id = self.manager.db_path, person.agent_id, person.private_doc_library_id
        await self.manager.close()
        clock = self.clock.restarted(offline_seconds=3600)
        self.addCleanup(clock.close)
        client = ScriptedModelClient(ModelStep(idle()))
        self.manager = self.make_manager(Agent("NewHost", "Architect", client))
        self.manager.register_runtime_clock(clock)
        await self.manager.load_state(path)
        restored = self.manager._agents_by_id[owner]
        self.assertEqual(restored.lifecycle_state, "archived")
        self.assertIsNone(restored.llm_client)
        self.assertFalse(client.requests)
        self.assertNotIn(owner, self.manager._activity.timers)
        await self.manager.reactivate_agent(owner, "fixture")
        timer = self.manager._activity.timers[owner]
        clock.advance(300)
        await asyncio.wait_for(timer, 10)
        await self.settle()
        self.assertIs(self.manager._agents_by_id[owner], restored)
        self.assertEqual(restored.private_doc_library_id, private_id)
        self.assertEqual(self.manager.inspect_agent_activity(owner).intent, "idle")
        self.assertEqual(len(client.requests), 1)

    async def test_schema_fifteen_is_rejected_before_any_database_or_library_change(self):
        await self.durable()
        await self.manager.save_state()
        path = self.manager.db_path
        await self.manager.close()
        with closing(sqlite3.connect(path)) as database:
            database.execute("UPDATE manager_config SET config_value='15' WHERE config_key='schema_version'")
            database.commit()
        before = Path(path).read_bytes()
        original = self.make_manager(Agent("CurrentRoot", "Architect", self.client))
        root = original.root_ai
        with self.assertRaisesRegex(StateRestoreError, "Unsupported state schema"):
            await original.load_state(path)
        self.assertIs(original.root_ai, root)
        self.assertEqual(Path(path).read_bytes(), before)
