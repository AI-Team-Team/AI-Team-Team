"""Fairness and scope checkpoints are not personal answers."""

import asyncio

from ai_team_team import LLMResponse
from test.test_att.test_autonomous_activity_phase0._fixtures import AsyncBarrier, ModelStep

from ._support import ActivityTestCase, call, idle


class InteractionAnswerBoundaryTests(ActivityTestCase):
    async def test_technical_yields_do_not_complete_a_tool_only_interaction(self):
        def noop() -> str:
            return "Tool observation, not the personal answer"

        self.manager.register_tool("noop", func=noop)
        for native in (True, False):
            for budget in ("model_requests_per_invocation", "tool_batches_per_invocation"):
                with self.subTest(native=native, budget=budget):
                    self.manager.config.tool_calling_mode = "native" if native else "text_react"
                    config = self.manager.config.activity
                    config.model_requests_per_invocation = 5
                    config.tool_batches_per_invocation = 5
                    setattr(config, budget, 1)
                    barrier = AsyncBarrier()
                    action = call("noop") if native else LLMResponse(text="Action: noop()")
                    self.client.steps.extend(
                        (
                            ModelStep(action),
                            ModelStep(LLMResponse(text="ACTUAL_PERSONAL_ANSWER"), barrier),
                            ModelStep(idle(native=native)),
                        )
                    )
                    observer = asyncio.create_task(
                        self.manager.execute_agent_interaction(
                            self.root, "Answer after inspecting the tool result"
                        )
                    )
                    try:
                        await barrier.wait_entered()
                        self.assertFalse(observer.done(), "A technical yield is not an answer.")
                        self.assertEqual(
                            self.manager.inspect_agent_activity(self.root.agent_id).intent,
                            "continuing",
                        )
                    finally:
                        barrier.release()
                    result = await asyncio.wait_for(observer, 10)
                    self.assertEqual(result.answer, "ACTUAL_PERSONAL_ANSWER")
                    await self.settle()

    async def test_scope_checkpoint_keeps_the_answer_observer_waiting(self):
        team = self.manager.bootstrap_agent_team(
            self.root,
            existing_members=[self.root],
            member_configs={"PeerA": {"model": "fixture"}, "PeerB": {"model": "fixture"}},
        )
        barrier = AsyncBarrier()
        self.client.steps.extend(
            (
                ModelStep(
                    call(
                        "set_operation_scope",
                        {"scope": {"kind": "agent_team", "team_id": team.team_id}},
                    )
                ),
                ModelStep(LLMResponse(text="Answer in the selected scope"), barrier),
                ModelStep(idle()),
            )
        )
        observer = asyncio.create_task(self.manager.execute_agent_interaction(self.root, "Reply"))
        try:
            await barrier.wait_entered()
            self.assertFalse(observer.done())
            self.assertEqual(
                self.manager.inspect_agent_activity(self.root.agent_id).scope.team_id, team.team_id
            )
        finally:
            barrier.release()
        result = await asyncio.wait_for(observer, 10)
        self.assertEqual(result.answer, "Answer in the selected scope")
        self.assertEqual(result.team_id, team.team_id)
        await self.settle()

    async def test_explicit_stop_is_still_an_observable_boundary_without_an_answer(self):
        self.steps(idle())
        result = await asyncio.wait_for(
            self.manager.execute_agent_interaction(self.root, "You may deliberately stop"), 10
        )
        self.assertEqual(result.answer, "")
        self.assertEqual(self.manager.inspect_agent_activity(self.root.agent_id).intent, "idle")

    async def test_unpresented_instruction_observer_follows_the_next_admission(self):
        barrier = AsyncBarrier()
        self.client.steps.extend(
            (
                ModelStep(idle(), barrier),
                ModelStep(LLMResponse(text="Answer to the later instruction")),
                ModelStep(idle()),
            )
        )
        await self.manager.activate_agent(self.root.agent_id)
        await barrier.wait_entered()
        observer = asyncio.create_task(
            self.manager.execute_agent_interaction(
                self.root, "An instruction arriving after the old frame was frozen"
            )
        )
        try:
            async with asyncio.timeout(5):
                while not self.manager._activity.sessions[self.root.agent_id].interaction_waiters:
                    await asyncio.sleep(0)
            barrier.release()
            result = await asyncio.wait_for(observer, 10)
            self.assertEqual(result.answer, "Answer to the later instruction")
            await self.settle()
        finally:
            barrier.release()
            if not observer.done():
                observer.cancel()
            await asyncio.gather(observer, return_exceptions=True)
        self.assertEqual(len(self.records("activity_admissions")), 2)

    async def test_close_releases_an_observer_whose_instruction_was_not_yet_presented(self):
        self.manager.register_runtime_clock(self.clock)
        barrier = AsyncBarrier()
        self.client.steps.append(
            ModelStep(
                call(
                    "set_activity_intent",
                    {"intent": {"kind": "sleep", "countdown": {"minutes": 5}}},
                ),
                barrier,
            )
        )
        admission = await self.manager.activate_agent(self.root.agent_id)
        await barrier.wait_entered()
        observer = asyncio.create_task(
            self.manager.execute_agent_interaction(
                self.root, "An ordinary instruction pending during deliberate sleep"
            )
        )
        try:
            async with asyncio.timeout(5):
                while not self.manager._activity.sessions[self.root.agent_id].interaction_waiters:
                    await asyncio.sleep(0)
            barrier.release()
            await self.wait(admission, "sleep")
            self.assertFalse(observer.done())
            await self.manager.close()
            with self.assertRaises(RuntimeError):
                await observer
        finally:
            barrier.release()
            if not observer.done():
                observer.cancel()
            await asyncio.gather(observer, return_exceptions=True)
