"""Finite sleep and provider recovery keep independent deadlines after restart."""

import asyncio
import sqlite3
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock, patch

from ai_team_team import Agent
from ai_team_team.core.manager.activity.values import ModelUnavailable, capture
from ai_team_team.core.manager.restore import preparation
from test.test_att.test_agent_activity._support import ActivityTestCase, call, idle
from test.test_att.test_autonomous_activity_phase0._fixtures import ModelStep, ScriptedModelClient
from test.test_att.test_background_tasks._support import contract


class RecoveryWakeTests(ActivityTestCase):
    async def interrupted_sleep(self, status):
        await self.manager.close()
        self.manager = self.make_manager(self.root, durable=True)
        self.manager.register_runtime_clock(self.clock)
        self.manager._activity.schedule_notice = Mock()
        self.steps(call("set_activity_intent", {"intent": {"kind": "sleep", "countdown": {"minutes": 5}}}))
        admitted = await self.manager.activate_agent(self.root.agent_id)
        await self.wait(admitted, "sleep")
        owner = self.root.agent_id
        started, release = asyncio.Event(), asyncio.Event()
        self.addCleanup(release.set)
        async def operation():
            started.set()
            await release.wait()
            return "external result"
        self.manager.register_tool("pending_owner_work", func=operation, execution_contract=contract())
        await self.manager.start_background_task("pending_owner_work", {}, actor=self.root)
        await asyncio.wait_for(started.wait(), 10)
        await self.manager._records.commit((capture(self.manager, "model_availability", agent_id=owner,
            model_alias="fixture", sequence_id="resource-recovery", status=status,
            reason="configuration" if status == "remediation_required" else "provider",
            request_budget=120, sequence_budget=600, last_confirmed={},
            earliest_admission_at=self.clock.wall_time() + 600 if status == "recoverable" else None),))
        await self.manager.save_state()
        path = str(Path(self.workspace.name) / "interrupted-sleeper.sqlite")
        with closing(sqlite3.connect(self.manager.db_path)) as source:
            with closing(sqlite3.connect(path)) as target:
                source.backup(target)
        await self.manager.close()
        release.set()
        self.restored_clock = self.clock.restarted(offline_seconds=0)
        self.addCleanup(self.restored_clock.close)
        self.restored_client = ScriptedModelClient(ModelStep(idle()))
        self.manager = self.make_manager(Agent("ReplacementHost", "Architect", self.restored_client))
        self.manager.register_runtime_clock(self.restored_clock)
        return path, owner

    async def expired_plan(self, owner):
        async with asyncio.timeout(10):
            while True:
                plan = next(row for row in self.records("sleep_plans") if row.values["agent_id"] == owner)
                if plan.values["status"] == "expired":
                    return plan
                await asyncio.sleep(0)

    async def await_model(self):
        async with asyncio.timeout(10):
            while not self.restored_client.requests:
                await asyncio.sleep(0)
        await self.settle()

    async def test_remediation_block_keeps_the_sleep_safeguard_until_its_original_deadline(self):
        path, owner = await self.interrupted_sleep("remediation_required")
        await self.manager.load_state(path)
        self.assertIn(owner, self.manager._activity.timers)
        self.assertFalse(self.restored_client.requests)
        self.restored_clock.advance(300)
        await self.expired_plan(owner)
        activity = self.manager.inspect_agent_activity(owner)
        self.assertEqual(activity.intent, "continuing")
        self.assertEqual(activity.availability, "unavailable")
        self.assertFalse(self.restored_client.requests)
        await self.manager.clear_agent_model_unavailability(owner)
        await self.await_model()
        self.assertEqual(len(self.restored_client.requests), 1)
        self.assertEqual(self.manager.inspect_agent_activity(owner).intent, "idle")

    async def test_later_provider_boundary_cannot_extend_the_sleep_countdown(self):
        path, owner = await self.interrupted_sleep("recoverable")
        await self.manager.load_state(path)
        self.assertFalse(self.restored_client.requests)
        self.restored_clock.advance(300)
        await self.expired_plan(owner)
        self.assertEqual(self.manager.inspect_agent_activity(owner).intent, "continuing")
        self.assertFalse(self.restored_client.requests)
        with self.assertRaises(ModelUnavailable):
            await self.manager.clear_agent_model_unavailability(owner)
        self.restored_clock.advance(300)
        await self.await_model()
        self.assertEqual(len(self.restored_client.requests), 1)
        self.assertEqual(self.manager.inspect_agent_activity(owner).intent, "idle")

    async def test_sleep_expired_during_slow_restore_settles_only_after_publication(self):
        path, owner = await self.interrupted_sleep("remediation_required")
        original = preparation.prepare_domain_recovery
        async def slow(*args, **kwargs):
            result = await original(*args, **kwargs)
            self.restored_clock.advance(360)
            self.assertFalse(self.restored_client.requests)
            self.assertNotIn(owner, self.manager._activity.sessions)
            self.assertFalse(self.manager._activity.timers)
            return result
        with patch.object(preparation, "prepare_domain_recovery", slow):
            await self.manager.load_state(path)
        await self.expired_plan(owner)
        self.assertEqual(self.manager.inspect_agent_activity(owner).intent, "continuing")
        self.assertEqual(self.manager.root_ai.agent_id, owner)
        self.assertFalse(self.restored_client.requests)
