"""No per-membership copies, implicit stopping, or mid-batch scope changes."""

import asyncio

from ai_team_team import ATTConfig, Agent, LLMResponse, ToolCall
from ai_team_team.core.activity.contracts import AgentTeamScope
from test.test_att.test_autonomous_activity_phase0._fixtures import (
    AsyncBarrier,
    ModelStep,
    ScriptedModelClient,
)

from ._support import ActivityTestCase, call, idle


class AdmissionAndControlTests(ActivityTestCase):
    async def test_personal_scope_and_memberships_cannot_reinfer_an_existing_parent(self):
        before = self.manager.create_agent_team(self.root)
        owned = self.manager.bootstrap_agent_team(
            self.root,
            existing_members=[self.root],
            member_configs={"PeerA": {"model": "fixture"}, "PeerB": {"model": "fixture"}},
        )
        self.assertIsNone(before.parent_team)
        self.assertIsNone(owned.parent_team)
        self.assertIsNone(self.manager.find_parent_team(before))
        self.steps(idle())
        admitted = await self.manager.activate_agent(
            self.root.agent_id, scope=AgentTeamScope(team_id=owned.team_id)
        )
        await self.wait(admitted)
        self.assertIsNone(self.manager.find_parent_team(owned))
        self.assertIsNone(before.parent_team)
        self.assertIsNone(owned.parent_team)
        self.assertNotIn(owned.team_id, self.manager._team_parent_map)

    async def test_registration_is_inert_and_checkpoint_observer_cancellation_is_independent(self):
        self.assertFalse(self.client.requests)
        barrier = AsyncBarrier()
        self.client.steps.append(ModelStep(idle(), barrier))
        admitted = await self.manager.activate_agent(self.root.agent_id)
        await asyncio.wait_for(barrier.wait_entered(), 5)
        observer = asyncio.create_task(
            self.manager.wait_for_activity_checkpoint(admitted.admission_id, intent="idle")
        )
        observer.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await observer
        self.assertTrue(self.manager._activity.sessions[self.root.agent_id].active)
        barrier.release()
        await self.wait(admitted)
        self.assertEqual(self.client.maximum_in_flight, 1)

    async def test_budget_yields_fairly_without_setting_idle(self):
        await self.manager.close()
        config = ATTConfig(
            workspace_root=self.workspace.name,
            tool_calling_mode="native",
            activity={"model_requests_per_invocation": 1, "max_concurrent_activities": 1},
        )
        self.manager = self.make_manager(self.root, config=config)
        other_client = ScriptedModelClient(ModelStep(idle()))
        other = Agent("Other", "Researcher", other_client)
        self.manager.register_llm_client("other", other_client)
        self.manager.register_agent(other)
        barrier = AsyncBarrier()
        self.client.steps.extend(
            (ModelStep(LLMResponse(text="Still continuing"), barrier), ModelStep(idle()))
        )
        first = await self.manager.activate_agent(self.root.agent_id)
        await asyncio.wait_for(barrier.wait_entered(), 5)
        second = await self.manager.activate_agent(other.agent_id)
        barrier.release()
        await self.wait(first)
        await self.wait(second)
        self.assertEqual(len(self.client.requests), 2)
        invocations = self.records("activity_invocations")
        self.assertEqual(
            [row.values["agent_id"] for row in invocations],
            [self.root.agent_id, other.agent_id, self.root.agent_id],
        )
        self.assertFalse(self.records("chat_messages"))

    async def test_different_people_are_not_held_by_a_team_barrier(self):
        first_wait, second_wait = AsyncBarrier(), AsyncBarrier()
        self.client.steps.append(ModelStep(idle(), first_wait))
        second_client = ScriptedModelClient(ModelStep(idle(), second_wait))
        other = Agent("Independent", "Researcher", second_client)
        self.manager.register_llm_client("other", second_client)
        self.manager.register_agent(other)
        first = await self.manager.activate_agent(self.root.agent_id)
        second = await self.manager.activate_agent(other.agent_id)
        await asyncio.wait_for(
            asyncio.gather(first_wait.wait_entered(), second_wait.wait_entered()), 5
        )
        first_wait.release()
        second_wait.release()
        await self.wait(first)
        await self.wait(second)

    async def test_scope_control_keeps_the_entire_native_batch_in_its_original_team(self):
        person = Agent(
            "Shared",
            "Continuing researcher",
            self.client,
            system_instructions="MY_PERSONAL_MISSION",
        )
        self.manager.register_agent(person)
        first = self.manager.bootstrap_agent_team(
            self.root,
            existing_members=[person],
            member_configs={f"A{i}": {"model": "fixture"} for i in range(2)},
        )
        second = self.manager.bootstrap_agent_team(
            self.root,
            existing_members=[person],
            member_configs={f"B{i}": {"model": "fixture"} for i in range(2)},
        )
        seen = []

        def scope_probe() -> str:
            seen.append(self.manager._active_team.get().team_id)
            return seen[-1]

        self.manager.register_tool(name="scope_probe", func=scope_probe)
        self.steps(
            LLMResponse(
                tool_calls=[
                    ToolCall(
                        "switch",
                        "set_operation_scope",
                        {"scope": {"kind": "agent_team", "team_id": second.team_id}},
                    ),
                    ToolCall("probe", "scope_probe", {}),
                ]
            ),
            idle(),
        )
        admission = await self.manager.activate_agent(
            person.agent_id, scope=AgentTeamScope(team_id=first.team_id)
        )
        await self.wait(admission)
        self.assertEqual(seen, [first.team_id])
        self.assertIn(second.team_id, self.client.requests[1].system_instruction)
        self.assertTrue(
            all(
                "MY_PERSONAL_MISSION" in request.system_instruction
                for request in self.client.requests
            )
        )
        self.assertEqual(
            [row.values["scope_team_id"] for row in self.records("activity_invocations")],
            [first.team_id, second.team_id],
        )
        self.assertEqual(person.system_instructions, "MY_PERSONAL_MISSION")

    async def test_duplicate_controls_fail_before_any_control_effect(self):
        self.steps(
            LLMResponse(
                tool_calls=[
                    ToolCall("one", "set_activity_intent", {"intent": {"kind": "idle"}}),
                    ToolCall(
                        "two",
                        "set_activity_intent",
                        {"intent": {"kind": "sleep", "countdown": {"minutes": 5}}},
                    ),
                ]
            ),
            idle(),
        )
        admission = await self.manager.activate_agent(self.root.agent_id)
        await self.wait(admission)
        observations = [
            message for message in self.client.requests[1].prompt if message.get("role") == "tool"
        ]
        self.assertEqual(len(observations), 2)
        self.assertTrue(all("invalid_arguments" in message["content"] for message in observations))
        self.assertFalse(self.records("sleep_plans"))

    async def test_sleep_has_a_live_finite_safeguard_and_mail_does_not_cancel_it(self):
        self.manager.register_runtime_clock(self.clock)
        self.steps(
            call("set_activity_intent", {"intent": {"kind": "sleep", "countdown": {"minutes": 5}}}),
            idle(),
        )
        admission = await self.manager.activate_agent(self.root.agent_id)
        await self.wait(admission, "sleep")
        await self.manager.deliver_agent_mail(
            self.root.agent_id, message_type="ordinary", payload={"note": "Stored while asleep"}
        )
        self.assertEqual(len(self.client.requests), 1)
        self.clock.advance(299)
        self.assertEqual(self.manager.inspect_agent_activity(self.root.agent_id).intent, "sleep")
        self.clock.advance(1)
        await self.settle()
        # The timer is a separately scheduled owner admission; explicitly wait
        # for its committed idle rather than assume one loop yield ran it.
        async with asyncio.timeout(10):
            while len(self.client.requests) < 2:
                await asyncio.sleep(0)
        current = self.manager.inspect_agent_activity(self.root.agent_id)
        await asyncio.wait_for(
            self.manager.wait_for_activity_checkpoint(current.admission_id, intent="idle"), 10
        )
        self.assertEqual(self.root.agent_inbox[0]["read_at"], None)
        self.assertEqual(len(self.client.requests), 2)

    async def test_missing_or_nonmember_scope_fails_without_a_model_request(self):
        for team_id in ("missing", self.manager.create_agent_team(self.root).team_id):
            with self.assertRaises(PermissionError):
                await self.manager.activate_agent(
                    self.root.agent_id, scope=AgentTeamScope(team_id=team_id)
                )
        self.assertFalse(self.client.requests)
