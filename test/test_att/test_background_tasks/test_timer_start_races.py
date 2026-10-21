"""Timer startup order cannot extend admitted execution or health deadlines."""

import asyncio
from unittest.mock import patch

from ai_team_team.core.activity.contracts import BackgroundTaskHandle
from test.test_att.test_agent_activity._support import call, idle
from test.test_att.test_autonomous_activity_phase0._fixtures import AsyncBarrier, ModelStep

from ._support import BackgroundTestCase, contract
from ._timer_support import TimerStartGate, wait_registered


class DetachmentTimerStartTests(BackgroundTestCase):
    async def foreground(self):
        self.manager.register_runtime_clock(self.clock)
        release = asyncio.Event()
        calls = []

        async def operation() -> str:
            calls.append(True)
            await release.wait()
            return "ORIGINAL_EXECUTION_RESULT"

        self.addCleanup(release.set)
        self.manager.register_tool("operation", func=operation,
            execution_contract=contract(cancellation="cooperative"))
        boundary = AsyncBarrier()
        self.addCleanup(boundary.release)
        self.steps(call("operation", call_id="delayed-clock"))
        self.client.steps.append(ModelStep(idle(), boundary))
        admitted = await self.manager.activate_agent(self.root.agent_id)
        return admitted, boundary, release, calls

    def observation(self):
        observations = [message for message in self.client.requests[-1].prompt
            if message.get("role") == "tool" and message.get("tool_call_id") == "delayed-clock"]
        self.assertEqual(len(observations), 1)
        return observations[0]

    async def test_deadline_passed_before_timer_start_still_detaches_the_original_execution(self):
        gate = TimerStartGate()
        self.addCleanup(gate.released.set)
        with patch("ai_team_team.core.manager.executions.dispatch.wait_until", gate):
            admitted, boundary, release, calls = await self.foreground()
            await asyncio.wait_for(gate.entered.wait(), 5)
            self.assertEqual(gate.deadline, 120)
            job = next(job for job in self.manager._executions.jobs.values() if job.tool.name == "operation")
            self.clock.advance(121)
            gate.released.set()
            await boundary.wait_entered()
            handle = BackgroundTaskHandle.model_validate_json(self.observation()["content"])
            self.assertEqual(handle.execution_id, job.execution_id)
            self.assertEqual(job.attempts, 1)
            self.assertEqual(job.started_monotonic, 0)
            self.assertFalse(job.finished.is_set())
            self.assertFalse(job.cancellation_requested)
            self.assertEqual(calls, [True])
            release.set()
            await self.finish(handle)
            boundary.release()
            await self.wait(admitted)

    async def test_completion_wins_without_an_extra_handle_when_the_timer_has_not_started(self):
        gate = TimerStartGate()
        self.addCleanup(gate.released.set)
        with patch("ai_team_team.core.manager.executions.dispatch.wait_until", gate):
            admitted, boundary, release, calls = await self.foreground()
            await asyncio.wait_for(gate.entered.wait(), 5)
            self.clock.advance(120)
            release.set()
            await boundary.wait_entered()
            observation = self.observation()
            self.assertIn("ORIGINAL_EXECUTION_RESULT", observation["content"])
            self.assertNotIn('"status":"BACKGROUND"', observation["content"])
            await asyncio.wait_for(gate.finished.wait(), 5)
            await asyncio.gather(gate.task, return_exceptions=True)
            self.assertTrue(gate.task.cancelled())
            self.assertEqual(calls, [True])
            row = next(row for row in self.records("executions") if row.values["tool_name"] == "operation")
            self.assertEqual(row.values["visibility"], "foreground")
            self.assertEqual(row.values["status"], "completed")
            boundary.release()
            await self.wait(admitted)

    async def test_cancelled_observer_cleans_up_a_timer_that_has_not_started(self):
        gate = TimerStartGate()
        self.addCleanup(gate.released.set)
        with patch("ai_team_team.core.manager.executions.dispatch.wait_until", gate):
            admitted, _boundary, _release, calls = await self.foreground()
            await asyncio.wait_for(gate.entered.wait(), 5)
            observer = next(task for task, job in self.manager._executions.observers.items() if job.tool.name == "operation")
            observer.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await self.wait(admitted)
            await asyncio.wait_for(gate.finished.wait(), 5)
            await asyncio.gather(gate.task, return_exceptions=True)
            self.assertTrue(gate.task.cancelled())
            self.assertEqual(calls, [True])
            self.assertEqual(self.clock.pending_waits, 0)


class HealthTimerStartTests(BackgroundTestCase):
    async def operation(self, signal):
        self.manager.register_runtime_clock(self.clock)
        release = asyncio.Event()

        async def operation() -> str:
            await release.wait()
            return "done"

        self.addCleanup(release.set)
        self.manager.register_tool("operation", func=operation, execution_contract=contract(
            cancellation="cooperative", health_signals=(signal,), **{f"{signal}_timeout_seconds": 10.0}))
        return await self.start("operation"), release

    async def wait_stalled(self, signal):
        async with asyncio.timeout(5):
            while not any(row.values["health"] == "stalled" and row.values["evidence_kind"] == signal
                          for row in self.records("execution_observations")):
                await asyncio.sleep(0)

    async def delayed_timeout(self, signal):
        gate = TimerStartGate()
        self.addCleanup(gate.released.set)
        with patch("ai_team_team.core.manager.executions.health.wait_until", gate):
            handle, release = await self.operation(signal)
            await asyncio.wait_for(gate.entered.wait(), 5)
            self.assertEqual(gate.deadline, 10)
            self.clock.advance(10)
            gate.released.set()
            await self.wait_stalled(signal)
            observations = self.records("execution_observations")
            self.assertEqual(observations[0].values["observed_at"], 10)
            self.assertEqual(self.manager.inspect_background_task(handle.execution_id, actor=self.root).health_state, "stalled")
            release.set()
            await self.finish(handle)

    async def test_delayed_heartbeat_timer_reports_at_its_original_deadline(self):
        await self.delayed_timeout("heartbeat")

    async def test_delayed_progress_timer_reports_at_its_original_deadline(self):
        await self.delayed_timeout("progress")

    async def test_fresh_sample_cancels_a_delayed_timer_and_keeps_the_refreshed_deadline(self):
        gate = TimerStartGate()
        self.addCleanup(gate.released.set)
        with patch("ai_team_team.core.manager.executions.health.wait_until", gate):
            handle, release = await self.operation("heartbeat")
            await asyncio.wait_for(gate.entered.wait(), 5)
            self.clock.advance(5)
            await self.manager.report_execution_health(handle.execution_id, "healthy", "heartbeat", {"sequence": 1})
            await asyncio.wait_for(gate.finished.wait(), 5)
            await asyncio.gather(gate.task, return_exceptions=True)
            self.assertTrue(gate.task.cancelled())
            await wait_registered(self.clock, 15)
            self.assertEqual([row.values["health"] for row in self.records("execution_observations")], ["healthy"])
            self.clock.advance(10)
            await self.wait_stalled("heartbeat")
            self.assertEqual([row.values["observed_at"] for row in self.records("execution_observations")], [5, 15])
            release.set()
            await self.finish(handle)

    async def test_cancelled_execution_cleans_up_a_delayed_health_timer(self):
        gate = TimerStartGate()
        self.addCleanup(gate.released.set)
        with patch("ai_team_team.core.manager.executions.health.wait_until", gate):
            handle, _release = await self.operation("heartbeat")
            await asyncio.wait_for(gate.entered.wait(), 5)
            result = await self.manager.cancel_background_task(handle.execution_id, actor=self.root)
            self.assertIn(result.status, {"CANCELLED", "UNCONFIRMED"})
            await self.finish(handle)
            view = self.manager.inspect_background_task(handle.execution_id, actor=self.root)
            self.assertEqual(view.execution_state, "cancelled")
            self.assertFalse(view.outcome_unconfirmed)
            self.assertEqual(self.records("execution_controls")[0].values["acknowledgement"], "acknowledged")
            await asyncio.wait_for(gate.finished.wait(), 5)
            await asyncio.gather(gate.task, return_exceptions=True)
            self.assertTrue(gate.task.cancelled())
            self.assertEqual(self.clock.pending_waits, 0)
