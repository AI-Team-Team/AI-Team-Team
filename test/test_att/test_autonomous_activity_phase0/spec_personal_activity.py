"""Intentionally red until Phase 2; run with the explicit spec_*.py command."""

import unittest

from ai_team_team import LLMResponse, ToolCall
from ai_team_team.core.activity.contracts import AgentTeamScope, ToolExecutionContract

from test.test_att.test_autonomous_activity_phase0._fixtures import AsyncBarrier, ModelStep
from test.test_att.test_autonomous_activity_phase0._runtime_spec import (
    RuntimeSpecFixture,
    idle_response,
    model_input,
)


class SpecPersonalActivity(RuntimeSpecFixture, unittest.IsolatedAsyncioTestCase):
    async def test_a_plain_answer_continues_activity_without_publication(self):
        activate = self.require_method("activate_agent")
        list_messages = self.require_method("list_team_messages")
        second_request = AsyncBarrier()
        self.client.steps.extend(
            [
                ModelStep(LLMResponse(text="PRIVATE_UNPUBLISHED_ANSWER")),
                ModelStep(idle_response(), second_request),
            ]
        )
        admitted = await activate(
            self.person.agent_id, scope=AgentTeamScope(team_id=self.first.team_id)
        )
        await second_request.wait_entered()
        self.assertEqual(self.client.maximum_in_flight, 1)
        self.assertEqual(list_messages(self.first.team_id, actor=self.person).total_count, 0)
        second_request.release()
        self.assertEqual((await self.wait_idle(admitted.admission_id)).intent, "idle")

    async def test_shared_person_admission_coalesces_across_team_scopes(self):
        activate = self.require_method("activate_agent")
        view = self.require_method("inspect_agent_activity")
        barrier = AsyncBarrier()
        self.client.steps.append(ModelStep(idle_response(), barrier))
        first = await activate(
            self.person.agent_id, scope=AgentTeamScope(team_id=self.first.team_id)
        )
        await barrier.wait_entered()
        second = await activate(
            self.person.agent_id, scope=AgentTeamScope(team_id=self.second.team_id)
        )
        self.assertEqual(second.status, "COALESCED")
        self.assertEqual(second.admission_id, first.admission_id)
        self.assertEqual(
            view(self.person.agent_id).scope, AgentTeamScope(team_id=self.first.team_id)
        )
        self.assertEqual(self.client.maximum_in_flight, 1)
        barrier.release()
        await self.wait_idle(first.admission_id)
        self.assertEqual(len(self.client.requests), 1)

    async def test_an_idle_owner_receives_mail_without_a_forced_reply_or_read(self):
        activate = self.require_method("activate_agent")
        deliver = self.require_method("deliver_agent_mail")
        view = self.require_method("inspect_agent_activity")
        self.client.steps.append(ModelStep(idle_response("first-idle")))
        admitted = await activate(self.person.agent_id)
        await self.wait_idle(admitted.admission_id)
        mail_request = AsyncBarrier()
        self.client.steps.append(ModelStep(idle_response("ignore-mail"), mail_request))
        receipt = await deliver(
            self.person.agent_id, message_type="personal_note", payload={"note": "hello"}
        )
        self.assertEqual(receipt.durability, "durable")
        await mail_request.wait_entered()
        prompt = model_input(self.client.requests[-1])
        self.assertIn(receipt.message_id, prompt)
        self.assertIsNone(
            next(
                item for item in self.person.agent_inbox if item["message_id"] == receipt.message_id
            )["read_at"]
        )
        admission_id = view(self.person.agent_id).admission_id
        mail_request.release()
        await self.wait_idle(admission_id)
        self.assertEqual(len(self.client.requests), 2)

    async def test_arrival_during_a_tool_wait_enters_the_immediate_next_valid_frame(self):
        activate = self.require_method("activate_agent")
        deliver = self.require_method("deliver_agent_mail")
        tool_wait = AsyncBarrier()
        next_frame = AsyncBarrier()

        async def foreground_read() -> str:
            await tool_wait.pause()
            return "safe observation"

        self.manager.register_tool(
            name="foreground_read",
            func=foreground_read,
            execution_contract=ToolExecutionContract(
                effects=("read_only",), background_allowed=False, required_scope="personal"
            ),
        )
        self.client.steps.extend(
            [
                ModelStep(LLMResponse(tool_calls=[ToolCall("read-A", "foreground_read", {})])),
                ModelStep(idle_response(), next_frame),
            ]
        )
        admitted = await activate(self.person.agent_id)
        await tool_wait.wait_entered()
        receipt = await deliver(
            self.person.agent_id, message_type="personal_note", payload={"note": "arrived"}
        )
        tool_wait.release()
        await next_frame.wait_entered()
        prompt = self.client.requests[-1].prompt
        self.assertIn(receipt.message_id, model_input(self.client.requests[-1]))
        self.assertEqual(sum(item.get("tool_call_id") == "read-A" for item in prompt), 1)
        next_frame.release()
        await self.wait_idle(admitted.admission_id)
