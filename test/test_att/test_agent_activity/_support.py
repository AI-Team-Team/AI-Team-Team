"""Logical clocks, exact idle choices, and isolated runtime managers."""

import asyncio
import tempfile
import unittest
from pathlib import Path

from ai_team_team import ATTConfig, ATTManager, Agent, LLMResponse, ToolCall
from test.test_att.test_autonomous_activity_phase0._fixtures import (
    LogicalClock,
    ModelStep,
    ScriptedModelClient,
)


def call(name, arguments=None, *, call_id="call"):
    return LLMResponse(tool_calls=[ToolCall(call_id, name, arguments or {})])


def idle(*, native=True):
    return (
        call("set_activity_intent", {"intent": {"kind": "idle"}}, call_id="idle")
        if native
        else LLMResponse(text="Action: set_activity_intent(intent={'kind': 'idle'})")
    )


class ActivityTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.workspace = tempfile.TemporaryDirectory(prefix="att-personal-runtime-")
        self.addCleanup(self.workspace.cleanup)
        self.client = ScriptedModelClient()
        self.root = Agent("Root", "Architect", self.client)
        self.manager = self.make_manager(self.root)
        self.clock = LogicalClock()
        self.addCleanup(self.clock.close)

    def make_manager(self, root, *, durable=False, config=None):
        manager = ATTManager(
            root,
            config or ATTConfig(workspace_root=self.workspace.name, tool_calling_mode="native"),
            db_path=str(Path(self.workspace.name) / "state.sqlite") if durable else None,
            persistence_mode="durable" if durable else "volatile",
        )
        manager.register_llm_client("fixture", root.llm_client)
        self.addAsyncCleanup(manager.close)
        return manager

    async def wait(self, admission, intent="idle"):
        return await asyncio.wait_for(
            self.manager.wait_for_activity_checkpoint(admission.admission_id, intent=intent), 10
        )

    def steps(self, *responses):
        self.client.steps.extend(ModelStep(response) for response in responses)

    def records(self, table):
        return [row for row in self.manager._records.snapshot() if row.table_name == table]

    async def settle(self, *, timeout=15):
        async with asyncio.timeout(timeout):
            while (
                self.manager._activity.workers
                or self.manager._activity.dispatch_tasks
                or not self.manager._activity.ready.empty()
            ):
                tasks = tuple(
                    self.manager._activity.workers | self.manager._activity.dispatch_tasks
                )
                if tasks:
                    await asyncio.gather(*(asyncio.shield(task) for task in tasks))
                # Done callbacks remove completed handles on the next loop
                # opportunity; awaiting an already-done gather need not yield.
                await asyncio.sleep(0)
