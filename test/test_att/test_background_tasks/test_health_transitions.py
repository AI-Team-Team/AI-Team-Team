"""Observation ordering is independent of repeated-notification suppression."""

import asyncio
from pathlib import Path
from unittest.mock import patch

from ._support import BackgroundTestCase, contract


class HealthTransitionTests(BackgroundTestCase):
    async def operation(self, signals=("provider",)):
        self.manager.register_runtime_clock(self.clock)
        entered, release = asyncio.Event(), asyncio.Event()

        async def operation() -> str:
            entered.set()
            await release.wait()
            return "done"

        self.manager.register_tool("operation", func=operation, execution_contract=contract(health_signals=signals))
        handle = await self.start("operation")
        await asyncio.wait_for(entered.wait(), 5)
        self.addCleanup(release.set)
        return handle, release

    async def test_return_to_a_previous_health_state_is_a_new_observation(self):
        handle, release = await self.operation()
        evidence = {"provider_status": "running"}
        for health in ("degraded", "error", "degraded"):
            await self.manager.report_execution_health(handle.execution_id, health, "provider", evidence)
        observations = self.records("execution_observations")
        self.assertEqual([row.values["health"] for row in observations], ["degraded", "error", "degraded"])
        self.assertEqual([row.values["observation_index"] for row in observations], [1, 2, 3])
        self.assertEqual(self.manager.inspect_background_task(handle.execution_id, actor=self.root).health_state, "degraded")
        self.assertEqual(len(self.records("agent_notifications")), 3)
        path = str(Path(self.workspace.name) / "health.sqlite")
        await self.manager.save_state(path)
        state = await self.manager._persistence.read(path)
        persisted = [row for row in state["records"] if row.table_name == "execution_observations"]
        self.assertEqual({row.values["observation_index"] for row in persisted}, {1, 2, 3})
        release.set()
        await self.finish(handle)

    async def test_consecutive_identical_nonhealthy_reports_coalesce_only_until_a_transition(self):
        handle, release = await self.operation()
        for _index in range(4):
            await self.manager.report_execution_health(handle.execution_id, "stalled", "provider", {"provider_status": "stalled"})
        self.assertEqual(len(self.records("execution_observations")), 1)
        self.assertEqual(len(self.records("agent_notifications")), 1)
        await self.manager.report_execution_health(handle.execution_id, "healthy", "provider", {"provider_status": "running"})
        await self.manager.report_execution_health(handle.execution_id, "stalled", "provider", {"provider_status": "stalled"})
        self.assertEqual(len(self.records("execution_observations")), 3)
        self.assertEqual(len(self.records("agent_notifications")), 2)
        release.set()
        await self.finish(handle)

    async def test_healthy_counters_at_the_same_clock_sample_are_not_lost(self):
        handle, release = await self.operation(("progress",))
        for sequence in (1, 2):
            await self.manager.report_execution_health(handle.execution_id, "healthy", "progress", {"units_completed": sequence})
        self.assertEqual([row.values["evidence"]["units_completed"] for row in self.records("execution_observations")], [1, 2])
        release.set()
        await self.finish(handle)

    async def test_cancelled_health_receipt_observer_still_updates_the_accepted_live_sample(self):
        handle, release_operation = await self.operation(("heartbeat",))
        entered, release_receipt = asyncio.Event(), asyncio.Event()
        commit = self.manager._records.commit

        async def blocked(records, **kwargs):
            records = tuple(records)
            receipt = await commit(records, **kwargs)
            if any(row.table_name == "execution_observations" for row in records):
                entered.set()
                await release_receipt.wait()
            return receipt

        self.clock.advance(10)
        with patch.object(self.manager._records, "commit", blocked):
            report = asyncio.create_task(self.manager.report_execution_health(handle.execution_id, "healthy", "heartbeat", {"sequence": 1}))
            try:
                await asyncio.wait_for(entered.wait(), 5)
                report.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await report
            finally:
                release_receipt.set()
        job = self.manager._executions.jobs[handle.execution_id]
        self.assertEqual(job.health_samples["heartbeat"], 10)
        self.assertTrue(job.health_updated.is_set())
        self.assertEqual(len(self.records("execution_observations")), 1)
        release_operation.set()
        await self.finish(handle)
