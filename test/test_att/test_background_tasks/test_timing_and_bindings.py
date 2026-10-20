"""Queue time is not execution time; retries and backoff do not restart it."""

import asyncio

from ai_team_team import LLMResponse, RetryableToolError, ToolCall, ToolBusinessError
from test.test_att.test_agent_activity._support import ActivityTestCase, idle
from test.test_att.test_autonomous_activity_phase0._fixtures import AsyncBarrier, ModelStep

from ._support import BackgroundTestCase, contract


class TimingTests(ActivityTestCase):
    async def test_backoff_is_included_without_restarting_the_executor_identity(self):
        self.manager.register_runtime_clock(self.clock)
        self.manager.config.tool_execution_retry_policy = "typed_transient"
        self.manager.config.tool_execution_retry_backoff_factor = 200.0
        attempted = asyncio.Event()
        calls = []

        async def operation() -> str:
            calls.append(True)
            attempted.set()
            raise RetryableToolError("Recoverable provider failure")

        self.manager.register_tool("operation", func=operation, execution_contract=contract())
        handle_boundary = AsyncBarrier()
        self.client.steps.extend((ModelStep(LLMResponse(tool_calls=[ToolCall("operation", "operation", {})])), ModelStep(idle(), handle_boundary)))
        admitted = await self.manager.activate_agent(self.root.agent_id)
        await asyncio.wait_for(attempted.wait(), 5)
        self.clock.advance(120)
        await handle_boundary.wait_entered()
        executions = [row for row in self.records("executions") if row.values["tool_name"] == "operation"]
        self.assertEqual(len(executions), 1)
        self.assertEqual(len(self.records("execution_attempts")), 1)
        self.assertEqual(calls, [True])
        handle_boundary.release()
        await self.wait(admitted)


class BindingTests(BackgroundTestCase):
    async def test_registered_provider_binding_confirms_its_real_operation(self):
        class Provider:
            def __init__(self):
                self.calls = []

            async def execute(self, call):
                self.calls.append(call.execution_id)
                self.assert_scope = call.scope.kind
                await call.report_health("healthy", "provider", {"provider_status": "running"})
                return {"result": "confirmed provider operation"}

            async def cancel(self, execution_id):
                return True

        binding = Provider()
        self.manager.register_executor("provider", binding)

        async def operation() -> str:
            raise AssertionError("The registered binding owns dispatch.")

        self.manager.register_tool("operation", func=operation, executor="provider",
            execution_contract=contract(cancellation="provider", health_signals=("provider",)))
        handle = await self.start("operation")
        await self.finish(handle)
        self.assertEqual(binding.calls, [handle.execution_id])
        self.assertEqual(self.manager.inspect_background_task(handle.execution_id, actor=self.root).execution_state, "completed")

    def test_nonexistent_binding_and_false_cancellation_capability_are_rejected(self):
        async def operation() -> str:
            return "never"
        with self.assertRaises(ValueError):
            self.manager.register_tool("missing", func=operation, executor="missing", execution_contract=contract())
        with self.assertRaises(ValueError):
            self.manager.register_tool("unsupported", func=operation, execution_contract=contract(cancellation="provider"))
        with self.assertRaises(ValueError):
            self.manager.register_tool("thread", func=lambda: "never", execution_contract=contract(cancellation="cooperative"))

    async def test_provider_stop_acknowledgement_does_not_need_a_fake_thread_cancel(self):
        started = asyncio.Event()

        class Provider:
            async def execute(self, call):
                started.set()
                await asyncio.Event().wait()

            async def cancel(self, execution_id):
                return True

        self.manager.register_executor("provider", Provider())
        self.manager.register_tool("operation", func=lambda: "unused", executor="provider",
            execution_contract=contract(cancellation="provider"))
        handle = await self.start("operation")
        await asyncio.wait_for(started.wait(), 5)
        result = await self.manager.cancel_background_task(handle.execution_id, actor=self.root)
        self.assertEqual(result.status, "CANCELLED")
