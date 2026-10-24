"""Atomic shared-model quotas at the actual personal provider boundary."""

import asyncio
from unittest.mock import patch

from ai_team_team import Agent, LLMResponse, Tool
from ai_team_team.core.adapters import HandlerClientAdapter
from ai_team_team.core.manager.activity.values import ModelUnavailable
from ai_team_team.core.utils import _count_request_input_tokens, generate_with_retry
from test.test_att.test_agent_activity._support import ActivityTestCase, idle
from test.test_att.test_autonomous_activity_phase0._fixtures import AsyncBarrier, ModelStep


class TestCriticalPersonalBudgets(ActivityTestCase):
    async def test_concurrent_people_cannot_reserve_the_same_remaining_allowance(self):
        barrier = AsyncBarrier()
        response = idle()
        response.usage = {"input_tokens": 2, "output_tokens": 1}
        self.client.steps.append(ModelStep(response, barrier))
        other = self.manager.register_agent(Agent("Other", "Researcher", self.client))
        self.manager.config.model_token_limits["fixture"] = 10
        self.manager.config.model_max_output_tokens["fixture"] = 6
        with patch("ai_team_team.core.manager.activity.models._count_request_input_tokens", return_value=2):
            first = await self.manager.activate_agent(self.root.agent_id)
            try:
                await barrier.wait_entered()
                self.assertEqual(self.manager.token_budget.available("fixture"), 2)
                second = await self.manager.activate_agent(other.agent_id)
                with self.assertRaises(ModelUnavailable):
                    await self.wait(second)
                self.assertEqual(len(self.client.requests), 1)
            finally:
                barrier.release()
            await self.wait(first)
        self.assertEqual(self.manager.token_budget.available("fixture"), 7)
        self.assertEqual(self.records("model_token_claims")[0].values["actual_usage"], 3)

    async def test_estimator_includes_system_instructions_and_full_tool_definitions(self):
        self.manager.count_tokens = lambda text, alias: len(str(text))
        tool = Tool("large_tool", "Definition metadata", lambda: "ok")
        plain = _count_request_input_tokens(self.manager, "fixture", "prompt", None, None)
        system = _count_request_input_tokens(self.manager, "fixture", "prompt", "SYSTEM_CONTENT", None)
        schema = _count_request_input_tokens(self.manager, "fixture", "prompt", None, [tool])
        self.assertEqual(system - plain, len("SYSTEM_CONTENT"))
        self.assertGreater(schema, plain + len(tool.description))
        self.manager.config.model_token_limits["fixture"] = 100
        admission = await self.manager.activate_agent(self.root.agent_id)
        with self.assertRaises(ModelUnavailable):
            await self.wait(admission)
        self.assertFalse(self.client.requests)
        self.assertFalse(self.records("model_token_claims"))

    async def test_cancellation_keeps_unknown_sent_reservation_without_inventing_usage(self):
        barrier = AsyncBarrier()
        self.client.steps.append(ModelStep(idle(), barrier))
        self.manager.config.model_token_limits["fixture"] = 20
        self.manager.config.model_max_output_tokens["fixture"] = 5
        with patch("ai_team_team.core.manager.activity.models._count_request_input_tokens", return_value=2):
            await self.manager.activate_agent(self.root.agent_id)
            await barrier.wait_entered()
            worker = self.manager._activity.sessions[self.root.agent_id].worker
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
        barrier.release()
        claim = self.records("model_token_claims")[0]
        self.assertEqual(claim.values["settlement"], "unknown_sent")
        self.assertIsNone(claim.values["actual_usage"])
        self.assertEqual(self.manager.token_budget.available("fixture"), 13)

    async def test_handler_output_cap_reaches_the_actual_common_model_request(self):
        observed = []

        async def handler(model_name, prompt, max_tokens, system_instruction=None, temperature=0.3, require_json=False):
            observed.append((model_name, max_tokens))
            return "Action: set_activity_intent(intent={'kind': 'idle'})"

        client = HandlerClientAdapter("bounded", handler)
        self.manager.register_llm_client("bounded", client)
        self.root.llm_client = client
        self.manager.config.tool_calling_mode = "text_react"
        self.manager.config.model_token_limits["bounded"] = 1_000_000
        self.manager.config.model_max_output_tokens["bounded"] = 4
        admission = await self.manager.activate_agent(self.root.agent_id)
        await self.wait(admission)
        self.assertEqual(observed, [("bounded", 4)])

    async def test_manager_inference_utility_cannot_start_a_second_execution_engine(self):
        with self.assertRaisesRegex(RuntimeError, "current personal activity"):
            await generate_with_retry(self.client, "Do not bypass admission.", manager=self.manager)
        self.assertFalse(self.client.requests)
