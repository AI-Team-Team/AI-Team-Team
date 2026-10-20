"""Cancellation, source acceptance, and presentation use authoritative boundaries."""

import asyncio
from unittest.mock import patch

from ai_team_team import Agent, LLMResponse, StatePersistenceError, ToolCall
from ai_team_team.core.activity.contracts import AgentTeamScope
from test.test_att.test_autonomous_activity_phase0._fixtures import AsyncBarrier, ModelStep

from ._support import ActivityTestCase, idle, personal_control_contract


class DispatchReceiptBoundaryTests(ActivityTestCase):
    async def test_cancelled_native_child_interrupts_its_waiting_sibling_and_owner(self):
        sibling_started, sibling_cancelled = asyncio.Event(), asyncio.Event()

        async def cancelled_tool() -> str:
            await sibling_started.wait()
            raise asyncio.CancelledError("The tool invocation was cancelled.")

        async def waiting_tool() -> str:
            sibling_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                sibling_cancelled.set()
            return "unreachable"

        self.manager.register_tool("cancelled_tool", func=cancelled_tool, execution_contract=personal_control_contract())
        self.manager.register_tool("waiting_tool", func=waiting_tool, execution_contract=personal_control_contract())
        self.steps(LLMResponse(tool_calls=[
            ToolCall("cancelled", "cancelled_tool", {}),
            ToolCall("waiting", "waiting_tool", {}),
        ]))
        admitted = await self.manager.activate_agent(self.root.agent_id)
        with self.assertRaises(asyncio.CancelledError):
            await self.wait(admitted)
        await asyncio.wait_for(sibling_cancelled.wait(), 5)
        async with asyncio.timeout(10):
            while self.manager._activity.workers or self.manager._activity.tool_tasks:
                await asyncio.gather(*(
                    self.manager._activity.workers | self.manager._activity.tool_tasks
                ), return_exceptions=True)
                await asyncio.sleep(0)
        self.assertFalse(self.root.lock.locked())
        self.assertEqual(self.manager.inspect_agent_activity(self.root.agent_id).intent, "continuing")
        self.assertEqual(self.records("activity_admissions")[0].values["disposition"], "interrupted")
        self.assertTrue(all(row.values["outcome_unconfirmed"] for row in self.records("executions")))
        self.assertEqual(
            {message["tool_call_id"] for message in self.root.messages if message["role"] == "tool"},
            {"cancelled", "waiting"},
        )
        self.assertTrue(all(
            "[interrupted]" in message["content"]
            for message in self.root.messages if message["role"] == "tool"
        ))
        self.steps(idle())
        retried = await self.manager.activate_agent(self.root.agent_id)
        await self.wait(retried)

    async def test_committed_interaction_survives_observer_cancellation_in_its_requested_scope(self):
        for durable in (False, True):
            with self.subTest(durable=durable):
                if durable:
                    await self.manager.close()
                    self.root = Agent("DurableRoot", "Architect", self.client)
                    self.manager = self.make_manager(self.root, durable=True)
                team = self.manager.bootstrap_agent_team(
                    self.root,
                    existing_members=[self.root],
                    member_configs={"PeerA": {"model": "fixture"}, "PeerB": {"model": "fixture"}},
                )
                committed, release = asyncio.Event(), asyncio.Event()
                original = self.manager._records.commit

                async def hold_source_receipt(records, **kwargs):
                    receipt = await original(records, **kwargs)
                    if any(row.table_name == "agent_notifications" for row in records):
                        committed.set()
                        await release.wait()
                    return receipt

                barrier = AsyncBarrier()
                self.client.steps.append(ModelStep(idle(), barrier))
                with patch.object(self.manager._records, "commit", hold_source_receipt):
                    observer = asyncio.create_task(self.manager.execute_agent_interaction(
                        self.root, "ACCEPTED_SCOPED_INSTRUCTION", team=team
                    ))
                    await asyncio.wait_for(committed.wait(), 10)
                    observer.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await observer
                    release.set()
                    await asyncio.wait_for(barrier.wait_entered(), 10)
                current = self.manager.inspect_agent_activity(self.root.agent_id)
                self.assertEqual(current.scope, AgentTeamScope(team_id=team.team_id))
                self.assertIn("ACCEPTED_SCOPED_INSTRUCTION", str(self.client.requests[-1].prompt))
                self.assertEqual(len(self.root.agent_inbox), 1)
                self.assertEqual(len(self.records("agent_notifications")), 1)
                self.assertFalse(getattr(
                    self.manager._activity.sessions[self.root.agent_id], "interaction_waiters", ()
                ))
                barrier.release()
                await asyncio.wait_for(self.manager.wait_for_activity_checkpoint(
                    current.admission_id, intent="idle"
                ), 10)
                await self.settle()

    async def test_cancellation_before_source_acceptance_has_no_mail_or_admission(self):
        barrier = AsyncBarrier()
        original = self.manager._records.commit

        async def hold_before_acceptance(records, **kwargs):
            if any(row.table_name == "agent_notifications" for row in records):
                await barrier.pause()
            return await original(records, **kwargs)

        with patch.object(self.manager._records, "commit", hold_before_acceptance):
            observer = asyncio.create_task(self.manager.execute_agent_interaction(
                self.root, "NOT_ACCEPTED"
            ))
            await barrier.wait_entered()
            observer.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await observer
        self.assertFalse(self.root.agent_inbox)
        self.assertFalse(self.records("agent_notifications"))
        self.assertFalse(self.records("activity_admissions"))
        self.assertFalse(self.manager._activity.dispatch_tasks)
        self.assertFalse(self.client.requests)

    async def test_interaction_observer_cannot_cancel_an_already_dispatched_model(self):
        barrier = AsyncBarrier()
        self.client.steps.append(ModelStep(idle(), barrier))
        observer = asyncio.create_task(self.manager.execute_agent_interaction(self.root, "Continue"))
        await barrier.wait_entered()
        observer.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await observer
        self.assertEqual(barrier.cancellations, 0)
        self.assertTrue(self.manager._activity.sessions[self.root.agent_id].active)
        barrier.release()
        current = self.manager.inspect_agent_activity(self.root.agent_id)
        await asyncio.wait_for(self.manager.wait_for_activity_checkpoint(
            current.admission_id, intent="idle"
        ), 10)

    async def test_cancellation_during_admission_does_not_cancel_its_accepted_commit(self):
        committed, release = asyncio.Event(), asyncio.Event()
        original = self.manager._records.commit

        async def hold_admission_receipt(records, **kwargs):
            receipt = await original(records, **kwargs)
            if any(row.table_name == "activity_admissions"
                   and row.values["disposition"] == "admitted" for row in records):
                committed.set()
                await release.wait()
            return receipt

        self.steps(idle())
        with patch.object(self.manager._records, "commit", hold_admission_receipt):
            observer = asyncio.create_task(self.manager.execute_agent_interaction(self.root, "Accepted"))
            await asyncio.wait_for(committed.wait(), 5)
            observer.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await observer
            release.set()
            await self.settle()
        self.assertEqual(len(self.client.requests), 1)
        self.assertEqual(self.records("activity_admissions")[0].values["disposition"], "completed")

    async def test_failed_source_commit_propagates_without_admitting_work(self):
        original = self.manager._records.commit

        async def reject_source(records, **kwargs):
            if any(row.table_name == "agent_notifications" for row in records):
                raise StatePersistenceError("Synthetic rejected personal instruction")
            return await original(records, **kwargs)

        with patch.object(self.manager._records, "commit", reject_source):
            with self.assertRaises(StatePersistenceError):
                await self.manager.execute_agent_interaction(self.root, "Not committed")
        self.assertFalse(self.root.agent_inbox)
        self.assertFalse(self.records("agent_notifications"))
        self.assertFalse(self.manager._activity.dispatch_tasks)
        self.assertFalse(self.client.requests)

    async def test_interaction_coalesces_without_replacing_the_existing_personal_scope(self):
        team = self.manager.bootstrap_agent_team(
            self.root, existing_members=[self.root],
            member_configs={"PeerA": {"model": "fixture"}, "PeerB": {"model": "fixture"}},
        )
        barrier = AsyncBarrier()
        self.client.steps.extend((
            ModelStep(LLMResponse(text="Before the instruction"), barrier),
            ModelStep(LLMResponse(text="PERSONAL_ANSWER")),
            ModelStep(idle()),
        ))
        admitted = await self.manager.activate_agent(self.root.agent_id)
        await barrier.wait_entered()
        observer = asyncio.create_task(self.manager.execute_agent_interaction(
            self.root, "Answer from your current activity", team=team
        ))
        async with asyncio.timeout(5):
            while not getattr(self.manager._activity.sessions[self.root.agent_id], "interaction_waiters", ()):
                await asyncio.sleep(0)
        barrier.release()
        result = await asyncio.wait_for(observer, 10)
        self.assertEqual(result.answer, "PERSONAL_ANSWER")
        self.assertIsNone(result.team_id)
        await self.wait(admitted)
        self.assertEqual(len(self.records("activity_admissions")), 1)

    async def test_duplicate_trusted_ingress_does_not_wake_a_presented_unread_notice(self):
        self.steps(idle(), idle())
        event = self.manager._memory.record_event(
            "permission_changed", agent=self.root, persist=False, inherit_context=False,
            payload={"resource_id": "owned-resource"},
        )
        notice_id = await self.manager._activity.deliver_system_event(event)
        await self.settle()
        self.assertEqual(len(self.client.requests), 1)
        self.assertEqual(await self.manager._activity.deliver_system_event(event), notice_id)
        await self.settle()
        self.assertEqual(len(self.client.requests), 1)
        self.assertEqual(len(self.records("activity_admissions")), 1)
        self.assertEqual(len(self.records("agent_notifications")), 1)

    async def test_cancelled_trusted_ingress_preserves_dispatch_after_its_source_receipt(self):
        committed, release = asyncio.Event(), asyncio.Event()
        original = self.manager._records.commit

        async def hold_source_receipt(records, **kwargs):
            receipt = await original(records, **kwargs)
            if any(row.table_name == "agent_notifications" for row in records):
                committed.set()
                await release.wait()
            return receipt

        event = self.manager._memory.record_event(
            "permission_changed", agent=self.root, persist=False, inherit_context=False,
            payload={"resource_id": "owned-resource"},
        )
        self.steps(idle())
        with patch.object(self.manager._records, "commit", hold_source_receipt):
            observer = asyncio.create_task(self.manager._activity.deliver_system_event(event))
            await asyncio.wait_for(committed.wait(), 5)
            observer.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await observer
            release.set()
            await self.settle()
        self.assertEqual(len(self.client.requests), 1)
        self.assertEqual(len(self.records("agent_notifications")), 1)
        self.assertEqual(self.records("notification_claims")[0].values["status"], "presented")

    async def test_notice_admission_rechecks_presentation_under_the_mutation_lock(self):
        self.steps(idle(), idle())
        receipt = await self.manager.deliver_agent_mail(
            self.root.agent_id, message_type="note", payload={}
        )
        await self.settle()
        async with self.manager._activity.lock:
            # Models a task queued before the presentation receipt was known.
            self.manager._activity.schedule_activation(self.root.agent_id, notification_only=True)
        await self.settle()
        self.assertEqual(len(self.client.requests), 1)
        self.assertEqual(len(self.records("activity_admissions")), 1)
        self.assertIsNone(self.root.agent_inbox[0]["read_at"])
        self.assertEqual(self.root.agent_inbox[0]["message_id"], receipt.message_id)

    async def test_recovery_activation_is_not_lost_behind_an_ineligible_notice_task(self):
        self.steps(idle(), idle())
        receipt = await self.manager.deliver_agent_mail(
            self.root.agent_id, message_type="note", payload={}
        )
        await self.settle()
        async with self.manager._activity.lock:
            self.manager._activity.schedule_activation(self.root.agent_id, notification_only=True)
            self.manager._activity.schedule_activation(self.root.agent_id)
        await self.settle()
        self.assertEqual(len(self.client.requests), 2)
        self.assertEqual(len(self.records("activity_admissions")), 2)
        self.assertEqual(len(self.records("agent_notifications")), 1)
        self.assertEqual(self.root.agent_inbox[0]["message_id"], receipt.message_id)
