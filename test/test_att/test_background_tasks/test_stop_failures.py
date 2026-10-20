"""Provider uncertainty cannot swallow authoritative framework failures."""

import asyncio
import threading

from ai_team_team import DatabaseOwnershipError, StatePersistenceError, StateRestoreError

from ._support import BackgroundTestCase, contract


class StopFailureTests(BackgroundTestCase):
    async def provider(self, stop):
        started = asyncio.Event()

        class Provider:
            cancel = staticmethod(stop)

            async def execute(self, call):
                started.set()
                await asyncio.Event().wait()

        self.manager.register_executor("provider", Provider())
        self.manager.register_tool("operation", func=lambda: "unused", executor="provider",
            execution_contract=contract(cancellation="provider"))
        handle = await self.start("operation")
        await asyncio.wait_for(started.wait(), 5)
        return handle

    async def assert_fatal_stop(self, error, *, synchronous=False):
        def sync_stop(execution_id):
            raise error

        async def async_stop(execution_id):
            raise error

        handle = await self.provider(sync_stop if synchronous else async_stop)
        with self.assertRaises(type(error)) as caught:
            await self.manager.cancel_background_task(handle.execution_id, actor=self.root)
        self.assertIs(caught.exception, error)
        job = self.manager._executions.jobs[handle.execution_id]
        await asyncio.wait_for(job.finished.wait(), 5)
        row = self.manager._records.index[("executions", (handle.execution_id,))]
        self.assertEqual(row.values["status"], "running")
        self.assertTrue(row.values["outcome_unconfirmed"])
        self.assertEqual(self.records("execution_controls")[0].values["acknowledgement"], "uncertain")
        self.assertEqual(self.manager._executions.errors, [error])
        with self.assertRaises(type(error)) as closing:
            await self.manager.close()
        self.assertIs(closing.exception, error)
        self.assertTrue(self.manager._closed)

    async def test_persistence_failure_from_an_async_stop_hook_propagates(self):
        await self.assert_fatal_stop(StatePersistenceError("The authoritative stop write failed."))

    async def test_restore_failure_from_a_sync_stop_hook_propagates(self):
        await self.assert_fatal_stop(StateRestoreError("The stop hook detected invalid state."), synchronous=True)

    async def test_writer_ownership_failure_from_a_stop_hook_propagates(self):
        await self.assert_fatal_stop(DatabaseOwnershipError("The stop hook lost database ownership."))

    async def test_ordinary_provider_failure_preserves_uncertainty_without_fatal_close(self):
        async def stop(execution_id):
            raise ConnectionError("The external provider is unavailable.")

        handle = await self.provider(stop)
        result = await self.manager.cancel_background_task(handle.execution_id, actor=self.root)
        self.assertEqual(result.status, "UNCONFIRMED")
        self.assertTrue(self.manager.inspect_background_task(handle.execution_id, actor=self.root).outcome_unconfirmed)
        self.assertFalse(self.manager._executions.errors)
        await self.manager.close()

    async def test_stop_failure_is_preserved_when_its_observer_is_cancelled(self):
        entered, release = asyncio.Event(), asyncio.Event()
        failure = StatePersistenceError("An accepted stop failed during observer cancellation.")

        async def stop(execution_id):
            entered.set()
            await release.wait()
            raise failure

        handle = await self.provider(stop)
        observer = asyncio.create_task(self.manager.cancel_background_task(handle.execution_id, actor=self.root))
        try:
            await asyncio.wait_for(entered.wait(), 5)
            observer.cancel()
            observer.cancel()
        finally:
            release.set()
        with self.assertRaises(StatePersistenceError) as caught:
            await observer
        self.assertIs(caught.exception, failure)
        with self.assertRaises(StatePersistenceError):
            await self.manager.close()

    async def test_fatal_stop_after_the_external_grace_period_is_retained(self):
        self.manager.config.executions.cancellation_grace_seconds = 0
        entered, release, cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()
        failure = StatePersistenceError("The late stop acknowledgement failed authoritatively.")
        task = None

        async def stop(execution_id):
            nonlocal task
            task = asyncio.current_task()
            entered.set()
            while not release.is_set():
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    cancelled.set()
            raise failure

        handle = await self.provider(stop)
        try:
            result = await self.manager.cancel_background_task(handle.execution_id, actor=self.root)
            self.assertEqual(result.status, "UNCONFIRMED")
            await asyncio.wait_for(entered.wait(), 5)
            await asyncio.wait_for(cancelled.wait(), 5)
        finally:
            release.set()
        with self.assertRaises(StatePersistenceError):
            await task
        await asyncio.sleep(0)
        self.assertIn(failure, self.manager._executions.errors)
        with self.assertRaises(StatePersistenceError):
            await self.manager.close()

    async def test_synchronous_stop_thread_keeps_its_late_fatal_after_grace_expires(self):
        self.manager.config.executions.cancellation_grace_seconds = 0
        entered, release = threading.Event(), threading.Event()
        failure = StatePersistenceError("The real stop thread failed after its observer expired.")

        def stop(execution_id):
            entered.set()
            if not release.wait(10):
                raise TimeoutError("The stop thread was not released.")
            raise failure

        handle = await self.provider(stop)
        try:
            result = await self.manager.cancel_background_task(handle.execution_id, actor=self.root)
            self.assertEqual(result.status, "UNCONFIRMED")
            self.assertTrue(await asyncio.to_thread(entered.wait, 5))
            pending = [task for task in self.manager._executions.tasks if task.get_name() == "att-executor-stop-thread"]
            self.assertEqual(len(pending), 1)
        finally:
            release.set()
        with self.assertRaises(StatePersistenceError):
            await pending[0]
        await asyncio.sleep(0)
        self.assertIn(failure, self.manager._executions.errors)
        with self.assertRaises(StatePersistenceError):
            await self.manager.close()

    async def test_stop_failure_is_not_erased_by_a_concurrent_factual_completion(self):
        entered, release = asyncio.Event(), asyncio.Event()
        started, completed = asyncio.Event(), asyncio.Event()
        failure = StatePersistenceError("Stop failed even though the operation completed.")

        class Provider:
            async def execute(self, call):
                started.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    return "FACTUAL_COMPLETION"

            async def cancel(self, execution_id):
                entered.set()
                await release.wait()
                raise failure

        self.manager.register_executor("provider", Provider())
        self.manager.register_tool("operation", func=lambda: "unused", executor="provider",
            execution_contract=contract(cancellation="provider"))
        handle = await self.start("operation")
        await asyncio.wait_for(started.wait(), 5)
        observer = asyncio.create_task(self.manager.cancel_background_task(handle.execution_id, actor=self.root))
        try:
            await asyncio.wait_for(entered.wait(), 5)
            await self.finish(handle)
            completed.set()
        finally:
            release.set()
        with self.assertRaises(StatePersistenceError):
            await observer
        self.assertTrue(completed.is_set())
        self.assertEqual(self.manager.inspect_background_task(handle.execution_id, actor=self.root).execution_state, "completed")
        with self.assertRaises(StatePersistenceError):
            await self.manager.close()
