"""Persistent claims, bounded retries, and unacknowledged local provider waits."""

import asyncio

from ai_team_team import LLMResponse, TransientLLMError

from ._support import ActivityTestCase, idle


async def observed(predicate):
    async with asyncio.timeout(10):
        while not predicate():
            await asyncio.sleep(0)


class ModelRequestTests(ActivityTestCase):
    async def test_explicit_input_and_schema_are_reserved_and_usage_settles_once(self):
        self.manager.config.model_token_limits["fixture"] = 1_000_000
        self.manager.config.model_max_output_tokens["fixture"] = 20
        response = idle()
        response.usage = {"total_tokens": 17}
        self.steps(response)
        admission = await self.manager.activate_agent(self.root.agent_id)
        await self.wait(admission)
        claims = self.records("model_token_claims")
        self.assertEqual(len(claims), 1)
        self.assertGreater(claims[0].values["prompt_budget"], 100)
        self.assertEqual(claims[0].values["output_budget"], 20)
        self.assertEqual(claims[0].values["settlement"], "known_usage")
        self.assertEqual(claims[0].values["actual_usage"], 17)
        self.assertEqual(self.manager.token_budget.available("fixture"), 1_000_000 - 17)
        self.assertEqual(self.client.requests[0].max_output_tokens, 20)
        self.assertEqual(self.records("model_requests")[0].values["outcome"], "completed")

    async def test_disabled_budget_stops_before_dispatch_and_requires_remediation(self):
        self.manager.config.model_token_limits["fixture"] = 0
        admission = await self.manager.activate_agent(self.root.agent_id)
        from ai_team_team.core.manager.activity.values import ModelUnavailable

        with self.assertRaises(ModelUnavailable):
            await self.wait(admission)
        self.assertFalse(self.client.requests)
        self.assertEqual(
            self.manager.inspect_agent_activity(self.root.agent_id).intent, "continuing"
        )
        self.assertEqual(
            self.records("model_availability")[0].values["status"], "remediation_required"
        )

    async def test_provider_wait_overrides_jitter_cap_and_refreshes_arrivals_on_retry(self):
        self.manager.register_runtime_clock(self.clock)
        self.manager._activity.models.jitter = lambda low, high: high
        error = TransientLLMError("Synthetic rate limit")
        error.retry_after = 90
        self.steps(error, idle())
        admission = await self.manager.activate_agent(self.root.agent_id)
        await observed(
            lambda: (
                self.records("model_requests")
                and self.records("model_requests")[0].values["outcome"] == "failed"
            )
        )
        await observed(lambda: self.clock.pending_waits == 1)
        receipt = await self.manager.deliver_agent_mail(
            self.root.agent_id, message_type="note", payload={}
        )
        self.clock.advance(89)
        self.assertEqual(len(self.client.requests), 1)
        self.clock.advance(1)
        await self.wait(admission)
        self.assertEqual(len(self.client.requests), 2)
        self.assertIn(receipt.message_id, str(self.client.requests[1].prompt))
        self.assertEqual(
            [row.values["attempt_index"] for row in self.records("model_requests")], [1, 2]
        )

    async def test_provider_wait_beyond_sequence_budget_defers_without_early_dispatch(self):
        self.manager.register_runtime_clock(self.clock)
        error = TransientLLMError("Synthetic rate limit")
        error.retry_after = 900
        self.steps(error, idle())
        admission = await self.manager.activate_agent(self.root.agent_id)
        from ai_team_team.core.manager.activity.values import ModelUnavailable

        with self.assertRaises(ModelUnavailable):
            await self.wait(admission)
        availability = self.records("model_availability")[0]
        self.assertEqual(availability.values["earliest_admission_at"], 900)
        self.assertEqual(self.records("model_requests")[0].values["earliest_retry_at"], 900)
        self.clock.advance(899)
        self.assertEqual(len(self.client.requests), 1)
        self.clock.advance(1)
        await observed(lambda: len(self.client.requests) == 2)
        await self.settle()
        self.assertEqual(self.manager.inspect_agent_activity(self.root.agent_id).intent, "idle")

    async def test_permanent_provider_error_has_no_periodic_recovery(self):
        self.manager.register_runtime_clock(self.clock)
        self.steps(ValueError("Synthetic invalid provider configuration"))
        admission = await self.manager.activate_agent(self.root.agent_id)
        from ai_team_team.core.manager.activity.values import ModelUnavailable

        with self.assertRaises(ModelUnavailable):
            await self.wait(admission)
        self.clock.advance(10_000)
        self.assertFalse(self.manager._activity.timers)
        self.assertEqual(len(self.client.requests), 1)
        with self.assertRaises(ModelUnavailable):
            await self.manager.activate_agent(self.root.agent_id)

    async def test_timeout_preserves_unknown_usage_and_never_overlaps_a_live_local_request(self):
        self.manager.register_runtime_clock(self.clock)
        self.manager.config.activity.llm.max_retries = 0
        self.manager.config.activity.llm.request_timeout_seconds = 1.0
        entered, release = asyncio.Event(), asyncio.Event()
        calls, maximum, active = 0, 0, 0

        class Uncooperative:
            def supports_output_token_limit(self):
                return True

            async def generate(inner, **kwargs):
                nonlocal calls, maximum, active
                calls += 1
                active += 1
                maximum = max(maximum, active)
                try:
                    if calls == 1:
                        entered.set()
                        while not release.is_set():
                            try:
                                await release.wait()
                            except asyncio.CancelledError:
                                continue
                        return LLMResponse(text="LATE_OUTPUT_MUST_NOT_ENTER_MEMORY")
                    return idle()
                finally:
                    active -= 1

        client = Uncooperative()
        self.manager.register_llm_client("uncooperative", client)
        self.root.llm_client = client
        self.manager.config.model_token_limits["uncooperative"] = 1_000_000
        self.manager.config.model_max_output_tokens["uncooperative"] = 10
        try:
            admission = await self.manager.activate_agent(self.root.agent_id)
            await asyncio.wait_for(entered.wait(), 5)
            self.clock.advance(1)
            from ai_team_team.core.manager.activity.values import ModelUnavailable

            with self.assertRaises(ModelUnavailable):
                await self.wait(admission)
            claim = self.records("model_token_claims")[0]
            self.assertEqual(claim.values["settlement"], "unknown_sent")
            self.assertIsNone(claim.values["actual_usage"])
            self.clock.advance(60)
            with self.assertRaises(ModelUnavailable):
                await self.manager.activate_agent(self.root.agent_id)
            self.assertEqual(calls, 1)
            release.set()
            await observed(lambda: calls == 2)
            await self.settle()
            self.assertEqual(maximum, 1)
            self.assertNotIn("LATE_OUTPUT_MUST_NOT_ENTER_MEMORY", str(self.root.messages))
            self.assertNotIn("LATE_OUTPUT_MUST_NOT_ENTER_MEMORY", str(self.root.message_history))
        finally:
            release.set()
            await asyncio.gather(
                *tuple(self.manager._activity.models.tasks), return_exceptions=True
            )

    async def test_close_does_not_wait_for_an_uncooperative_provider(self):
        entered, release = asyncio.Event(), asyncio.Event()

        class NeverUntilReleased:
            async def generate(inner, **kwargs):
                entered.set()
                while not release.is_set():
                    try:
                        await release.wait()
                    except asyncio.CancelledError:
                        continue
                return LLMResponse(text="late after close")

        client = NeverUntilReleased()
        self.manager.register_llm_client("hanging", client)
        self.root.llm_client = client
        try:
            await self.manager.activate_agent(self.root.agent_id)
            await asyncio.wait_for(entered.wait(), 5)
            await asyncio.wait_for(self.manager.close(), 3)
            self.assertTrue(self.manager._closed)
            self.assertFalse(self.manager._activity.workers)
            self.assertEqual(
                self.records("model_token_claims")[0].values["settlement"], "unknown_sent"
            )
        finally:
            release.set()
            await asyncio.gather(
                *tuple(self.manager._activity.models.tasks), return_exceptions=True
            )
        self.assertNotIn("late after close", str(self.root.message_history))
