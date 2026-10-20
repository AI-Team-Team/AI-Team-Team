"""Undeclared foreground work shares reservations without losing its Session."""

import asyncio
import threading
from contextlib import asynccontextmanager
from unittest.mock import patch

from ai_team_team import Agent, StatePersistenceError, ResourceClaim
from ai_team_team.core.manager.executions.resources import ResourceCoordinator
from test.test_att.test_agent_activity._support import call, idle, personal_control_contract

from ._support import BackgroundTestCase, contract


class ForegroundCoordinationTests(BackgroundTestCase):
    async def test_personal_controls_share_known_outcome_settlement_without_losing_the_session(self):
        entered, release = asyncio.Event(), asyncio.Event()
        observer = None
        prepare = self.manager._executions.prepare_result

        async def personal_control() -> str:
            nonlocal observer
            observer = asyncio.current_task()
            self.assertIsNotNone(self.manager._activity.current.get())
            return "CONFIRMED_PERSONAL_CONTROL"

        async def delayed(tool, result):
            if tool.name == "personal_control":
                entered.set()
                await release.wait()
            return await prepare(tool, result)

        self.manager.register_tool("personal_control", func=personal_control,
            execution_contract=personal_control_contract())
        self.steps(call("personal_control"))
        with patch.object(self.manager._executions, "prepare_result", delayed):
            admitted = await self.manager.activate_agent(self.root.agent_id)
            try:
                await asyncio.wait_for(entered.wait(), 5)
                observer.cancel()
                await asyncio.sleep(0)
                self.assertFalse(observer.done())
            finally:
                release.set()
            with self.assertRaises(asyncio.CancelledError):
                await self.wait(admitted)
        row = next(row for row in self.records("executions") if row.values["tool_name"] == "personal_control")
        self.assertEqual(row.values["status"], "completed")
        self.assertFalse(row.values["outcome_unconfirmed"])
        result = await self.manager.read_background_task_result(row.values["execution_id"], actor=self.root)
        self.assertIn("CONFIRMED_PERSONAL_CONTROL", result.content)

    async def test_transient_result_cleanup_drops_the_completed_finalizer_reference(self):
        self.manager.libraries[self.root.private_doc_library_id].write_file("private.txt", "TRANSIENT_BODY_SENTINEL")
        handle = await self.start("read_private_file", {"path": "private.txt"})
        job = await self.finish(handle)
        self.assertIsNotNone(job.outcome_task)
        self.steps(call("read_background_task_result", {"execution_id": handle.execution_id}), idle())
        admitted = await self.manager.activate_agent(self.root.agent_id)
        await self.wait(admitted)
        self.assertIsNone(job.result)
        self.assertIsNone(job.thread_outcome)
        self.assertIsNone(job.outcome_task)
        self.assertNotIn("TRANSIENT_BODY_SENTINEL", str(self.root.message_history))

    async def test_waiter_cannot_preempt_a_scheduler_reservation_before_its_worker_enters(self):
        resources = ResourceCoordinator()
        claims = (ResourceClaim(namespace="global", resource_id="conservative", access="write"),)
        self.assertTrue(resources.try_claim("background", claims))
        waiting, entered = asyncio.Event(), asyncio.Event()

        async def foreground():
            waiting.set()
            async with resources.hold("foreground", claims):
                entered.set()
            resources.release("foreground")

        task = asyncio.create_task(foreground())
        try:
            await asyncio.wait_for(waiting.wait(), 5)
            async with asyncio.timeout(5):
                async with resources.hold("background", claims):
                    self.assertFalse(entered.is_set())
            resources.release("background")
            await asyncio.wait_for(task, 5)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_undeclared_foreground_waits_for_another_owners_global_writer(self):
        started, release, waited = asyncio.Event(), asyncio.Event(), asyncio.Event()
        invoked = []
        other = Agent("Other", "Researcher", self.client)
        self.manager.register_agent(other)

        async def background() -> str:
            started.set()
            await release.wait()
            return "background complete"

        async def foreground() -> str:
            session = self.manager._activity.current.get()
            invoked.append((session.agent_id, session.invocation_id))
            return "foreground complete"

        self.manager.register_tool("background", func=background,
            execution_contract=contract(effects=("artifact_write",), mutation_safety="managed_lease"))
        self.manager.register_tool("foreground", func=foreground)
        handle = await self.manager.start_background_task("background", {}, actor=other)
        await asyncio.wait_for(started.wait(), 5)
        hold = self.manager._executions.resources.hold

        @asynccontextmanager
        async def observed(execution_id, claims):
            waited.set()
            async with hold(execution_id, claims):
                yield

        self.steps(call("foreground"), idle())
        with patch.object(self.manager._executions.resources, "hold", observed):
            admitted = await self.manager.activate_agent(self.root.agent_id)
            try:
                await asyncio.wait_for(waited.wait(), 5)
                self.assertFalse(invoked)
            finally:
                release.set()
            await self.finish(handle)
            await self.wait(admitted)
        self.assertEqual(invoked[0][0], self.root.agent_id)
        self.assertIsNotNone(invoked[0][1])

    async def test_undeclared_foreground_reservation_also_blocks_new_background_work(self):
        started, release = asyncio.Event(), asyncio.Event()
        invoked = []

        async def foreground() -> str:
            started.set()
            await release.wait()
            return "done"

        async def background() -> str:
            invoked.append(True)
            return "done"

        self.manager.register_tool("foreground", func=foreground)
        self.manager.register_tool("background", func=background, execution_contract=contract())
        self.steps(call("foreground"), idle())
        admitted = await self.manager.activate_agent(self.root.agent_id)
        await asyncio.wait_for(started.wait(), 5)
        handle = await self.start("background")
        try:
            self.assertEqual(self.manager.inspect_background_task(handle.execution_id, actor=self.root).execution_state, "queued")
            self.assertFalse(invoked)
        finally:
            release.set()
        await self.wait(admitted)
        await self.finish(handle)
        self.assertEqual(invoked, [True])

    async def test_cancelled_foreground_thread_keeps_its_reservation_until_return(self):
        started, release = threading.Event(), threading.Event()
        invoked = []

        def foreground() -> str:
            started.set()
            if not release.wait(10):
                raise TimeoutError("Foreground thread was not released.")
            return "confirmed late foreground result"

        async def background() -> str:
            invoked.append(True)
            return "done"

        self.manager.register_tool("foreground", func=foreground)
        self.manager.register_tool("background", func=background, execution_contract=contract())
        self.steps(call("foreground"))
        admitted = await self.manager.activate_agent(self.root.agent_id)
        try:
            self.assertTrue(await asyncio.to_thread(started.wait, 5))
            job = next(job for job in self.manager._executions.jobs.values() if job.tool.name == "foreground")
            job.task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await self.wait(admitted)
            self.assertIn(job.execution_id, self.manager._executions.resources.active)
            handle = await self.start("background")
            self.assertFalse(invoked)
        finally:
            release.set()
            await asyncio.gather(*tuple(job.pending_threads))
            await asyncio.sleep(0)
            await asyncio.gather(*tuple(self.manager._executions.finalizers))
        await self.finish(handle)
        self.assertEqual(invoked, [True])
        self.assertEqual(self.manager._records.index[("executions", (job.execution_id,))].values["status"], "completed")

    async def test_builtin_stop_control_is_not_blocked_by_a_global_reservation(self):
        started = asyncio.Event()

        async def background() -> str:
            started.set()
            await asyncio.Event().wait()

        self.manager.register_tool("background", func=background, execution_contract=contract(
            effects=("artifact_write",), mutation_safety="managed_lease", cancellation="cooperative"))
        handle = await self.start("background")
        await asyncio.wait_for(started.wait(), 5)
        self.steps(call("cancel_background_task", {"execution_id": handle.execution_id}), idle())
        admitted = await self.manager.activate_agent(self.root.agent_id)
        await self.wait(admitted)
        self.assertEqual(self.manager.inspect_background_task(handle.execution_id, actor=self.root).execution_state, "cancelled")

    async def test_undeclared_nested_personal_wait_fails_before_accepting_a_dependency(self):
        other = Agent("Other", "Researcher", self.client)
        self.manager.register_agent(other)

        async def foreground() -> str:
            return str(await self.manager.execute_agent_interaction(other, "Do not accept this nested source"))

        self.manager.register_tool("foreground", func=foreground)
        self.steps(call("foreground"), idle())
        admitted = await self.manager.activate_agent(self.root.agent_id)
        await self.wait(admitted)
        self.assertFalse(other.agent_inbox)
        self.assertFalse(self.manager._agent_wait_edge_counts)
        job = next(job for job in self.manager._executions.jobs.values() if job.tool.name == "foreground")
        self.assertEqual(job.result.status.value, "denied")

    async def test_cancelled_coordinated_admission_records_a_stop_without_dispatch(self):
        entered, release = asyncio.Event(), asyncio.Event()
        invoked = []
        tool_task = None
        commit = self.manager._records.commit

        async def foreground() -> str:
            invoked.append(True)
            return "must not execute"

        async def blocked(records, **kwargs):
            nonlocal tool_task
            records = tuple(records)
            receipt = await commit(records, **kwargs)
            if any(row.table_name == "executions" and row.values["tool_name"] == "foreground"
                   and row.values["status"] == "queued" for row in records):
                tool_task = asyncio.current_task()
                entered.set()
                await release.wait()
            return receipt

        self.manager.register_tool("foreground", func=foreground)
        self.steps(call("foreground"))
        with patch.object(self.manager._records, "commit", blocked):
            admitted = await self.manager.activate_agent(self.root.agent_id)
            try:
                await asyncio.wait_for(entered.wait(), 5)
                tool_task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await self.wait(admitted)
            finally:
                release.set()
        row = next(row for row in self.records("executions") if row.values["tool_name"] == "foreground")
        self.assertEqual(row.values["status"], "cancelled")
        self.assertFalse(invoked)
        self.assertFalse(self.manager._executions.resources.active)

    async def test_ordinary_sync_fatal_is_not_reclassified_as_a_late_tool_failure(self):
        def operation() -> str:
            raise StatePersistenceError("Authoritative synchronous failure")

        self.manager.register_tool("operation", func=operation, execution_contract=contract())
        handle = await self.start("operation")
        with self.assertRaises(StatePersistenceError):
            await self.finish(handle)
        job = self.manager._executions.jobs[handle.execution_id]
        self.assertFalse(job.awaiting_thread_result)
        self.assertFalse(job.late_settlement_started)
        self.assertFalse(self.manager._executions.finalizers)
        self.assertIsNone(job.result)
        with self.assertRaises(StatePersistenceError):
            await self.manager.close()
