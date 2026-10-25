"""Lifecycle controls preserve external acknowledgements and isolate other owners."""

import asyncio
from unittest.mock import Mock

from ai_team_team import Agent
from test.test_att.test_agent_activity._support import ActivityTestCase
from test.test_att.test_background_tasks._support import contract


class PausableExecutor:
    def __init__(self, acknowledge=True):
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.acknowledge = acknowledge
        self.pauses = []
        self.stops = []

    async def execute(self, call):
        self.started.set()
        await self.release.wait()
        return "external result"

    async def suspend(self, execution_id):
        self.pauses.append(execution_id)
        return self.acknowledge

    async def cancel(self, execution_id):
        self.stops.append(execution_id)
        return True


class ExecutionLifecycleTests(ActivityTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.manager.config.executions.cancellation_grace_seconds = 0.01
        self.manager._activity.schedule_notice = Mock()
        self.person = self.manager.register_agent(Agent("Owner", "Researcher", self.client))

    async def start_external(self, binding):
        self.manager.register_executor("pausable", binding)
        async def declaration():
            return "The executor supplies this operation."
        self.manager.register_tool("external", func=declaration, executor="pausable",
            execution_contract=contract(cancellation="provider", suspension="provider"))
        handle = await self.manager.start_background_task("external", {}, actor=self.person)
        await asyncio.wait_for(binding.started.wait(), 10)
        return handle

    async def test_supported_suspension_is_acknowledged_without_a_fabricated_terminal_state(self):
        binding = PausableExecutor()
        handle = await self.start_external(binding)
        result = await self.manager.mark_agent_dead(self.person.agent_id, confirm=True)
        self.assertEqual(result["tasks"][0]["status"], "SUSPENDED")
        self.assertEqual(binding.pauses, [handle.execution_id])
        self.assertFalse(binding.stops)
        row = self.manager._records.index[("executions", (handle.execution_id,))]
        self.assertEqual(row.values["status"], "running")
        self.assertIsNone(row.values["finished_at"])
        controls = self.records("execution_controls")
        self.assertEqual([(row.values["operation"], row.values["acknowledgement"]) for row in controls], [("suspend", "acknowledged")])

    async def test_unacknowledged_suspension_falls_back_to_supported_termination(self):
        binding = PausableExecutor(acknowledge=False)
        handle = await self.start_external(binding)
        result = await self.manager.mark_agent_dead(self.person.agent_id, confirm=True)
        self.assertEqual(result["tasks"][0]["status"], "CANCELLED")
        self.assertEqual(binding.pauses, [handle.execution_id])
        self.assertEqual(binding.stops, [handle.execution_id])
        self.assertEqual(self.manager._records.index[("executions", (handle.execution_id,))].values["status"], "cancelled")

    async def test_unstoppable_owned_worker_cannot_write_later_or_fence_other_people(self):
        started, release = asyncio.Event(), asyncio.Event()
        attempted = asyncio.Event()
        library = self.manager.libraries[self.person.private_doc_library_id]
        async def late_write():
            started.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()
            try:
                library.write_file("late.txt", "must be rejected")
            except PermissionError:
                attempted.set()
            return "late outcome"
        self.manager.register_tool("late_write", func=late_write,
            execution_contract=contract(effects=("artifact_write",), mutation_safety="managed_lease"))
        handle = await self.manager.start_background_task("late_write", {}, actor=self.person)
        await asyncio.wait_for(started.wait(), 10)
        try:
            result = await asyncio.wait_for(self.manager.mark_agent_dead(self.person.agent_id, confirm=True), 10)
            self.assertEqual(result["tasks"][0]["status"], "UNCONFIRMED")
            row = self.manager._records.index[("executions", (handle.execution_id,))]
            self.assertTrue(row.values["outcome_unconfirmed"])
            self.manager.libraries[self.root.private_doc_library_id].write_file("healthy.txt", "independent")
        finally:
            release.set()
            await asyncio.wait_for(attempted.wait(), 10)
            await asyncio.gather(*tuple(self.manager._executions.tasks), return_exceptions=True)
        self.assertFalse(library.path_exists("late.txt"))
