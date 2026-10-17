"""Presentation, typed tool failure, privacy, and genuine wake boundaries."""

import asyncio
import json

from ai_team_team import LLMResponse, ToolPermissionError, RetryableToolError
from test.test_att.test_autonomous_activity_phase0._fixtures import AsyncBarrier, ModelStep

from ._support import ActivityTestCase, call, idle


class NotificationAndToolTests(ActivityTestCase):
    async def test_native_and_text_failures_remain_observations_not_idle_or_team_failure(self):
        for native in (True, False):
            self.manager.config.tool_calling_mode = "native" if native else "text_react"

            def denied():
                raise ToolPermissionError("This operation is denied.")

            def missing():
                raise FileNotFoundError("A missing path is not an unavailable tool.")

            self.manager.register_tool("denied", func=denied)
            self.manager.register_tool("missing", func=missing)
            responses = [call("denied"), call("missing"), call("absent"), idle()]
            if not native:
                responses = [
                    LLMResponse(text=f"Action: {name}()")
                    for name in ("denied", "missing", "absent")
                ] + [idle(native=False)]
            start = len(self.client.requests)
            self.steps(*responses)
            admitted = await self.manager.activate_agent(self.root.agent_id)
            await self.wait(admitted)
            await self.settle()
            self.assertEqual(len(self.client.requests) - start, 4)
            self.assertFalse(self.records("tool_cooldowns"))
            self.assertFalse(self.manager._activity.sessions[self.root.agent_id].failure)

    async def test_execution_fault_cools_only_new_calls_to_the_same_tool(self):
        calls = []

        def flaky():
            calls.append("flaky")
            raise RetryableToolError("The declared service is temporarily unavailable.")

        def healthy():
            calls.append("healthy")
            return "success"

        self.manager.register_tool("flaky", func=flaky)
        self.manager.register_tool("healthy", func=healthy)
        self.steps(call("flaky"), call("flaky", call_id="again"), call("healthy"), idle())
        admitted = await self.manager.activate_agent(self.root.agent_id)
        await self.wait(admitted)
        self.assertEqual(calls, ["flaky", "healthy"])
        self.assertEqual(len(self.records("tool_cooldowns")), 1)
        cooldown = self.records("tool_cooldowns")[0]
        self.assertEqual(
            cooldown.version, 1, "A rejected cooling call must not extend the cooldown."
        )
        self.assertEqual(cooldown.values["agent_id"], self.root.agent_id)

    async def test_invalid_sleep_is_correctable_without_cooling_the_control(self):
        self.steps(
            call("set_activity_intent", {"intent": {"kind": "sleep", "countdown": {"minutes": 1}}}),
            idle(),
        )
        admission = await self.manager.activate_agent(self.root.agent_id)
        await self.wait(admission)
        self.assertFalse(self.records("sleep_plans"))
        self.assertFalse(self.records("tool_cooldowns"))

    async def test_presented_unanswered_mail_does_not_reactivate_or_mark_read(self):
        self.steps(idle(), idle())
        first = await self.manager.activate_agent(self.root.agent_id)
        await self.wait(first)
        receipt = await self.manager.deliver_agent_mail(
            self.root.agent_id, message_type="note", payload={"text": "A voluntary matter."}
        )
        await self.settle()
        self.assertIsNone(self.root.agent_inbox[0]["read_at"])
        self.assertEqual(len(self.client.requests), 2)
        claim = next(
            row
            for row in self.records("notification_claims")
            if row.values["notification_id"] in receipt.notification_ids
        )
        self.assertEqual(claim.values["status"], "presented")
        # Read-state changes are not arrivals and cannot create another admission.
        await self.manager.mark_agent_inbox_read(self.root.agent_id)
        await self.settle()
        self.assertEqual(len(self.client.requests), 2)
        self.assertEqual(len(self.records("activity_admissions")), 2)

    async def test_mail_arriving_during_model_wait_enters_the_next_request_without_overlap(self):
        barrier = AsyncBarrier()
        self.client.steps.extend(
            [ModelStep(LLMResponse(text="Continue privately"), barrier), ModelStep(idle())]
        )
        admission = await self.manager.activate_agent(self.root.agent_id)
        await asyncio.wait_for(barrier.wait_entered(), 5)
        receipt = await self.manager.deliver_agent_mail(
            self.root.agent_id, message_type="notice", payload={}
        )
        self.assertEqual(len(self.client.requests), 1)
        barrier.release()
        await self.wait(admission)
        self.assertIn(receipt.message_id, json.dumps(self.client.requests[1].prompt))
        self.assertEqual(self.client.maximum_in_flight, 1)

    async def test_private_read_is_transient_even_at_a_mid_activity_checkpoint(self):
        secret = "PRIVATE_BODY_MUST_NOT_ENTER_CHECKPOINT_OR_CALLBACK"
        self.manager.libraries[self.root.private_doc_library_id].write_file("secret.txt", secret)
        barrier = AsyncBarrier()
        self.client.steps.extend(
            [
                ModelStep(call("read_private_file", {"path": "secret.txt"})),
                ModelStep(idle(), barrier),
            ]
        )
        observed = []
        self.manager.on_system_event = lambda *args: observed.append(args)
        admission = await self.manager.activate_agent(self.root.agent_id)
        await asyncio.wait_for(barrier.wait_entered(), 5)
        self.assertIn(secret, json.dumps(self.client.requests[-1].prompt))
        dirty = self.manager._new_dirty_state(full=True)
        snapshot = self.manager._capture_state_snapshot(dirty)
        from ai_team_team.database.persistence.records import thaw

        safe = {
            key: thaw(value)
            for key, value in snapshot.items()
            if key not in {"records", "file_changes"}
        }
        self.assertNotIn(secret, json.dumps(safe))
        self.assertNotIn(secret, str(self.root.message_history))
        await self.manager.flush_callbacks()
        self.assertNotIn(secret, str(observed))
        barrier.release()
        await self.wait(admission)

    async def test_ordinary_mail_cannot_spoof_a_protected_wake(self):
        self.manager.register_runtime_clock(self.clock)
        self.steps(
            call("set_activity_intent", {"intent": {"kind": "sleep", "countdown": {"minutes": 5}}}),
            idle(),
        )
        admitted = await self.manager.activate_agent(self.root.agent_id)
        await self.wait(admitted, "sleep")
        receipt = await self.manager.deliver_agent_mail(
            self.root.agent_id,
            message_type="recovery_interruption",
            payload={"classification": "recovery", "important": True},
        )
        self.assertEqual(
            self.manager._records.index[
                ("agent_notifications", (receipt.notification_ids[0],))
            ].values["classification"],
            "ordinary",
        )
        self.assertEqual(len(self.client.requests), 1)
        event = self.manager._memory.record_event(
            "permission_changed",
            agent=self.root,
            persist=False,
            inherit_context=False,
            payload={"resource_id": "owned-resource"},
        )
        await self.manager._activity.deliver_system_event(event)
        await self.settle()
        self.assertEqual(len(self.client.requests), 2)
        self.assertEqual(self.manager.inspect_agent_activity(self.root.agent_id).intent, "idle")

    async def test_invalid_mail_payload_has_no_partial_source_or_arrival(self):
        for payload in ({"bad": object()}, {"bad": float("nan")}):
            with self.assertRaises(ValueError):
                await self.manager.deliver_agent_mail(
                    self.root.agent_id, message_type="bad", payload=payload
                )
        self.assertFalse(self.root.agent_inbox)
        self.assertFalse(self.records("agent_notifications"))
        self.assertFalse(self.client.requests)
