"""Late synchronous results use the same classification, never implicit replay."""

import asyncio
import threading

from ai_team_team import RetryableToolError, StatePersistenceError, ToolArgumentError, ToolBusinessError, ToolPermissionError

from ._support import BackgroundTestCase, contract


class LateFailureTests(BackgroundTestCase):
    async def late_failure(self, error, *, attempts=1):
        started, release = threading.Event(), threading.Event()
        calls = []

        def operation() -> str:
            calls.append(True)
            if len(calls) < attempts:
                raise RetryableToolError("Retry before the physical wait")
            started.set()
            if not release.wait(10):
                raise TimeoutError("Late outcome was not released.")
            raise error

        self.manager.config.tool_execution_retry_policy = "typed_transient"
        self.manager.config.tool_execution_retry_backoff_factor = 0
        self.manager.register_tool("operation", func=operation, execution_contract=contract())
        handle = await self.start("operation")
        try:
            self.assertTrue(await asyncio.to_thread(started.wait, 5))
            await self.manager.cancel_background_task(handle.execution_id, actor=self.root)
            job = self.manager._executions.jobs[handle.execution_id]
            await asyncio.wait_for(job.finished.wait(), 5)
        finally:
            release.set()
            await asyncio.gather(*tuple(job.pending_threads), return_exceptions=True)
            await asyncio.sleep(0)
        finalizers = tuple(self.manager._executions.finalizers)
        await asyncio.gather(*finalizers, return_exceptions=True)
        await asyncio.sleep(0)
        self.assertEqual(len(calls), attempts, "A cancelled attempt must never be automatically replayed.")
        return job

    async def test_late_fatal_is_preserved_and_propagated_from_close(self):
        error = StatePersistenceError("Late authoritative failure")
        job = await self.late_failure(error)
        self.assertIs(job.error, error)
        self.assertIn(error, self.manager._executions.errors)
        self.assertIsNone(job.result)
        with self.assertRaises(StatePersistenceError) as raised:
            await self.manager.close()
        self.assertIs(raised.exception, error)

    async def test_late_permission_failure_remains_denied(self):
        job = await self.late_failure(ToolPermissionError("Permission changed"))
        self.assertEqual((job.result.status.value, job.result.error_kind), ("denied", "permission_denied"))
        self.assertIsNone(job.error)

    async def test_late_business_failure_remains_a_business_failure(self):
        job = await self.late_failure(ToolBusinessError("Rejected by the domain", error_kind="domain_conflict"))
        self.assertEqual((job.result.status.value, job.result.error_kind), ("business_error", "domain_conflict"))

    async def test_late_argument_failure_remains_invalid_arguments(self):
        job = await self.late_failure(ToolArgumentError("Invalid external argument"))
        self.assertEqual(job.result.status.value, "invalid_arguments")

    async def test_late_transient_failure_keeps_the_actual_attempt_count_without_replay(self):
        job = await self.late_failure(RetryableToolError("Late transient failure"), attempts=2)
        self.assertEqual((job.result.status.value, job.result.attempts), ("transient_error", 2))

    async def test_late_internal_failure_uses_the_shared_internal_category(self):
        job = await self.late_failure(RuntimeError("Late implementation failure"))
        self.assertEqual((job.result.status.value, job.result.error_kind), ("internal_error", "tool_internal_error"))
