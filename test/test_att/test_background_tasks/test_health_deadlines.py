"""Timeout evidence uses the same ordering boundary as accepted live samples."""

import asyncio
from unittest.mock import patch

from ._support import BackgroundTestCase, contract


class HealthDeadlineTests(BackgroundTestCase):
    async def operation(self, **timeouts):
        self.manager.register_runtime_clock(self.clock)
        started, release = asyncio.Event(), asyncio.Event()

        async def operation() -> str:
            started.set()
            await release.wait()
            return "done"

        self.manager.register_tool("operation", func=operation, execution_contract=contract(
            health_signals=tuple(name.removesuffix("_timeout_seconds") for name in timeouts), **timeouts))
        handle = await self.start("operation")
        await asyncio.wait_for(started.wait(), 5)
        self.addCleanup(release.set)
        await self.wait_timer(min(timeouts.values()))
        return handle, release

    async def wait_timer(self, deadline):
        async with asyncio.timeout(5):
            while not any(when == deadline and not future.done() for when, _index, future in self.clock._waits):
                await asyncio.sleep(0)

    async def wait_stalls(self, count):
        async with asyncio.timeout(5):
            while len([row for row in self.records("execution_observations") if row.values["health"] == "stalled"]) < count:
                await asyncio.sleep(0)

    async def test_heartbeat_accepted_before_the_monitor_lock_prevents_a_stale_stall(self):
        handle, release = await self.operation(heartbeat_timeout_seconds=10.0)
        job = self.manager._executions.jobs[handle.execution_id]
        healthy_waiting, monitor_waiting = asyncio.Event(), asyncio.Event()
        lock = self.manager._activity.lock
        acquire = lock.acquire

        async def observed_acquire():
            task = asyncio.current_task()
            if task.get_name() == "healthy-report":
                healthy_waiting.set()
            if task is job.health_task:
                monitor_waiting.set()
            return await acquire()

        with patch.object(lock, "acquire", observed_acquire):
            await lock.acquire()
            try:
                report = asyncio.create_task(self.manager.report_execution_health(handle.execution_id,
                    "healthy", "heartbeat", {"sequence": 1}), name="healthy-report")
                await asyncio.wait_for(healthy_waiting.wait(), 5)
                self.clock.advance(10)
                await asyncio.wait_for(monitor_waiting.wait(), 5)
            finally:
                lock.release()
            await asyncio.wait_for(report, 5)
            await self.wait_timer(20)
        self.assertEqual(job.health_samples["heartbeat"], 10)
        self.assertEqual(self.manager.inspect_background_task(handle.execution_id, actor=self.root).health_state, "healthy")
        self.assertEqual([row.values["health"] for row in self.records("execution_observations")], ["healthy"])
        self.assertFalse(self.records("agent_notifications"))
        self.clock.advance(10)
        await self.wait_stalls(1)
        self.assertEqual(self.manager.inspect_background_task(handle.execution_id, actor=self.root).health_state, "stalled")
        release.set()
        await self.finish(handle)

    async def test_heartbeat_after_an_accepted_stall_rearms_the_next_deadline(self):
        handle, release = await self.operation(heartbeat_timeout_seconds=10.0)
        self.clock.advance(10)
        await self.wait_stalls(1)
        await self.manager.report_execution_health(handle.execution_id, "healthy", "heartbeat", {"sequence": 1})
        await self.wait_timer(20)
        self.clock.advance(9)
        self.assertEqual(self.manager.inspect_background_task(handle.execution_id, actor=self.root).health_state, "healthy")
        self.clock.advance(1)
        await self.wait_stalls(2)
        self.assertEqual([row.values["health"] for row in self.records("execution_observations")], ["stalled", "healthy", "stalled"])
        release.set()
        await self.finish(handle)

    async def test_refreshing_one_signal_does_not_extend_the_other_deadline(self):
        handle, release = await self.operation(heartbeat_timeout_seconds=10.0, progress_timeout_seconds=12.0)
        self.clock.advance(5)
        await self.manager.report_execution_health(handle.execution_id, "healthy", "heartbeat", {"sequence": 1})
        await self.wait_timer(12)
        self.clock.advance(7)
        await self.wait_stalls(1)
        stalled = [row for row in self.records("execution_observations") if row.values["health"] == "stalled"]
        self.assertEqual(stalled[0].values["evidence_kind"], "progress")
        await self.manager.report_execution_health(handle.execution_id, "healthy", "progress", {"units_completed": 1})
        await self.wait_timer(15)
        self.clock.advance(3)
        await self.wait_stalls(2)
        stalled = [row.values["evidence_kind"] for row in self.records("execution_observations") if row.values["health"] == "stalled"]
        self.assertEqual(stalled[-1], "heartbeat")
        release.set()
        await self.finish(handle)

    async def test_slow_stall_receipt_cannot_drop_another_signals_crossed_deadline(self):
        handle, release = await self.operation(heartbeat_timeout_seconds=10.0, progress_timeout_seconds=12.0)
        self.clock.advance(5)
        await self.manager.report_execution_health(handle.execution_id, "healthy", "heartbeat", {"sequence": 1})
        await self.wait_timer(12)
        entered, release_receipt = asyncio.Event(), asyncio.Event()
        commit = self.manager._records.commit
        monitor_idle = asyncio.Event()
        job = self.manager._executions.jobs[handle.execution_id]
        wait = asyncio.wait

        async def observed_wait(futures, **kwargs):
            if asyncio.current_task() is job.health_task and len(futures) == 1:
                monitor_idle.set()
            return await wait(futures, **kwargs)

        async def blocked(records, **kwargs):
            records = tuple(records)
            receipt = await commit(records, **kwargs)
            if any(row.table_name == "execution_observations" and row.values["health"] == "stalled"
                   and row.values["evidence_kind"] == "progress" for row in records):
                entered.set()
                await release_receipt.wait()
            return receipt

        with patch.object(self.manager._records, "commit", blocked), patch("asyncio.wait", observed_wait):
            self.clock.advance(7)
            try:
                await asyncio.wait_for(entered.wait(), 5)
                self.clock.advance(4)
            finally:
                release_receipt.set()
            await self.wait_stalls(2)
            await asyncio.wait_for(monitor_idle.wait(), 5)
        stalled = [row.values["evidence_kind"] for row in self.records("execution_observations") if row.values["health"] == "stalled"]
        self.assertEqual(stalled, ["progress", "heartbeat"])
        release.set()
        await self.finish(handle)
