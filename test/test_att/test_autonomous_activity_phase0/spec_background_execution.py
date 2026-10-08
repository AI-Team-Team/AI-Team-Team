"""Intentionally red until Phase 4; no second invocation or executor is faked."""

import asyncio
import unittest

from ai_team_team import LLMResponse, ToolCall
from ai_team_team.core.activity.contracts import BackgroundTaskHandle, ToolExecutionContract

from test.test_att.test_autonomous_activity_phase0._fixtures import (
    AsyncBarrier,
    ControlledExecutor,
    ModelStep,
)
from test.test_att.test_autonomous_activity_phase0._runtime_spec import (
    RuntimeSpecFixture,
    idle_response,
    model_input,
)


class SpecBackgroundExecution(RuntimeSpecFixture, unittest.IsolatedAsyncioTestCase):
    async def test_threshold_releases_only_the_wait_and_produces_one_native_observation(self):
        activate = self.require_method("activate_agent")
        bind_clock = self.require_method("register_runtime_clock")
        bind_clock(self.clock)
        executor = ControlledExecutor()
        self.addCleanup(executor.close)

        async def controlled_operation() -> str:
            return (await executor()).value

        self.manager.register_tool(
            name="controlled_operation",
            func=controlled_operation,
            execution_contract=ToolExecutionContract(
                effects=("read_only",), background_allowed=True, required_scope="personal"
            ),
        )
        handle_frame = AsyncBarrier()
        result_frame = AsyncBarrier()
        self.client.steps.extend(
            [
                ModelStep(LLMResponse(tool_calls=[ToolCall("slow-A", "controlled_operation", {})])),
                ModelStep(LLMResponse(text="I can attend to another matter."), handle_frame),
                ModelStep(idle_response(), result_frame),
            ]
        )
        admitted = await activate(self.person.agent_id)
        await asyncio.wait_for(executor.started.wait(), timeout=5)
        self.clock.advance(120)
        await handle_frame.wait_entered()
        observations = [
            item for item in self.client.requests[-1].prompt if item.get("tool_call_id") == "slow-A"
        ]
        self.assertEqual(len(observations), 1)
        handle = BackgroundTaskHandle.model_validate_json(observations[0]["content"])
        self.assertEqual(handle.durability, "durable")
        self.assertEqual(executor.side_effects, 1)
        executor.complete("completed original operation")
        handle_frame.release()
        await result_frame.wait_entered()
        notification_context = model_input(self.client.requests[-1], notification_only=True)
        self.assertIn(handle.execution_id, notification_context)
        self.assertIn("completed", notification_context.lower())
        self.assertEqual(
            sum(item.get("tool_call_id") == "slow-A" for item in self.client.requests[-1].prompt), 1
        )
        self.assertEqual(executor.calls, 1)
        self.assertEqual(self.client.maximum_in_flight, 1)
        result_frame.release()
        await self.wait_idle(admitted.admission_id)
