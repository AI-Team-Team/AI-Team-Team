"""Parallel faults and receipt settlement preserve one coherent tool cooldown."""

import asyncio
from unittest.mock import patch

from ai_team_team import LLMResponse, RetryableToolError, StatePersistenceError, Tool, ToolCall
from ai_team_team.core.tool_runtime import ToolExecutor
from test.test_att.test_autonomous_activity_phase0._fixtures import AsyncBarrier, ModelStep

from ._support import ActivityTestCase, call, idle, personal_control_contract


class CooldownTransactionTests(ActivityTestCase):
    async def test_parallel_same_tool_faults_serialize_their_record_versions(self):
        self.manager.register_runtime_clock(self.clock)
        for mode in ("include", "exclude"):
            for exception in (RetryableToolError, RuntimeError):
                with self.subTest(mode=mode, exception=exception.__name__):
                    name = f"fault_{mode}_{exception.__name__}"
                    started, release = asyncio.Event(), asyncio.Event()
                    committing, commit_release, returned = asyncio.Event(), asyncio.Event(), asyncio.Event()
                    calls = results = 0
                    original_commit = self.manager._records.commit
                    original_execute = ToolExecutor.execute
                    self.manager.config.activity.cooldown_downtime = mode

                    async def fault():
                        nonlocal calls
                        calls += 1
                        if calls == 2:
                            started.set()
                        await release.wait()
                        raise exception("Synthetic simultaneous service failure")

                    async def commit(records=(), **kwargs):
                        if any(row.table_name == "tool_cooldowns" for row in records):
                            committing.set()
                            await commit_release.wait()
                        return await original_commit(records, **kwargs)

                    async def execute(executor, tool_name, *args, **kwargs):
                        nonlocal results
                        result = await original_execute(executor, tool_name, *args, **kwargs)
                        if tool_name == name:
                            results += 1
                            if results == 2:
                                returned.set()
                        return result

                    self.manager.register_tool(name, func=fault, execution_contract=personal_control_contract())
                    self.steps(
                        LLMResponse(tool_calls=[ToolCall("a", name, {}), ToolCall("b", name, {})]),
                        call(name, call_id="cooling"),
                        idle(),
                    )
                    with (
                        patch.object(self.manager._records, "commit", commit),
                        patch.object(ToolExecutor, "execute", execute),
                    ):
                        admission = await self.manager.activate_agent(self.root.agent_id)
                        try:
                            await asyncio.wait_for(started.wait(), 5)
                            release.set()
                            await asyncio.wait_for(committing.wait(), 5)
                            await asyncio.wait_for(returned.wait(), 5)
                            commit_release.set()
                            await self.wait(admission)
                            await self.settle()
                        finally:
                            release.set()
                            commit_release.set()
                    cooldown = self.manager._records.index[("tool_cooldowns", (self.root.agent_id, name))]
                    executions = [row for row in self.records("executions") if row.values["tool_name"] == name]
                    self.assertEqual(calls, 2, "Cooling must reject a third call without replay.")
                    self.assertEqual(cooldown.version, 2)
                    self.assertEqual(len(executions), 2)
                    self.assertTrue(all(row.values["status"] == "failed" for row in executions))
                    self.assertIn(cooldown.values["fault_id"], {row.values["execution_id"] for row in executions})
                    self.assertEqual(self.manager._activity.cooldown_remaining(cooldown), 600)
                    self.assertIsNone(self.manager._activity.sessions[self.root.agent_id].failure)
        self.assertEqual(len(self.client.requests), 12)
        self.assertFalse(self.manager._activity.fatal_errors)

    async def active_session(self):
        self.manager.register_runtime_clock(self.clock)
        self.manager.config.activity.cooldown_downtime = "exclude"
        barrier = AsyncBarrier()
        self.client.steps.append(ModelStep(idle(), barrier))
        admission = await self.manager.activate_agent(self.root.agent_id)
        await barrier.wait_entered()
        return self.manager._activity.sessions[self.root.agent_id], admission, barrier

    async def test_rejected_cooldown_receipt_does_not_publish_a_monotonic_deadline(self):
        session, admission, barrier = await self.active_session()
        original = self.manager._records.commit

        async def reject(records, **kwargs):
            if any(row.table_name == "tool_cooldowns" for row in records):
                raise StatePersistenceError("Synthetic rejected cooldown receipt")
            return await original(records, **kwargs)

        def fault():
            raise RetryableToolError("Synthetic service failure")

        tool = Tool("fault", func=fault, execution_contract=personal_control_contract())
        try:
            with patch.object(self.manager._records, "commit", reject):
                with self.assertRaisesRegex(StatePersistenceError, "cooldown receipt"):
                    await self.manager._activity.execute_tool(
                        session, "fault", [], {}, call_id="fault", tools={"fault": tool}
                    )
            self.assertFalse(self.records("tool_cooldowns"))
            self.assertFalse(self.manager._activity.cooldown_deadlines)
        finally:
            barrier.release()
            await self.wait(admission)
        with self.assertRaises(StatePersistenceError):
            await self.manager.close()

    async def test_cancelled_observer_publishes_a_successfully_committed_deadline(self):
        session, admission, barrier = await self.active_session()
        committed, release = asyncio.Event(), asyncio.Event()
        original = self.manager._records.commit

        async def commit(records, **kwargs):
            receipt = await original(records, **kwargs)
            if any(row.table_name == "tool_cooldowns" for row in records):
                committed.set()
                await release.wait()
            return receipt

        def fault():
            raise RetryableToolError("Synthetic service failure")

        tool = Tool("fault", func=fault, execution_contract=personal_control_contract())
        with patch.object(self.manager._records, "commit", commit):
            execution = asyncio.create_task(self.manager._activity.execute_tool(
                session, "fault", [], {}, call_id="fault", tools={"fault": tool}
            ))
            try:
                await asyncio.wait_for(committed.wait(), 5)
                self.assertFalse(self.manager._activity.cooldown_deadlines)
                self.clock.advance(30)
                execution.cancel()
                await asyncio.sleep(0)
                self.assertFalse(execution.done(), "Accepted local settlement must survive observer cancellation.")
                release.set()
                with self.assertRaises(asyncio.CancelledError):
                    await execution
                row = self.records("tool_cooldowns")[0]
                self.assertEqual(self.manager._activity.cooldown_remaining(row), 570)
                self.assertEqual(self.manager._activity.cooldown_deadlines[(self.root.agent_id, "fault")], 600)
            finally:
                release.set()
                await asyncio.gather(execution, return_exceptions=True)
                barrier.release()
                await self.wait(admission)
