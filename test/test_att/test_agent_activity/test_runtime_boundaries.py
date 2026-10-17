"""Adversarial request, execution, shutdown, and checkpoint ownership."""

import asyncio
import threading
from unittest.mock import patch

from ai_team_team import (
    ATTConfig,
    Agent,
    LLMResponse,
    RetryableToolError,
    StatePersistenceError,
    ToolCall,
)
from ai_team_team.core.config import PersonalActivityConfig
from ai_team_team.core.manager.activity.values import ModelUnavailable
from test.test_att.test_autonomous_activity_phase0._fixtures import (
    AsyncBarrier,
    ModelStep,
    ScriptedModelClient,
)

from ._support import ActivityTestCase, call, idle


async def until(predicate):
    async with asyncio.timeout(10):
        while not predicate():
            await asyncio.sleep(0)


class RuntimeBoundaryTests(ActivityTestCase):
    async def test_rejected_stop_receipt_cannot_publish_intent_or_scope(self):
        for kind in ("idle", "sleep"):
            with self.subTest(intent=kind):
                if self.manager._closed:
                    self.root = Agent(f"Stop{kind}", "Researcher", self.client)
                    self.manager = self.make_manager(self.root)
                team = self.manager.bootstrap_agent_team(
                    self.root,
                    existing_members=[self.root],
                    member_configs={"Peer1": {"model": "fixture"}, "Peer2": {"model": "fixture"}},
                )
                original = self.manager._records.commit
                observed, rejected = [], False
                observed_scopes = []

                async def reject_stop(records, **kwargs):
                    nonlocal rejected
                    if not rejected and any(
                        row.table_name == "activity_admissions"
                        and row.values["disposition"] == "completed"
                        for row in records
                    ):
                        rejected = True
                        observed.append(
                            self.manager.inspect_agent_activity(self.root.agent_id).intent
                        )
                        observed_scopes.append(self.root.last_context["activity_scope"])
                        raise StatePersistenceError("Synthetic rejected stop checkpoint")
                    return await original(records, **kwargs)

                intent = {"kind": kind}
                if kind == "sleep":
                    intent["countdown"] = {"minutes": 5}
                self.steps(
                    LLMResponse(
                        tool_calls=[
                            ToolCall("stop", "set_activity_intent", {"intent": intent}),
                            ToolCall(
                                "scope",
                                "set_operation_scope",
                                {"scope": {"kind": "agent_team", "team_id": team.team_id}},
                            ),
                        ]
                    )
                )
                with self.assertLogs(self.manager.logger, level="ERROR"):
                    with patch.object(self.manager._records, "commit", reject_stop):
                        admitted = await self.manager.activate_agent(self.root.agent_id)
                        with self.assertRaises(StatePersistenceError):
                            await self.wait(admitted)
                        with self.assertRaises(StatePersistenceError):
                            await self.manager.close()
                self.assertEqual(observed, ["continuing"])
                self.assertEqual(observed_scopes, [{"kind": "personal"}])
                self.assertEqual(
                    self.manager.inspect_agent_activity(self.root.agent_id).intent, "continuing"
                )
                self.assertEqual(self.root.last_context["activity_scope"], {"kind": "personal"})
                self.assertFalse(self.manager._activity.timers)
                self.assertFalse(
                    any(row.values["status"] == "active" for row in self.records("sleep_plans"))
                )
                self.assertEqual(
                    self.manager._records.index[
                        ("activity_admissions", (admitted.admission_id,))
                    ].values["disposition"],
                    "interrupted",
                )

    async def test_cancellation_after_an_idle_or_sleep_receipt_cannot_reopen_admission(self):
        self.manager.register_runtime_clock(self.clock)
        for kind in ("idle", "sleep"):
            with self.subTest(intent=kind):
                committed, release = asyncio.Event(), asyncio.Event()
                original = self.manager._records.commit

                async def hold_receipt(records, **kwargs):
                    receipt = await original(records, **kwargs)
                    if any(
                        row.table_name == "activity_admissions"
                        and row.values["disposition"] == "completed"
                        for row in records
                    ):
                        committed.set()
                        await release.wait()
                    return receipt

                intent = {"kind": kind}
                if kind == "sleep":
                    intent["countdown"] = {"minutes": 5}
                self.steps(call("set_activity_intent", {"intent": intent}))
                with patch.object(self.manager._records, "commit", hold_receipt):
                    admitted = await self.manager.activate_agent(self.root.agent_id)
                    await asyncio.wait_for(committed.wait(), 5)
                    worker = next(
                        task
                        for task in self.manager._activity.workers
                        if task.get_name() == f"att-person-{self.root.agent_id}"
                    )
                    worker.cancel()
                    release.set()
                    with self.assertRaises(asyncio.CancelledError):
                        await worker
                    checkpoint = await self.wait(admitted, kind)
                self.assertEqual(checkpoint.intent, kind)
                self.assertEqual(
                    self.manager._records.index[
                        ("activity_admissions", (admitted.admission_id,))
                    ].values["disposition"],
                    "completed",
                )
                self.assertFalse(self.manager._activity.fatal_errors)
                self.assertFalse(self.root.lock.locked())
        self.assertIn(self.root.agent_id, self.manager._activity.timers)

    async def test_provider_completion_after_deadline_is_fenced_even_if_timer_started_late(self):
        self.manager.register_runtime_clock(self.clock)
        self.manager.config.activity.llm.request_timeout_seconds = 1.0
        self.manager.config.activity.llm.max_retries = 0

        class Late:
            async def generate(inner, **kwargs):
                self.clock.advance(2)
                return LLMResponse(text="LATE_RESPONSE_MARKER", usage={"total_tokens": 3})

        client = Late()
        self.manager.register_llm_client("late", client)
        self.root.llm_client = client
        admitted = await self.manager.activate_agent(self.root.agent_id)
        with self.assertRaises(ModelUnavailable):
            await self.wait(admitted)
        self.assertNotIn("LATE_RESPONSE_MARKER", str(self.root.message_history))
        self.assertEqual(self.records("model_token_claims")[0].values["actual_usage"], 3)
        self.assertEqual(self.records("model_requests")[0].values["outcome"], "failed")

    async def test_failed_response_checkpoint_cannot_start_a_tool_and_close_reports_it(self):
        invoked = []

        def side_effect() -> str:
            invoked.append(True)
            return "executed"

        self.manager.register_tool("side_effect", func=side_effect)
        self.steps(call("side_effect"))
        original = self.manager._records.commit

        async def fail_window(records, **kwargs):
            dirty = kwargs.get("dirty")
            if (
                dirty
                and self.root.agent_id in dirty["agents"]
                and any(message.get("tool_calls") for message in self.root.messages)
            ):
                raise StatePersistenceError("Synthetic response checkpoint failure")
            return await original(records, **kwargs)

        with self.assertLogs(self.manager.logger, level="ERROR"):
            with patch.object(self.manager._records, "commit", fail_window):
                admitted = await self.manager.activate_agent(self.root.agent_id)
                with self.assertRaises(StatePersistenceError):
                    await self.wait(admitted)
                with self.assertRaises(StatePersistenceError):
                    await self.manager.close()
        self.assertFalse(invoked)
        self.assertFalse(self.records("executions"))
        self.assertTrue(self.manager._closed)

    async def test_invalid_provider_call_identity_requires_remediation_without_a_partial_batch(
        self,
    ):
        response = call("unknown")
        response.tool_calls *= 2
        response.usage = {"total_tokens": 3}
        self.steps(response)
        admission = await self.manager.activate_agent(self.root.agent_id)
        with self.assertRaises(ModelUnavailable):
            await self.wait(admission)
        self.assertFalse(self.records("executions"))
        self.assertFalse(any(message.get("tool_calls") for message in self.root.messages))
        self.assertEqual(self.records("model_token_claims")[0].values["actual_usage"], 3)
        self.assertEqual(self.records("model_requests")[0].values["outcome"], "failed")
        self.assertEqual(
            self.records("model_availability")[0].values["status"], "remediation_required"
        )

    async def test_activity_config_rejects_invalid_runtime_changes_without_mutation(self):
        config = PersonalActivityConfig()
        for key, value in (
            ("minimum_sleep_minutes", 3000),
            ("maximum_sleep_minutes", 1),
            ("model_requests_per_invocation", 0),
            ("max_concurrent_model_requests", True),
        ):
            before = config.model_dump()
            with self.assertRaises(ValueError):
                setattr(config, key, value)
            self.assertEqual(config.model_dump(), before)
        for value in (0, -1, float("inf"), True):
            with self.assertRaises(ValueError):
                config.llm.model_timeouts["fixture"] = value
        config.llm.max_retries = 0
        config.llm.backoff_base_seconds = 0.0

    async def test_each_real_execution_retry_has_evidence_but_an_auditor_denial_has_none(self):
        attempts = 0

        async def flaky() -> str:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise RetryableToolError("Synthetic recoverable execution fault")
            return "done"

        def refused() -> str:
            self.fail("The denied executor must not begin.")

        self.manager.register_tool("flaky", func=flaky)
        self.manager.register_tool("refused", func=refused)
        self.manager.register_tool_auditor("refused", lambda: (False, "Denied by fixture"))
        self.manager.config.tool_execution_retry_policy = "typed_transient"
        self.manager.config.tool_execution_retry_backoff_factor = 0.0
        self.steps(call("flaky"), call("refused"), idle())
        admission = await self.manager.activate_agent(self.root.agent_id)
        await self.wait(admission)
        executions = {row.values["tool_name"]: row for row in self.records("executions")}
        evidence = self.records("execution_attempts")
        self.assertEqual(
            [
                row.values["attempt_index"]
                for row in evidence
                if row.values["execution_id"] == executions["flaky"].values["execution_id"]
            ],
            [1, 2, 3],
        )
        self.assertFalse(
            [
                row
                for row in evidence
                if row.values["execution_id"] == executions["refused"].values["execution_id"]
            ]
        )
        self.assertFalse(self.records("tool_cooldowns"))

    async def test_provider_capacity_wait_is_inside_the_whole_sequence_budget(self):
        await self.manager.close()
        self.manager = self.make_manager(
            self.root,
            config=ATTConfig(
                workspace_root=self.workspace.name,
                tool_calling_mode="native",
                activity={
                    "max_concurrent_model_requests": 1,
                    "llm": {"sequence_timeout_seconds": 1.0, "max_retries": 0},
                },
            ),
        )
        self.manager.register_runtime_clock(self.clock)
        barrier = AsyncBarrier()
        self.client.steps.append(ModelStep(idle(), barrier))
        first = await self.manager.activate_agent(self.root.agent_id)
        await asyncio.wait_for(barrier.wait_entered(), 5)
        second_client = ScriptedModelClient(ModelStep(idle()))
        other = Agent("Waiting", "Researcher", second_client)
        self.manager.register_llm_client("waiting", second_client)
        self.manager.register_agent(other)
        second = await self.manager.activate_agent(other.agent_id)
        await until(
            lambda: len(self.records("model_token_claims")) == 2 and self.clock.pending_waits >= 2
        )
        self.clock.advance(1)
        for admission in (first, second):
            with self.assertRaises(ModelUnavailable):
                await self.wait(admission)
        self.assertFalse(second_client.requests)
        claims = {row.values["model_alias"]: row for row in self.records("model_token_claims")}
        self.assertEqual(claims["waiting"].values["settlement"], "confirmed_unsent")
        self.assertEqual(claims["fixture"].values["settlement"], "unknown_sent")
        barrier.release()

    async def test_host_remediation_does_not_reset_usage_or_the_person(self):
        self.manager.config.model_token_limits["fixture"] = 1_000_000
        self.steps(ValueError("Synthetic configuration failure"), idle())
        admission = await self.manager.activate_agent(self.root.agent_id)
        with self.assertRaises(ModelUnavailable):
            await self.wait(admission)
        before = self.records("model_token_claims")[0]
        identity = self.root.agent_id
        history = tuple(self.root.message_history)
        await self.manager.clear_agent_model_unavailability(identity)
        await self.settle()
        self.assertEqual(self.root.agent_id, identity)
        self.assertEqual(tuple(self.root.message_history[: len(history)]), history)
        self.assertEqual(self.manager._records.index[before.identity], before)
        self.assertEqual(self.manager.inspect_agent_activity(identity).intent, "idle")

    async def test_arrival_waiting_at_the_idle_checkpoint_cannot_be_stranded(self):
        entered, release = asyncio.Event(), asyncio.Event()
        arrival_waiting = asyncio.Event()
        original = self.manager._records.commit
        original_acquire = self.manager._activity.lock.acquire
        source = None
        gated = False

        async def acquire():
            if asyncio.current_task() is source:
                arrival_waiting.set()
            return await original_acquire()

        async def commit(records, **kwargs):
            nonlocal gated
            if not gated and any(
                row.table_name == "agent_activities" and row.values["intent"] == "idle"
                for row in records
            ):
                gated = True
                entered.set()
                await release.wait()
            return await original(records, **kwargs)

        self.steps(idle(), idle())
        with (
            patch.object(self.manager._records, "commit", commit),
            patch.object(self.manager._activity.lock, "acquire", acquire),
        ):
            try:
                first = await self.manager.activate_agent(self.root.agent_id)
                await asyncio.wait_for(entered.wait(), 5)
                source = asyncio.create_task(
                    self.manager.deliver_agent_mail(
                        self.root.agent_id, message_type="note", payload={}
                    )
                )
                await asyncio.wait_for(arrival_waiting.wait(), 5)
                release.set()
                receipt = await asyncio.wait_for(source, 5)
                await self.wait(first)
                await self.settle()
            finally:
                release.set()
                if source is not None:
                    if not source.done():
                        source.cancel()
                    await asyncio.gather(source, return_exceptions=True)
        self.assertEqual(len(self.client.requests), 2)
        self.assertIn(receipt.message_id, str(self.client.requests[1].prompt))
        self.assertEqual(self.manager.inspect_agent_activity(self.root.agent_id).intent, "idle")

    async def test_working_window_is_bounded_without_erasing_history_or_cutting_a_batch(self):
        self.manager.config.max_memory_turns = 3
        self.steps(
            *(LLMResponse(text=f"Personal observation {index}") for index in range(9)), idle()
        )
        admission = await self.manager.activate_agent(self.root.agent_id)
        await self.wait(admission)
        self.assertLess(len(self.root.messages), 10)
        self.assertIn("Personal observation 0", str(self.root.message_history))
        self.assertTrue(
            any("Journal were retained" in str(message) for message in self.root.messages)
        )
        self.assertEqual(len(self.client.requests), 10)

    async def test_synchronous_provider_timeout_retains_the_live_local_owner(self):
        entered, release = threading.Event(), threading.Event()

        class Blocking:
            def generate(self, **kwargs):
                entered.set()
                release.wait(15)
                return LLMResponse(text="late synchronous provider result")

        client = Blocking()
        self.manager.register_llm_client("blocking", client)
        self.root.llm_client = client
        self.manager.config.activity.llm.request_timeout_seconds = 1.0
        self.manager.config.activity.llm.max_retries = 0
        self.manager.register_runtime_clock(self.clock)
        try:
            admission = await self.manager.activate_agent(self.root.agent_id)
            self.assertTrue(await asyncio.to_thread(entered.wait, 5))
            self.clock.advance(1)
            with self.assertRaises(ModelUnavailable):
                await self.wait(admission)
            self.clock.advance(60)
            with self.assertRaises(ModelUnavailable):
                await self.manager.activate_agent(self.root.agent_id)
            await asyncio.wait_for(self.manager.close(), 3)
        finally:
            release.set()
            await asyncio.gather(
                *tuple(self.manager._activity.models.tasks), return_exceptions=True
            )
        self.assertNotIn("late synchronous", str(self.root.message_history))

    async def test_uncooperative_tool_cannot_block_close_or_write_after_the_fence(self):
        entered, release = asyncio.Event(), asyncio.Event()
        library = self.manager.libraries[self.root.private_doc_library_id]

        async def late_write() -> str:
            entered.set()
            while not release.is_set():
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    continue
            library.write_file("late.txt", "MUST_NOT_BE_WRITTEN")
            return "finished"

        self.manager.register_tool("late_write", func=late_write)
        self.steps(call("late_write"))
        try:
            await self.manager.activate_agent(self.root.agent_id)
            await asyncio.wait_for(entered.wait(), 5)
            await asyncio.wait_for(self.manager.close(), 3)
            execution = next(
                row for row in self.records("executions") if row.values["tool_name"] == "late_write"
            )
            self.assertEqual(execution.values["status"], "running")
            self.assertEqual(execution.values["outcome_unconfirmed"], 1)
        finally:
            release.set()
            await asyncio.gather(*tuple(self.manager._activity.tool_tasks), return_exceptions=True)
        from pathlib import Path

        self.assertFalse(Path(library.root_dir, "late.txt").exists())
