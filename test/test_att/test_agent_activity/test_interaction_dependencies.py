"""Synchronous observers reserve identity edges and yield bounded worker capacity."""

import asyncio
from unittest.mock import patch

from ai_team_team import Agent, LLMResponse, ToolCall
from ai_team_team.core.exceptions import AgentInvocationDependencyError
from test.test_att.test_autonomous_activity_phase0._fixtures import (
    AsyncBarrier,
    ModelStep,
    ScriptedModelClient,
)

from ._support import ActivityTestCase, call, idle


class InteractionDependencyTests(ActivityTestCase):
    async def test_self_interaction_is_rejected_before_accepting_an_instruction(self):
        rejected = []

        async def ask_self() -> str:
            try:
                await self.manager.execute_agent_interaction(self.root, "Impossible nested wait")
            except AgentInvocationDependencyError as error:
                rejected.append(str(error))
                return "Dependency rejected before delivery"
            self.fail("A synchronous self dependency must not be accepted.")

        self.manager.register_tool("ask_self", func=ask_self)
        self.steps(call("ask_self"), idle())
        admission = await self.manager.activate_agent(self.root.agent_id)
        await self.wait(admission)
        await self.settle()
        self.assertEqual(len(rejected), 1)
        self.assertFalse(self.root.agent_inbox)
        self.assertFalse(self.records("agent_notifications"))
        self.assertFalse(self.manager._agent_wait_edge_counts)

    async def test_acyclic_interaction_completes_with_one_worker_slot(self):
        self.manager.config.activity.max_concurrent_activities = 1
        barrier = AsyncBarrier()
        other_client = ScriptedModelClient(
            ModelStep(LLMResponse(text="Other person's answer"), barrier), ModelStep(idle())
        )
        other = Agent("Other", "Researcher", other_client)
        self.manager.register_llm_client("other", other_client)
        self.manager.register_agent(other)
        answers = []

        async def ask_other() -> str:
            result = await self.manager.execute_agent_interaction(other, "Answer independently")
            answers.append(result.answer)
            return result.answer

        self.manager.register_tool("ask_other", func=ask_other)
        self.steps(call("ask_other"), idle())
        admission = await self.manager.activate_agent(self.root.agent_id)
        try:
            await barrier.wait_entered()
            activity = self.manager._activity
            self.assertEqual(len(activity.workers), 2)
            self.assertEqual(len(activity.suspended_workers), 1)
            self.assertEqual(
                self.manager._agent_wait_edge_counts,
                {
                    (self.root.agent_id, other.agent_id): 1,
                },
            )
        finally:
            barrier.release()
        await self.wait(admission)
        await self.settle()
        self.assertEqual(answers, ["Other person's answer"])
        self.assertFalse(self.manager._agent_wait_edge_counts)
        self.assertFalse(self.manager._activity.suspended_workers)
        self.assertEqual(self.client.maximum_in_flight, 1)
        self.assertEqual(other_client.maximum_in_flight, 1)

    async def test_long_dependency_cycle_fails_closed_without_starving_acyclic_work(self):
        self.manager.config.activity.max_concurrent_activities = 1
        people = [self.root]
        clients = [self.client]
        for index in range(1, 5):
            client = ScriptedModelClient()
            agent = Agent(f"Person{index}", "Researcher", client)
            self.manager.register_llm_client(f"person{index}", client)
            self.manager.register_agent(agent)
            people.append(agent)
            clients.append(client)
        by_id = {agent.agent_id: agent for agent in people}
        rejected = []

        async def ask_person(agent_id: str) -> str:
            try:
                result = await self.manager.execute_agent_interaction(by_id[agent_id], "Reply")
                return result.answer
            except AgentInvocationDependencyError as error:
                rejected.append(str(error))
                return "Cycle rejected before source acceptance"

        self.manager.register_tool("ask_person", func=ask_person)
        for index, client in enumerate(clients):
            target = people[(index + 1) % len(people)]
            client.steps.extend(
                (
                    ModelStep(call("ask_person", {"agent_id": target.agent_id})),
                    ModelStep(LLMResponse(text=f"Answer from person {index}")),
                    ModelStep(idle()),
                )
            )
        result = await asyncio.wait_for(
            self.manager.execute_agent_interaction(self.root, "Begin the dependency chain"), 15
        )
        self.assertEqual(result.answer, "Answer from person 0")
        await self.settle()
        self.assertEqual(len(rejected), 1)
        self.assertEqual(len(self.root.agent_inbox), 1)
        self.assertTrue(all(len(agent.agent_inbox) == 1 for agent in people))
        self.assertFalse(self.manager._agent_wait_edge_counts)
        self.assertFalse(self.manager._activity.suspended_workers)
        self.assertTrue(all(not client.unexpected_requests for client in clients))

    async def test_parallel_interaction_observers_share_one_suspended_worker(self):
        self.manager.config.activity.max_concurrent_activities = 1
        people = []
        for index in range(2):
            client = ScriptedModelClient(
                ModelStep(LLMResponse(text=f"Answer {index}")), ModelStep(idle())
            )
            agent = Agent(f"Parallel{index}", "Researcher", client)
            self.manager.register_llm_client(f"parallel{index}", client)
            self.manager.register_agent(agent)
            people.append(agent)

        async def ask(index: int) -> str:
            result = await self.manager.execute_agent_interaction(people[index], "Reply")
            return result.answer

        self.manager.register_tool("ask", func=ask)
        self.steps(
            LLMResponse(
                tool_calls=[
                    ToolCall("one", "ask", {"index": 0}),
                    ToolCall("two", "ask", {"index": 1}),
                ]
            ),
            idle(),
        )
        admission = await self.manager.activate_agent(self.root.agent_id)
        await self.wait(admission)
        await self.settle()
        observations = [item["content"] for item in self.root.messages if item["role"] == "tool"]
        self.assertIn("[success] Answer 0", observations)
        self.assertIn("[success] Answer 1", observations)
        self.assertFalse(self.manager._activity.suspended_workers)
        self.assertFalse(self.manager._agent_wait_edge_counts)

    async def test_cancelling_a_nested_observer_does_not_wait_for_downstream_capacity(self):
        self.manager.config.activity.max_concurrent_activities = 1
        barrier = AsyncBarrier()
        client = ScriptedModelClient(
            ModelStep(LLMResponse(text="Independent answer"), barrier), ModelStep(idle())
        )
        other = Agent("Independent", "Researcher", client)
        self.manager.register_llm_client("independent", client)
        self.manager.register_agent(other)
        tool_tasks = []

        async def ask_other() -> str:
            tool_tasks.append(asyncio.current_task())
            result = await self.manager.execute_agent_interaction(other, "Continue independently")
            return result.answer

        self.manager.register_tool("ask_other", func=ask_other)
        self.steps(call("ask_other"))
        admission = await self.manager.activate_agent(self.root.agent_id)
        try:
            await barrier.wait_entered()
            release_waiting = asyncio.Event()
            original_acquire = self.manager._runtime_gate.acquire

            async def acquire():
                if asyncio.current_task().get_name() == "att-dependency-release":
                    release_waiting.set()
                return await original_acquire()

            with patch.object(self.manager._runtime_gate, "acquire", acquire):
                async with self.manager._runtime_gate:
                    tool_tasks[0].cancel()
                    await asyncio.wait_for(release_waiting.wait(), 5)
                    # A second cancellation cannot abandon the accepted local
                    # dependency cleanup while it waits for the runtime gate.
                    tool_tasks[0].cancel()
            with self.assertRaises(asyncio.CancelledError):
                await self.wait(admission)
            self.assertFalse(self.root.lock.locked())
            self.assertFalse(self.manager._agent_wait_edge_counts)
            self.assertEqual(barrier.cancellations, 0)
            await asyncio.gather(
                self.manager._activity.sessions[self.root.agent_id].worker, return_exceptions=True
            )
            async with asyncio.timeout(5):
                while (
                    self.manager._activity.sessions[self.root.agent_id].worker
                    in self.manager._activity.workers
                ):
                    await asyncio.sleep(0)
        finally:
            barrier.release()
        await self.settle()
        self.assertEqual(self.manager.inspect_agent_activity(other.agent_id).intent, "idle")
        self.assertFalse(self.manager._activity.suspended_workers)
