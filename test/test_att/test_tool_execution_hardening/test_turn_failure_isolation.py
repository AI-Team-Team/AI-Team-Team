"""Personal runtime failures never imply a synthetic team-wide outcome."""

import asyncio

from ai_team_team import Agent, LLMResponse, StatePersistenceError
from ai_team_team.core.manager.activity.values import ModelUnavailable
from test.personal_activity import interact_and_idle
from test.test_att.test_agent_activity._support import ActivityTestCase, call, idle
from test.test_att.test_autonomous_activity_phase0._fixtures import ModelStep, ScriptedModelClient


class TestPersonalFailureIsolation(ActivityTestCase):
    async def test_invalid_action_can_be_corrected_after_a_technical_checkpoint(self):
        self.manager.config.tool_calling_mode = "text_react"
        self.manager.config.activity.model_requests_per_invocation = 1
        self.steps(LLMResponse(text="Action: missing("), LLMResponse(text="Final Answer: recovered"), idle(native=False))
        result = await interact_and_idle(self.manager, self.root, "Correct an invalid action.")
        self.assertEqual(result.answer, "recovered")
        self.assertEqual(len(self.records("activity_invocations")), 3)
        self.assertTrue(any(message.get("tool_status") == "invalid_arguments" for message in self.root.messages))
        self.assertFalse(self.records("audit_runs"))

    async def test_unavailable_person_does_not_stop_another_person(self):
        self.manager.config.activity.llm.max_retries = 0
        other_client = ScriptedModelClient(ModelStep(LLMResponse(text="Independent answer")), ModelStep(idle()))
        self.manager.register_llm_client("other", other_client)
        other = self.manager.register_agent(Agent("Other", "Researcher", other_client))
        self.steps(ValueError("SENSITIVE_PROVIDER_DETAIL"))
        first = asyncio.create_task(self.manager.execute_agent_interaction(self.root, "Use the unavailable resource."))
        second = asyncio.create_task(interact_and_idle(self.manager, other, "Continue independent work."))
        with self.assertRaises(ModelUnavailable):
            await first
        self.assertEqual((await second).answer, "Independent answer")
        self.assertEqual(self.root.lifecycle_state, "active")
        self.assertEqual(other.lifecycle_state, "active")
        self.assertFalse(self.records("health_incidents"))

    async def test_resource_failure_event_does_not_expose_provider_details(self):
        events = []
        self.manager.on_system_event = lambda event, payload: events.append((event, payload))
        self.steps(ValueError("SENSITIVE_PROVIDER_DETAIL"))
        with self.assertRaises(ModelUnavailable) as caught:
            await self.manager.execute_agent_interaction(self.root, "Use the unavailable resource.")
        await self.manager.flush_callbacks()
        self.assertTrue(any(event == "model_unavailable" for event, _ in events))
        self.assertNotIn("SENSITIVE_PROVIDER_DETAIL", repr(events))
        self.assertNotIn("SENSITIVE_PROVIDER_DETAIL", str(caught.exception))

    async def test_tool_failure_callback_has_metadata_not_arguments_or_private_body(self):
        events = []
        self.manager.on_system_event = lambda event, payload: events.append((event, payload))

        async def secret_tool(value: str):
            raise RuntimeError(f"Sensitive failure body: {value}")

        self.manager.register_tool("secret_tool", func=secret_tool)
        self.steps(call("secret_tool", {"value": "SECRET_ARGUMENT"}), idle())
        admission = await self.manager.activate_agent(self.root.agent_id)
        await self.wait(admission)
        await self.manager.flush_callbacks()
        failures = [payload for name, payload in events if name == "tool_execution_failed"]
        self.assertEqual(len(failures), 1)
        self.assertNotIn("SECRET_ARGUMENT", repr(events))
        self.assertNotIn("Sensitive failure body", repr(events))

    async def test_authoritative_failure_and_cancellation_still_propagate(self):
        async def fatal():
            raise StatePersistenceError("Authoritative receipt failed")

        self.manager.register_tool("fatal", func=fatal)
        self.steps(call("fatal"))
        with self.assertRaises(StatePersistenceError):
            await self.manager.execute_agent_interaction(self.root, "Run the authoritative operation.")
        self.assertFalse(self.root.lock.locked())
        self.assertFalse(self.records("audit_runs"))
        with self.assertRaises(StatePersistenceError):
            await self.manager.close()
