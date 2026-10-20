"""An issued stop is not a terminal fact, and health requires supported evidence."""

import asyncio
import threading

from ai_team_team import ToolArgumentError

from ._support import BackgroundTestCase, contract


class CancellationTests(BackgroundTestCase):
    async def test_queued_cancel_prevents_dispatch(self):
        self.manager.config.executions.max_concurrent_executions = 1
        started, release = asyncio.Event(), asyncio.Event()
        calls = []

        async def operation(index: int) -> str:
            calls.append(index)
            started.set()
            await release.wait()
            return "done"

        self.manager.register_tool("operation", func=operation, execution_contract=contract())
        first = await self.start("operation", {"index": 1})
        await asyncio.wait_for(started.wait(), 5)
        second = await self.start("operation", {"index": 2})
        result = await self.manager.cancel_background_task(second.execution_id, actor=self.root)
        self.assertEqual(result.status, "CANCELLED")
        self.assertEqual(self.manager.inspect_background_task(second.execution_id, actor=self.root).execution_state, "cancelled")
        release.set()
        await self.finish(first)
        self.assertEqual(calls, [1])

    async def test_cooperative_running_cancel_has_an_acknowledgement(self):
        started = asyncio.Event()

        async def operation() -> str:
            started.set()
            await asyncio.Event().wait()
            return "never"

        self.manager.register_tool("operation", func=operation, execution_contract=contract(cancellation="cooperative"))
        handle = await self.start("operation")
        await asyncio.wait_for(started.wait(), 5)
        await self.manager.cancel_background_task(handle.execution_id, actor=self.root)
        await self.finish(handle)
        view = self.manager.inspect_background_task(handle.execution_id, actor=self.root)
        self.assertEqual(view.execution_state, "cancelled")
        controls = self.records("execution_controls")
        self.assertEqual(controls[0].values["acknowledgement"], "acknowledged")

    async def test_uncooperative_async_completion_remains_a_confirmed_completion(self):
        started, requested, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def operation() -> str:
            started.set()
            while not release.is_set():
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    requested.set()
            return "COMPLETED_AFTER_STOP_REQUEST"

        self.manager.register_tool("operation", func=operation, execution_contract=contract())
        handle = await self.start("operation")
        await asyncio.wait_for(started.wait(), 5)
        result = await self.manager.cancel_background_task(handle.execution_id, actor=self.root)
        self.assertEqual(result.status, "UNCONFIRMED")
        self.assertTrue(self.manager.inspect_background_task(handle.execution_id, actor=self.root).outcome_unconfirmed)
        await asyncio.wait_for(requested.wait(), 5)
        release.set()
        await self.finish(handle)
        view = self.manager.inspect_background_task(handle.execution_id, actor=self.root)
        self.assertEqual(view.execution_state, "completed")
        self.assertFalse(view.outcome_unconfirmed)

    async def test_cancelled_thread_keeps_its_resource_reservation_until_actual_return(self):
        started, release = threading.Event(), threading.Event()

        def operation() -> str:
            started.set()
            if not release.wait(10):
                raise TimeoutError("Thread was not released.")
            return "REAL_THREAD_RESULT"

        self.manager.register_tool("operation", func=operation, execution_contract=contract())
        handle = await self.start("operation")
        self.assertTrue(await asyncio.to_thread(started.wait, 5))
        try:
            result = await self.manager.cancel_background_task(handle.execution_id, actor=self.root)
            self.assertEqual(result.status, "UNCONFIRMED")
            job = self.manager._executions.jobs[handle.execution_id]
            await asyncio.wait_for(job.finished.wait(), 5)
            self.assertIn(handle.execution_id, self.manager._executions.resources.active)
        finally:
            release.set()
            for task in tuple(job.pending_threads):
                await asyncio.shield(task)
            await asyncio.sleep(0)
            if self.manager._executions.finalizers:
                await asyncio.gather(*tuple(self.manager._executions.finalizers))
        self.assertEqual(self.manager.inspect_background_task(handle.execution_id, actor=self.root).execution_state, "completed")

    async def test_hanging_executor_does_not_block_close_or_start_a_late_write(self):
        self.manager.config.executions.cancellation_grace_seconds = 0
        started, release, refused = asyncio.Event(), asyncio.Event(), []
        library = self.manager.libraries[self.root.private_doc_library_id]

        async def operation() -> str:
            started.set()
            while not release.is_set():
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    continue
            try:
                library.write_file("late.txt", "MUST_NOT_EXIST")
            except (PermissionError, RuntimeError):
                refused.append(True)
            return "stopped late"

        self.manager.register_tool("operation", func=operation, execution_contract=contract())
        handle = await self.start("operation")
        await asyncio.wait_for(started.wait(), 5)
        try:
            await asyncio.wait_for(self.manager.close(), 5)
        finally:
            release.set()
            await asyncio.wait_for(self.manager._executions.jobs[handle.execution_id].finished.wait(), 5)
        self.assertEqual(refused, [True])
        self.assertFalse(__import__("pathlib").Path(library.root_dir, "late.txt").exists())


class HealthTests(BackgroundTestCase):
    async def test_unsupported_heartbeat_is_not_an_inferred_stall(self):
        self.manager.register_runtime_clock(self.clock)
        started, release = asyncio.Event(), asyncio.Event()

        async def operation() -> str:
            started.set()
            await release.wait()
            return "done"

        self.manager.register_tool("operation", func=operation, execution_contract=contract())
        handle = await self.start("operation")
        await asyncio.wait_for(started.wait(), 5)
        self.clock.advance(100000)
        self.assertEqual(self.manager.inspect_background_task(handle.execution_id, actor=self.root).health_state, "unknown")
        with self.assertRaises(ToolArgumentError):
            await self.manager.report_execution_health(handle.execution_id, "stalled", "heartbeat")
        release.set()
        await self.finish(handle)

    async def test_declared_stall_is_deduplicated_and_attention_is_independent(self):
        self.manager.register_runtime_clock(self.clock)
        started, release = asyncio.Event(), asyncio.Event()

        async def operation() -> str:
            started.set()
            await release.wait()
            return "done"

        self.manager.register_tool("operation", func=operation, execution_contract=contract(
            health_signals=("heartbeat",), heartbeat_timeout_seconds=10.0))
        handle = await self.start("operation")
        await asyncio.wait_for(started.wait(), 5)
        self.clock.advance(10)
        await self.manager.report_execution_health(handle.execution_id, "stalled", "heartbeat")
        await self.manager.report_execution_health(handle.execution_id, "stalled", "heartbeat")
        notices = [row for row in self.records("agent_notifications") if row.values["execution_id"] == handle.execution_id]
        self.assertEqual(len(notices), 1)
        await self.manager.acknowledge_background_task(handle.execution_id, actor=self.root)
        view = self.manager.inspect_background_task(handle.execution_id, actor=self.root)
        self.assertEqual((view.execution_state, view.health_state, view.attention_state), ("running", "stalled", "acknowledged"))
        release.set()
        await self.finish(handle)
        self.assertEqual(self.manager.inspect_background_task(handle.execution_id, actor=self.root).attention_state, "required")
