"""Cancellation cannot lose accepted work or publish unaccepted protected content."""

import asyncio
import threading
from unittest.mock import patch

from ai_team_team import StatePersistenceError, ResourceClaim
from ai_team_team.core.activity.contracts import AgentTeamScope
from ai_team_team.database.persistence.coordinator import PersistenceCoordinator
from ai_team_team.database.persistence.records import thaw
from ai_team_team.core.manager.executions import evidence

from . import test_resources_and_privacy as resource_cases
from ._support import BackgroundTestCase, contract


class CommitBoundaryTests(BackgroundTestCase):
    async def test_late_thread_result_revalidates_sources_and_preserves_its_execution_reference(self):
        _source, team, library = resource_cases.RetainedResultTests.teams(self)
        owner = team.members[0]
        entered, release = threading.Event(), threading.Event()

        def operation() -> str:
            entered.set()
            if not release.wait(10):
                raise TimeoutError("The late thread was not released.")
            return "UNACCEPTED_LATE_SOURCE_CONTENT"

        self.manager.register_tool("operation", func=operation, execution_contract=contract(),
            resource_resolver=lambda scope, arguments: (ResourceClaim(namespace="library", resource_id=library.lib_id, path="source.txt", access="read"),))
        handle = await self.manager.start_background_task("operation", {}, actor=owner, scope=AgentTeamScope(team_id=team.team_id))
        try:
            self.assertTrue(await asyncio.to_thread(entered.wait, 5))
            await self.manager.cancel_background_task(handle.execution_id, actor=owner)
            await asyncio.wait_for(self.manager._executions.jobs[handle.execution_id].finished.wait(), 5)
            with self.manager._resources.mutation():
                self.manager.library_permissions[library.lib_id]["/"].pop(team.team_id)
        finally:
            release.set()
            job = self.manager._executions.jobs[handle.execution_id]
            await asyncio.gather(*(asyncio.shield(task) for task in tuple(job.pending_threads)))
            await asyncio.sleep(0)
            await asyncio.gather(*tuple(self.manager._executions.finalizers))
        self.assertEqual(job.result._execution_id, handle.execution_id)
        self.assertEqual(job.result.status.value, "denied")
        self.assertNotIn("UNACCEPTED_LATE_SOURCE_CONTENT", str([thaw(row.values) for row in self.records("execution_payloads")]))

    async def test_revocation_before_result_acceptance_does_not_create_a_retained_copy(self):
        _source, team, library = resource_cases.RetainedResultTests.teams(self)
        owner = team.members[0]
        entered, release = threading.Event(), threading.Event()
        original = evidence.digest

        def delayed(value):
            if "status" in value:
                entered.set()
                if not release.wait(10):
                    raise TimeoutError("The result preparation barrier was not released.")
            return original(value)

        with patch.object(evidence, "digest", delayed):
            handle = await self.manager.start_background_task("read_library_file",
                {"lib_id": library.lib_id, "path": "source.txt"}, actor=owner, scope=AgentTeamScope(team_id=team.team_id))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 5))
                with self.manager._resources.mutation():
                    self.manager.library_permissions[library.lib_id]["/"].pop(team.team_id)
            finally:
                release.set()
                await self.finish(handle)
        view = self.manager.inspect_background_task(handle.execution_id, actor=owner)
        self.assertEqual(view.execution_state, "failed")
        results = [thaw(row.values) for row in self.records("execution_payloads")]
        self.assertNotIn("AUTHORIZED_SOURCE_RESULT", str(results))

    async def test_cancelled_accepted_admission_dispatches_once_after_receipt(self):
        await self.manager.close()
        self.manager = self.make_manager(self.root, durable=True)
        self.manager._activity.schedule_notice = lambda _notice: None
        entered, release = threading.Event(), threading.Event()
        invoked = []

        async def operation() -> str:
            invoked.append(True)
            return "accepted execution"

        self.manager.register_tool("operation", func=operation, execution_contract=contract())
        original = PersistenceCoordinator._write

        def blocked(coordinator, path, snapshot):
            if any(row.table_name == "executions" and row.values["tool_name"] == "operation"
                   and row.values["status"] == "queued" for row in snapshot.get("records", ())):
                entered.set()
                if not release.wait(10):
                    raise TimeoutError("The admission writer was not released.")
            return original(coordinator, path, snapshot)

        with patch.object(PersistenceCoordinator, "_write", blocked):
            observer = asyncio.create_task(self.start("operation"))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 5))
                observer.cancel()
                await asyncio.sleep(0)
                observer.cancel()
                self.assertFalse(invoked)
            finally:
                release.set()
            with self.assertRaises(asyncio.CancelledError):
                await observer
            task = self.manager.list_background_tasks(actor=self.root).items[0]
            await self.finish(task)
        self.assertEqual(invoked, [True])

    async def test_worker_cannot_open_an_owner_model_invocation(self):
        async def operation() -> str:
            return str(await self.manager.execute_agent_interaction(self.root, "Do not impersonate the owner"))

        self.manager.register_tool("operation", func=operation, execution_contract=contract())
        handle = await self.start("operation")
        await self.finish(handle)
        self.assertEqual(self.manager.inspect_background_task(handle.execution_id, actor=self.root).execution_state, "failed")
        self.assertFalse(self.client.requests)
        self.assertFalse(self.root.agent_inbox)

    async def test_supported_stop_hook_is_called_on_close(self):
        started, stopped = asyncio.Event(), []

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
        await self.manager.close()
        self.assertEqual(stopped, [handle.execution_id])
        self.assertEqual(self.manager._records.index[("executions", (handle.execution_id,))].values["status"], "cancelled")
