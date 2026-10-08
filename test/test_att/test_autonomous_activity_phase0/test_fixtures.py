"""Prove that adversarial controls are deterministic and cancellation-aware."""

import asyncio
import unittest

from ai_team_team import LLMResponse
from ai_team_team.tool import Tool

from test.test_att.test_autonomous_activity_phase0._fixtures import (
    AsyncBarrier,
    ControlledCommitter,
    ControlledExecutor,
    CountdownCheckpoint,
    InjectedPublicationFailure,
    LogicalClock,
    ModelStep,
    PUBLICATION_POINTS,
    PublicationFaults,
    ScriptedModelClient,
    cancel_and_drain,
)


class TestLogicalClock(unittest.IsolatedAsyncioTestCase):
    async def test_waiters_advance_at_exact_boundaries_without_real_delays(self):
        clock = LogicalClock()
        self.addCleanup(clock.close)
        first = asyncio.create_task(clock.sleep(120))
        second = asyncio.create_task(clock.sleep(120))
        self.addAsyncCleanup(cancel_and_drain, first, second)
        await asyncio.sleep(0)
        self.assertEqual(clock.pending_waits, 2)
        clock.advance(119)
        await asyncio.sleep(0)
        self.assertFalse(first.done())
        clock.advance(1)
        await asyncio.gather(first, second)
        self.assertEqual(clock.monotonic(), 120)
        self.assertEqual(clock.pending_waits, 0)

    async def test_cancelled_timer_is_removed_and_invalid_time_is_rejected(self):
        clock = LogicalClock()
        task = asyncio.create_task(clock.sleep(10))
        await asyncio.sleep(0)
        await cancel_and_drain(task)
        self.assertEqual(clock.pending_waits, 0)
        for invalid in (True, -1, float("inf"), float("nan"), "120"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                clock.advance(invalid)
            with self.subTest(anchor=invalid), self.assertRaises(ValueError):
                CountdownCheckpoint(clock, 10, anchor=invalid)

    async def test_finite_clock_arithmetic_rejects_overflow_without_partial_advance(self):
        clock = LogicalClock(wall_time=1e308, monotonic=1e308)
        with self.assertRaises(ValueError):
            clock.advance(1e308)
        self.assertEqual(clock.monotonic(), 1e308)
        self.assertEqual(clock.wall_time(), 1e308)
        with self.assertRaises(ValueError):
            await clock.sleep(1e308)
        self.assertEqual(clock.pending_waits, 0)
        with self.assertRaises(ValueError):
            CountdownCheckpoint(clock, 1e308)
        with self.assertRaises(ValueError):
            clock.advance(10**1000)

    def test_countdown_uses_restore_start_and_excludes_offline_time(self):
        clock = LogicalClock(wall_time=1000)
        checkpoint = CountdownCheckpoint(clock, 7200)
        clock.advance(100)
        saved = checkpoint.remaining()
        restored = clock.restarted(offline_seconds=21600)
        restoration_start = restored.monotonic()
        restored.advance(50)
        countdown = CountdownCheckpoint(restored, saved, anchor=restoration_start)
        self.assertEqual(countdown.remaining(), 7050)
        self.assertEqual(restored.wall_time(), 22750)


class TestModelAndExecutorFixtures(unittest.IsolatedAsyncioTestCase):
    async def test_model_captures_a_snapshot_and_real_tool_objects(self):
        barrier = AsyncBarrier()
        client = ScriptedModelClient(ModelStep(LLMResponse(text="private answer"), barrier))

        async def read_note() -> str:
            return "note"

        tool = Tool(read_note)
        prompt = [{"role": "user", "content": "before"}]
        call = asyncio.create_task(client.generate(prompt, tools=[tool]))
        self.addAsyncCleanup(cancel_and_drain, call)
        await barrier.wait_entered()
        prompt[0]["content"] = "after"
        self.assertEqual(client.requests[0].prompt[0]["content"], "before")
        self.assertIs(client.requests[0].tools[0], tool)
        self.assertEqual(client.in_flight, 1)
        barrier.release()
        self.assertEqual((await call).text, "private answer")
        self.assertEqual(client.in_flight, 0)
        with self.assertRaises(AssertionError):
            await client.generate([])
        self.assertEqual(len(client.requests), 2)
        self.assertEqual(client.requests[-1].prompt, [])
        self.assertEqual(client.unexpected_requests, 1)

    async def test_model_rejects_nonprotocol_keywords_before_consuming_a_step(self):
        client = ScriptedModelClient(ModelStep("available"))
        with self.assertRaises(TypeError):
            await client.generate([], unknown_generation_option=True)
        self.assertEqual(client.requests, [])
        self.assertEqual(len(client.steps), 1)
        self.assertEqual((await client.generate([])).text, "available")

    async def test_model_failure_and_cancellation_are_not_success_responses(self):
        barrier = AsyncBarrier()
        client = ScriptedModelClient(
            ModelStep(ConnectionError("offline")), ModelStep("never returned", barrier)
        )
        with self.assertRaises(ConnectionError):
            await client.generate([])
        call = asyncio.create_task(client.generate([]))
        await barrier.wait_entered()
        call.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await call
        self.assertEqual(client.in_flight, 0)
        self.assertEqual(barrier.cancellations, 1)

    async def test_cancellation_request_does_not_win_against_completed_result(self):
        executor = ControlledExecutor()
        self.addCleanup(executor.close)
        call = asyncio.create_task(executor())
        self.addAsyncCleanup(cancel_and_drain, call)
        await executor.started.wait()
        executor.request_cancellation()
        self.assertIsNone(executor.outcome)
        self.assertTrue(executor.complete("result"))
        self.assertFalse(executor.acknowledge_cancellation())
        self.assertEqual((await call).state, "completed")
        self.assertEqual(executor.calls, 1)
        self.assertEqual(executor.side_effects, 1)

    async def test_cancellation_before_dispatch_never_performs_the_effect(self):
        barrier = AsyncBarrier()
        executor = ControlledExecutor(dispatch_barrier=barrier)
        self.addCleanup(executor.close)
        call = asyncio.create_task(executor())
        self.addAsyncCleanup(cancel_and_drain, call)
        await barrier.wait_entered()
        with self.assertRaisesRegex(AssertionError, "actual executor dispatch"):
            executor.complete("fabricated completion")
        self.assertIsNone(executor.outcome)
        executor.request_cancellation()
        self.assertTrue(executor.acknowledge_cancellation())
        barrier.release()
        self.assertEqual((await call).state, "cancelled")
        self.assertEqual(executor.side_effects, 0)

    async def test_cancelling_the_local_wait_does_not_acknowledge_remote_stop(self):
        executor = ControlledExecutor()
        self.addCleanup(executor.close)
        call = asyncio.create_task(executor())
        await executor.started.wait()
        await cancel_and_drain(call)
        self.assertIsNone(executor.outcome)
        self.assertTrue(executor.complete("late result"))
        self.assertEqual(executor.outcome.state, "completed")


class TestCommitAndPublicationFixtures(unittest.IsolatedAsyncioTestCase):
    async def test_commit_captures_immutable_input_and_waits_for_exact_receipt(self):
        committer = ControlledCommitter()
        self.addCleanup(committer.close)
        delta = {"notifications": ["notice-A"]}
        call = asyncio.create_task(committer.commit("operation-A", delta))
        self.addAsyncCleanup(cancel_and_drain, call)
        attempt = await committer.next_attempt()
        delta["notifications"].append("notice-B")
        self.assertEqual(attempt.captured_delta, {"notifications": ["notice-A"]})
        self.assertFalse(call.done())
        attempt.succeed(7)
        self.assertEqual((await call).state_version, 7)

    async def test_commit_failure_propagates_without_fabricated_receipt(self):
        committer = ControlledCommitter()
        self.addCleanup(committer.close)
        call = asyncio.create_task(committer.commit("operation-A", {}))
        attempt = await committer.next_attempt()
        attempt.fail(OSError("disk failed"))
        with self.assertRaises(OSError):
            await call

    async def test_cancelled_caller_does_not_decide_an_accepted_commit(self):
        committer = ControlledCommitter()
        self.addCleanup(committer.close)
        call = asyncio.create_task(committer.commit("operation-A", {}))
        attempt = await committer.next_attempt()
        await cancel_and_drain(call)
        self.assertFalse(attempt.result.done())
        attempt.succeed(8)
        self.assertEqual(attempt.result.result().state_version, 8)

    def test_every_publication_boundary_can_fail_by_name(self):
        for boundary in PUBLICATION_POINTS:
            with self.subTest(boundary=boundary):
                faults = PublicationFaults(boundary)
                for point in PUBLICATION_POINTS:
                    if point == boundary:
                        with self.assertRaisesRegex(InjectedPublicationFailure, boundary):
                            faults.hit(point)
                        break
                    faults.hit(point)
                self.assertEqual(faults.visited[-1], boundary)
        with self.assertRaises(ValueError):
            PublicationFaults("unknown")
