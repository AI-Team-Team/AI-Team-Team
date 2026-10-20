"""Coordinated operations retain the same evidence without independent workers."""

import asyncio
from pathlib import Path

from ai_team_team import StatePersistenceError
from test.test_att.test_agent_activity._support import call, idle

from ._support import BackgroundTestCase, contract


class ForegroundEvidenceTests(BackgroundTestCase):
    async def test_first_partial_export_includes_observation_execution_dependencies(self):
        async def ordinary(value: str) -> str:
            return value

        self.manager.register_tool("ordinary", func=ordinary)
        self.steps(call("ordinary", {"value": "foreground answer"}), idle())
        admitted = await self.manager.activate_agent(self.root.agent_id)
        await self.wait(admitted)
        ordinary_row = next(row for row in self.records("executions") if row.values["tool_name"] == "ordinary")
        self.assertEqual(ordinary_row.values["status"], "completed")
        self.assertIsNotNone(ordinary_row.values["started_at"])
        self.assertIsNotNone(ordinary_row.values["finished_at"])
        self.assertEqual(ordinary_row.values["contract_snapshot"]["effects"], ("undeclared",))
        self.assertTrue(any(message.get("source_execution_id") == ordinary_row.values["execution_id"] for message in self.root.messages))
        dirty = self.manager._new_dirty_state()
        dirty["agents"].add(self.root.agent_id)
        dirty["configs"] = True
        snapshot = self.manager._capture_state_snapshot(dirty)
        target = str(Path(self.workspace.name) / "first-partial.sqlite")
        await asyncio.wrap_future(self.manager._persistence.submit(target, snapshot))
        state = await self.manager._persistence.read(target)
        self.manager._validate_state_snapshot(state)
        self.assertEqual({row.values["execution_id"] for row in state["records"] if row.table_name == "executions"},
                         {row.values["execution_id"] for row in self.records("executions")})
        await self.manager.load_state(target)
        self.assertEqual(self.manager.root_ai.agent_id, self.root.agent_id)

    async def test_fatal_auditor_error_before_dispatch_is_not_reported_as_cancelled(self):
        invoked = []

        async def operation() -> str:
            invoked.append(True)
            return "never"

        async def auditor():
            raise StatePersistenceError("The auditor's authoritative write failed.")

        self.manager.register_tool("operation", func=operation, execution_contract=contract())
        self.manager.tool_auditors["operation"] = auditor
        self.steps(call("operation"))
        admitted = await self.manager.activate_agent(self.root.agent_id)
        with self.assertRaises(StatePersistenceError):
            await self.wait(admitted)
        self.assertFalse(invoked)
        execution = next(row for row in self.records("executions") if row.values["tool_name"] == "operation")
        self.assertEqual(execution.values["status"], "queued")
        self.assertEqual(execution.values["outcome_unconfirmed"], 1)
        self.assertIsNone(execution.values["started_at"])
        self.assertFalse(self.records("execution_attempts"))
        with self.assertRaises(StatePersistenceError):
            await self.manager.close()

    async def test_missing_private_delete_is_classified(self):
        handle = await self.start("delete_private_file", {"path": "absent.txt"})
        job = await self.finish(handle)
        self.assertEqual(job.result.status.value, "business_error")
        self.assertEqual(self.manager.inspect_background_task(handle.execution_id, actor=self.root).execution_state, "failed")
