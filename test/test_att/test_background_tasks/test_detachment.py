"""Text and Native close the original call exactly once without replay."""

import asyncio
import unittest

from ai_team_team import LLMResponse, ToolCall
from ai_team_team.core.activity.contracts import BackgroundTaskHandle
from test.test_att.test_agent_activity._support import ActivityTestCase, idle
from test.test_att.test_autonomous_activity_phase0._fixtures import AsyncBarrier, ControlledExecutor, ModelStep
from test.test_att.test_autonomous_activity_phase0 import spec_background_execution as frozen

from ._support import BackgroundTestCase, contract


class FrozenBackgroundContractTests(frozen.SpecBackgroundExecution):
    """The previously red Phase 0 contract now participates in discovery."""


class DetachmentTests(ActivityTestCase):
    async def test_text_detachment_continues_without_a_second_execution(self):
        self.manager.config.tool_calling_mode = "react"
        self.manager.register_runtime_clock(self.clock)
        executor = ControlledExecutor()
        self.addCleanup(executor.close)

        async def slow() -> str:
            return (await executor()).value

        self.manager.register_tool("slow", func=slow, execution_contract=contract())
        next_request = AsyncBarrier()
        self.client.steps.extend((ModelStep(LLMResponse(text="Action: slow()")), ModelStep(idle(native=False), next_request)))
        admission = await self.manager.activate_agent(self.root.agent_id)
        await asyncio.wait_for(executor.started.wait(), 5)
        self.clock.advance(120)
        await next_request.wait_entered()
        self.assertEqual(executor.calls, 1)
        self.assertIn('"status":"BACKGROUND"', str(self.client.requests[-1].prompt))
        executor.complete("original result")
        next_request.release()
        await self.wait(admission)

    async def test_fast_native_sibling_and_one_handle_close_a_complete_batch(self):
        self.manager.register_runtime_clock(self.clock)
        started, release = asyncio.Event(), asyncio.Event()
        calls = []

        async def slow() -> str:
            calls.append("slow")
            started.set()
            await release.wait()
            return "slow result"

        async def fast() -> str:
            calls.append("fast")
            return "fast result"

        self.manager.register_tool("slow", func=slow, execution_contract=contract())
        self.manager.register_tool("fast", func=fast, execution_contract=contract())
        boundary = AsyncBarrier()
        self.client.steps.extend((ModelStep(LLMResponse(tool_calls=[ToolCall("slow-call", "slow", {}), ToolCall("fast-call", "fast", {})])),
                                  ModelStep(idle(), boundary)))
        admitted = await self.manager.activate_agent(self.root.agent_id)
        await asyncio.wait_for(started.wait(), 5)
        self.clock.advance(120)
        await boundary.wait_entered()
        observations = [item for item in self.client.requests[-1].prompt if item.get("role") == "tool"]
        self.assertEqual({item["tool_call_id"] for item in observations}, {"slow-call", "fast-call"})
        self.assertEqual(len(observations), 2)
        handle = next(item for item in observations if item["tool_call_id"] == "slow-call")
        BackgroundTaskHandle.model_validate_json(handle["content"])
        self.assertEqual(sorted(calls), ["fast", "slow"])
        release.set()
        boundary.release()
        await self.wait(admitted)


class CompletionRaceTests(BackgroundTestCase):
    async def test_explicit_native_task_retains_the_actual_invocation_and_call_identity(self):
        async def operation(value: str) -> str:
            return value

        self.manager.register_tool("operation", func=operation, execution_contract=contract())
        self.steps(LLMResponse(tool_calls=[ToolCall("explicit-call", "start_background_task",
            {"tool_name": "operation", "arguments": {"value": "explicit result"}})]), idle())
        admitted = await self.manager.activate_agent(self.root.agent_id)
        await self.wait(admitted)
        observations = [message for message in self.client.requests[-1].prompt
                        if message.get("role") == "tool" and message.get("tool_call_id") == "explicit-call"]
        self.assertEqual(len(observations), 1)
        handle = BackgroundTaskHandle.model_validate_json(observations[0]["content"])
        await self.finish(handle)
        execution = self.manager._records.index[("executions", (handle.execution_id,))]
        self.assertEqual(execution.values["call_id"], "explicit-call")
        self.assertEqual(execution.values["invocation_id"], observations[0]["invocation_id"])
        self.assertEqual(execution.values["visibility"], "explicit_background")

    async def test_fast_result_stays_foreground_without_a_task_notice(self):
        self.manager.register_runtime_clock(self.clock)

        async def fast() -> str:
            return "fast"

        self.manager.register_tool("fast", func=fast, execution_contract=contract())
        self.steps(LLMResponse(tool_calls=[ToolCall("fast", "fast", {})]), idle())
        admitted = await self.manager.activate_agent(self.root.agent_id)
        await self.wait(admitted)
        view = self.manager.list_background_tasks(actor=self.root, include_foreground=True)
        result = next(item for item in view.items if item.tool_name == "fast")
        self.assertEqual(result.visibility, "foreground")
        self.assertEqual(result.execution_state, "completed")
        self.assertFalse(self.records("agent_notifications"))
