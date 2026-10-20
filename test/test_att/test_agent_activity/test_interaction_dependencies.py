"""Synchronous observers reserve identity edges and yield bounded worker capacity."""

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch

from ai_team_team import Agent, LLMResponse, ToolCall
from ai_team_team.core.exceptions import AgentInvocationDependencyError
from test.test_att.test_autonomous_activity_phase0._fixtures import (
    AsyncBarrier,
    ModelStep,
    ScriptedModelClient,
)

from ._support import ActivityTestCase, call, idle, personal_control_contract


DEPENDENCY_CHAIN_TIMEOUT_SECONDS = 60


class InteractionDependencyTests(ActivityTestCase):
    @staticmethod
    def _task_state(task):
        if task is None:
            return None
        frames = task.get_stack(limit=1)
        location = None
        if frames:
            frame = frames[0]
            location = f"{Path(frame.f_code.co_filename).name}:{frame.f_lineno}:{frame.f_code.co_name}"
        return {
            "done": task.done(),
            "cancelled": task.cancelled(),
            "cancelling": task.cancelling(),
            "location": location,
        }

    def _dependency_state(self):
        activity = self.manager._activity
        return {
            "workers": len(activity.workers),
            "ready": activity.ready.qsize(),
            "dispatch_tasks": len(activity.dispatch_tasks),
            "tool_tasks": len(activity.tool_tasks),
            "provider_tasks": len(activity.models.tasks),
            "admitted_model_requests": activity.models.admitted_requests,
            "scheduler": self._task_state(activity.scheduler),
            "locks": {
                "runtime": self.manager._runtime_gate.locked(),
                "activity": activity.lock.locked(),
                "records": self.manager._records.lock.locked(),
            },
            "wait_edges": [
                {"source_agent_id": source, "target_agent_id": target, "count": count}
                for (source, target), count in sorted(self.manager._agent_wait_edge_counts.items())
            ],
            "suspended_workers": [
                {
                    "agent_id": resume.session.agent_id,
                    "waits": resume.waits,
                    "queued": resume.queued,
                    "resume_done": resume.future.done(),
                    "worker": self._task_state(resume.worker),
                }
                for resume in sorted(
                    activity.suspended_workers.values(), key=lambda item: item.session.agent_id
                )
            ],
            "sessions": {
                agent_id: {
                    "active": session.active,
                    "running": session.running,
                    "queued": session.queued,
                    "intent": session.intent,
                    "availability": session.availability,
                    "model_calls": len(self.manager._agents_by_id[agent_id].llm_client.requests),
                    "worker": self._task_state(getattr(session, "worker", None)),
                }
                for agent_id, session in sorted(activity.sessions.items())
            },
        }

    @asynccontextmanager
    async def _dependency_watchdog(self, *, timeout=DEPENDENCY_CHAIN_TIMEOUT_SECONDS):
        deadline = asyncio.timeout(timeout)
        try:
            async with deadline:
                yield
        except TimeoutError:
            if not deadline.expired():
                raise
            # Capture IDs, counts, and source locations, never prompts or tool payloads.
            self.fail(
                f"The dependency workload did not settle within {timeout:g} seconds. "
                f"Runtime state: {json.dumps(self._dependency_state(), sort_keys=True)}"
            )

    async def test_self_interaction_is_rejected_before_accepting_an_instruction(self):
        rejected = []

        async def ask_self() -> str:
            try:
                await self.manager.execute_agent_interaction(self.root, "Impossible nested wait")
            except AgentInvocationDependencyError as error:
                rejected.append(str(error))
                return "Dependency rejected before delivery"
            self.fail("A synchronous self dependency must not be accepted.")

        self.manager.register_tool("ask_self", func=ask_self, execution_contract=personal_control_contract())
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

        self.manager.register_tool("ask_other", func=ask_other, execution_contract=personal_control_contract())
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

        self.manager.register_tool("ask_person", func=ask_person, execution_contract=personal_control_contract())
        for index, client in enumerate(clients):
            target = people[(index + 1) % len(people)]
            client.steps.extend(
                (
                    ModelStep(call("ask_person", {"agent_id": target.agent_id})),
                    ModelStep(LLMResponse(text=f"Answer from person {index}")),
                    ModelStep(idle()),
                )
            )
        # One cross-platform watchdog covers the serialized chain and its final idle commits.
        async with self._dependency_watchdog():
            result = await self.manager.execute_agent_interaction(
                self.root, "Begin the dependency chain"
            )
            self.assertEqual(result.answer, "Answer from person 0")
            await self.settle(timeout=DEPENDENCY_CHAIN_TIMEOUT_SECONDS)
        self.assertEqual(len(rejected), 1)
        self.assertEqual(len(self.root.agent_inbox), 1)
        self.assertTrue(all(len(agent.agent_inbox) == 1 for agent in people))
        self.assertFalse(self.manager._agent_wait_edge_counts)
        self.assertFalse(self.manager._activity.suspended_workers)
        self.assertTrue(all(not client.unexpected_requests for client in clients))

    async def test_dependency_watchdog_reports_metadata_without_private_content(self):
        private_content = "Private diagnostic sentinel must never appear in the failure report."
        self.manager.config.activity.max_concurrent_activities = 1
        barrier = AsyncBarrier()
        client = ScriptedModelClient(
            ModelStep(LLMResponse(text=private_content), barrier), ModelStep(idle())
        )
        other = Agent("PrivateSource", "Researcher", client)
        self.manager.register_llm_client("private-source", client)
        self.manager.register_agent(other)

        async def ask_private_source() -> str:
            result = await self.manager.execute_agent_interaction(other, private_content)
            return result.answer

        self.manager.register_tool("ask_private_source", func=ask_private_source, execution_contract=personal_control_contract())
        self.steps(call("ask_private_source"), LLMResponse(text="Complete"), idle())
        observer = asyncio.create_task(
            self.manager.execute_agent_interaction(self.root, private_content)
        )
        try:
            await asyncio.wait_for(barrier.entered.wait(), DEPENDENCY_CHAIN_TIMEOUT_SECONDS)
            with self.assertRaises(self.failureException) as raised:
                async with self._dependency_watchdog(timeout=0):
                    await asyncio.shield(observer)
            message = str(raised.exception)
            self.assertIn("did not settle within 0 seconds", message)
            self.assertNotIn(private_content, message)
            state = json.loads(message.split("Runtime state: ", 1)[1])
            self.assertEqual(state["provider_tasks"], 1)
            self.assertEqual(state["admitted_model_requests"], 1)
            self.assertEqual(
                state["wait_edges"],
                [{"source_agent_id": self.root.agent_id, "target_agent_id": other.agent_id, "count": 1}],
            )
            self.assertEqual(len(state["suspended_workers"]), 1)
            self.assertEqual(state["suspended_workers"][0]["agent_id"], self.root.agent_id)
            self.assertEqual(state["suspended_workers"][0]["waits"], 1)
            session = state["sessions"][self.root.agent_id]
            self.assertTrue(session["running"])
            self.assertEqual(session["model_calls"], 1)
            self.assertIsNotNone(session["worker"]["location"])
            self.assertFalse(observer.done())
        finally:
            barrier.release()
            await asyncio.wait_for(observer, DEPENDENCY_CHAIN_TIMEOUT_SECONDS)
            await self.settle(timeout=DEPENDENCY_CHAIN_TIMEOUT_SECONDS)

    async def test_dependency_watchdog_preserves_operation_timeouts(self):
        failure = TimeoutError("The observed operation itself timed out.")
        with self.assertRaises(TimeoutError) as raised:
            async with self._dependency_watchdog():
                raise failure
        self.assertIs(raised.exception, failure)

    async def test_dependency_watchdog_preserves_cancellation(self):
        barrier = AsyncBarrier()

        async def observed():
            async with self._dependency_watchdog():
                await barrier.pause()

        task = asyncio.create_task(observed())
        try:
            await barrier.wait_entered()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

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

        self.manager.register_tool("ask", func=ask, execution_contract=personal_control_contract())
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

        self.manager.register_tool("ask_other", func=ask_other, execution_contract=personal_control_contract())
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
