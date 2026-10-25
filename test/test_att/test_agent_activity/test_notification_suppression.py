"""Suppression is personal reminder state, separate from delivered sources."""

import asyncio
from unittest.mock import Mock

from ai_team_team import Agent
from ai_team_team.core.activity.contracts import SuppressionPreference, WakeDuration
from ai_team_team.core.exceptions import ToolPermissionError
from test.test_att.test_agent_activity._support import ActivityTestCase, call, idle


class SuppressionTests(ActivityTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.manager.register_runtime_clock(self.clock)
        self.manager._activity.schedule_notice = Mock()

    async def test_timed_expiration_emits_one_count_summary_without_reading_mail(self):
        preference = await self.manager.set_notification_suppression(
            SuppressionPreference(scope="all", countdown=WakeDuration(minutes=5)), actor=self.root)
        receipt = await self.manager.deliver_agent_mail(self.root.agent_id, message_type="ordinary", payload={"secret": "private body"})
        notice = self.manager._records.index[("agent_notifications", (receipt.notification_ids[0],))]
        self.assertTrue(self.manager._activity.suppressed(notice))
        timer = self.manager._activity.suppression_timers[preference["preference_id"]]
        self.clock.advance(300)
        await asyncio.wait_for(timer, 10)
        pending = self.manager._activity.pending_notices(self.root.agent_id)
        self.assertEqual(len(pending), 1)
        self.assertEqual(self.manager._activity.summary_counts(pending[0]), [
            {"source_kind": "personal_mail", "source_id": None, "count": 1}])
        self.assertIsNone(self.root.agent_inbox[-1]["read_at"])
        self.assertNotIn("private body", str(self.records("notification_summary_items")))
        await self.manager.remove_notification_suppression(preference["preference_id"], actor=self.root)
        self.assertEqual(len(self.records("notification_summary_items")), 1)

    async def test_overlapping_permanent_preferences_do_not_replay_suppressed_arrivals(self):
        first, second = [await self.manager.set_notification_suppression(SuppressionPreference(scope="all"), actor=self.root)
                         for _ in range(2)]
        await self.manager.deliver_agent_mail(self.root.agent_id, message_type="ordinary", payload={})
        await self.manager.remove_notification_suppression(first["preference_id"], actor=self.root)
        self.assertFalse(self.manager._activity.pending_notices(self.root.agent_id))
        self.assertFalse(self.records("notification_summary_items"))
        await self.manager.remove_notification_suppression(second["preference_id"], actor=self.root)
        self.assertEqual(len(self.manager._activity.pending_notices(self.root.agent_id)), 1)
        self.assertEqual(len(self.records("notification_summary_items")), 1)

    async def test_preferences_cannot_select_another_owner_or_bypass_protected_notices(self):
        other = self.manager.register_agent(Agent("Other", "Researcher", self.client))
        preference = await self.manager.set_notification_suppression(SuppressionPreference(scope="all"), actor=self.root)
        with self.assertRaises(ToolPermissionError):
            await self.manager.remove_notification_suppression(preference["preference_id"], actor=other)
        event = self.manager._memory.record_event("permission_changed", agent=self.root, payload={}, persist=False)
        notice_id = await self.manager._activity.deliver_system_event(event)
        self.assertEqual([row.values["notification_id"] for row in self.manager._activity.pending_notices(self.root.agent_id)], [notice_id])

    async def test_native_control_exposes_only_the_current_person(self):
        self.steps(call("set_notification_suppression", {"preference": {"scope": "all"}}), idle())
        admitted = await self.manager.activate_agent(self.root.agent_id)
        await self.wait(admitted)
        preferences = self.manager.list_notification_suppressions(actor=self.root)
        self.assertEqual(len(preferences), 1)
        self.assertTrue(preferences[0]["permanent"])

    async def test_countdown_sampler_persists_elapsed_sleep_without_an_explicit_save(self):
        self.steps(call("set_activity_intent", {"intent": {"kind": "sleep", "countdown": {"minutes": 5}}}))
        admission = await self.manager.activate_agent(self.root.agent_id)
        await self.wait(admission, "sleep")
        async with asyncio.timeout(10):
            while self.clock.pending_waits < 2:
                await asyncio.sleep(0)
        self.clock.advance(60)
        async with asyncio.timeout(10):
            while self.records("sleep_plans")[0].values["remaining_seconds"] != 240:
                await asyncio.sleep(0)
        self.assertEqual(self.records("sleep_plans")[0].values["remaining_seconds"], 240)
