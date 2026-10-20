"""Accepted controls and known outcomes survive observer cancellation."""

import asyncio
import threading
from unittest.mock import patch

from ai_team_team.database.persistence.coordinator import PersistenceCoordinator

from ._support import BackgroundTestCase, contract


class ControlSettlementTests(BackgroundTestCase):
    async def test_return_after_confirmed_stop_cannot_deliver_an_unaccepted_body(self):
        started, release = asyncio.Event(), asyncio.Event()

        class Provider:
            async def execute(self, call):
                started.set()
                while not release.is_set():
                    try:
                        await release.wait()
                    except asyncio.CancelledError:
                        continue
                return "UNACCEPTED_AFTER_CONFIRMED_STOP"

            async def cancel(self, execution_id):
                return True

        self.manager.register_executor("provider", Provider())
        self.manager.register_tool("operation", func=lambda: "unused", executor="provider",
            execution_contract=contract(cancellation="provider"))
        handle = await self.start("operation")
        try:
            await asyncio.wait_for(started.wait(), 5)
            self.assertEqual((await self.manager.cancel_background_task(handle.execution_id, actor=self.root)).status, "CANCELLED")
        finally:
            release.set()
        job = await self.finish(handle)
        self.assertEqual(job.result.error_kind, "execution_cancelled")
        self.assertNotIn("UNACCEPTED_AFTER_CONFIRMED_STOP", str(self.records("execution_payloads")))
        self.assertNotIn("UNACCEPTED_AFTER_CONFIRMED_STOP", job.result.content)

    async def durable(self):
        await self.manager.close()
        self.manager = self.make_manager(self.root, durable=True)
        self.manager._activity.schedule_notice = lambda _notice: None

    async def test_cancelled_stop_observer_cannot_dispatch_an_accepted_queued_stop(self):
        await self.durable()
        self.manager.config.executions.max_concurrent_executions = 1
        started, release_operation = asyncio.Event(), asyncio.Event()
        entered, release_writer = threading.Event(), threading.Event()
        calls = []

        async def operation(index: int) -> str:
            calls.append(index)
            started.set()
            await release_operation.wait()
            return "finished"

        self.manager.register_tool("operation", func=operation, execution_contract=contract())
        first = await self.start("operation", {"index": 1})
        await asyncio.wait_for(started.wait(), 5)
        second = await self.start("operation", {"index": 2})
        original = PersistenceCoordinator._write

        def blocked(coordinator, path, snapshot):
            if any(row.table_name == "execution_controls" and row.values["acknowledgement"] == "requested"
                   for row in snapshot.get("records", ())):
                entered.set()
                if not release_writer.wait(10):
                    raise TimeoutError("Stop receipt was not released.")
            return original(coordinator, path, snapshot)

        with patch.object(PersistenceCoordinator, "_write", blocked):
            observer = asyncio.create_task(self.manager.cancel_background_task(second.execution_id, actor=self.root))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 5))
                observer.cancel()
                await asyncio.sleep(0)
                observer.cancel()
            finally:
                release_writer.set()
            with self.assertRaises(asyncio.CancelledError):
                await observer
        release_operation.set()
        await self.finish(first)
        self.assertEqual(calls, [1])
        self.assertEqual(self.manager.inspect_background_task(second.execution_id, actor=self.root).execution_state, "cancelled")
        await self.manager.flush_state()
        state = await self.manager._persistence.read(self.manager.db_path)
        control = next(row for row in state["records"] if row.table_name == "execution_controls")
        self.assertEqual(control.values["acknowledgement"], "acknowledged")

    async def test_running_stop_hook_survives_a_cancelled_receipt_observer(self):
        started, entered, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        stopped = []

        class Provider:
            async def execute(self, call):
                started.set()
                await asyncio.Event().wait()

            async def cancel(self, execution_id):
                stopped.append(execution_id)
                return True

        self.manager.register_executor("provider", Provider())
        self.manager.register_tool("operation", func=lambda: "unused", executor="provider",
            execution_contract=contract(cancellation="provider"))
        handle = await self.start("operation")
        await asyncio.wait_for(started.wait(), 5)
        commit = self.manager._records.commit

        async def blocked(records, **kwargs):
            records = tuple(records)
            receipt = await commit(records, **kwargs)
            if any(row.table_name == "execution_controls" and row.values["acknowledgement"] == "requested" for row in records):
                entered.set()
                await release.wait()
            return receipt

        with patch.object(self.manager._records, "commit", blocked):
            observer = asyncio.create_task(self.manager.cancel_background_task(handle.execution_id, actor=self.root))
            try:
                await asyncio.wait_for(entered.wait(), 5)
                observer.cancel()
            finally:
                release.set()
            with self.assertRaises(asyncio.CancelledError):
                await observer
        self.assertEqual(stopped, [handle.execution_id])
        self.assertEqual(self.manager.inspect_background_task(handle.execution_id, actor=self.root).execution_state, "cancelled")

    async def outcome_boundary(self):
        entered, release = asyncio.Event(), asyncio.Event()
        prepare = self.manager._executions.prepare_result

        async def delayed(tool, result):
            if tool.name == "operation":
                entered.set()
                await release.wait()
            return await prepare(tool, result)

        async def operation() -> str:
            return "CONFIRMED_OPERATION_RESULT"

        self.manager.register_tool("operation", func=operation, execution_contract=contract(cancellation="cooperative"))
        return entered, release, delayed

    async def test_cancel_during_local_preparation_preserves_a_returned_success(self):
        entered, release, delayed = await self.outcome_boundary()
        with patch.object(self.manager._executions, "prepare_result", delayed):
            handle = await self.start("operation")
            await asyncio.wait_for(entered.wait(), 5)
            observer = asyncio.create_task(self.manager.cancel_background_task(handle.execution_id, actor=self.root))
            try:
                await asyncio.sleep(0)
                self.assertFalse(observer.done())
                self.assertFalse(self.manager._executions.jobs[handle.execution_id].cancellation_requested)
            finally:
                release.set()
            self.assertEqual((await observer).status, "ALREADY_TERMINAL")
            await self.finish(handle)
        view = self.manager.inspect_background_task(handle.execution_id, actor=self.root)
        self.assertEqual(view.execution_state, "completed")
        self.assertTrue(view.result_available)

    async def test_cancelled_worker_cannot_erase_a_known_result(self):
        entered, release, delayed = await self.outcome_boundary()
        with patch.object(self.manager._executions, "prepare_result", delayed):
            handle = await self.start("operation")
            await asyncio.wait_for(entered.wait(), 5)
            job = self.manager._executions.jobs[handle.execution_id]
            job.task.cancel()
            job.task.cancel()
            release.set()
            await self.finish(handle)
        self.assertEqual(self.manager.inspect_background_task(handle.execution_id, actor=self.root).execution_state, "completed")
        self.assertIn("CONFIRMED_OPERATION_RESULT", job.result.content)

    async def test_close_waits_for_local_outcomes_without_using_the_external_grace_limit(self):
        self.manager.config.executions.cancellation_grace_seconds = 0
        entered, release, delayed = await self.outcome_boundary()
        close_started = asyncio.Event()
        original = self.manager._executions.request_cancel

        async def observed(*args, **kwargs):
            close_started.set()
            return await original(*args, **kwargs)

        with patch.object(self.manager._executions, "prepare_result", delayed), patch.object(self.manager._executions, "request_cancel", observed):
            handle = await self.start("operation")
            await asyncio.wait_for(entered.wait(), 5)
            closing = asyncio.create_task(self.manager.close())
            try:
                await asyncio.wait_for(close_started.wait(), 5)
                self.assertFalse(closing.done())
            finally:
                release.set()
            await asyncio.wait_for(closing, 5)
        row = self.manager._records.index[("executions", (handle.execution_id,))]
        self.assertEqual(row.values["status"], "completed")
        self.assertFalse(self.manager._executions.finalizers)
