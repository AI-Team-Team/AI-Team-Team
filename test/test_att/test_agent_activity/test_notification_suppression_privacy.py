"""Restored reminder presentation must not reveal suppressed bodies or hidden sources."""

import asyncio
from unittest.mock import Mock

from ai_team_team.core.activity.contracts import SuppressionPreference, WakeDuration
from test.test_att.test_agent_activity._support import ActivityTestCase, idle


class SuppressionPrivacyTests(ActivityTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.manager.register_runtime_clock(self.clock)
        self.manager._activity.schedule_notice = Mock()
        self.team = self.manager.bootstrap_agent_team(self.root, existing_members=[self.root],
            member_configs={"Peer1": {"model": "fixture"}, "Peer2": {"model": "fixture"}})
        self.peer = self.team.members[1]

    async def test_removal_frame_contains_counts_but_no_titles_bodies_or_reminder_replay(self):
        preference = await self.manager.set_notification_suppression(SuppressionPreference(scope="all"), actor=self.root)
        message = await self.manager.send_team_message(self.team.team_id, "# SECRET_TITLE\nSECRET_BODY", actor=self.peer)
        await self.manager.remove_notification_suppression(preference["preference_id"], actor=self.root)
        self.steps(idle())
        admitted = await self.manager.activate_agent(self.root.agent_id)
        await self.wait(admitted)
        prompt = str(self.client.requests[-1].prompt)
        self.assertIn("1 unread", prompt)
        self.assertNotIn("SECRET_TITLE", prompt)
        self.assertNotIn("SECRET_BODY", prompt)
        view = self.manager._messaging.view(self.root, message.message_id)
        self.assertIsNone(view.values["read_at"])

    async def test_personally_hidden_messages_are_never_counted_or_restored(self):
        preference = await self.manager.set_notification_suppression(SuppressionPreference(scope="all"), actor=self.root)
        message = await self.manager.send_team_message(self.team.team_id, "# Hidden\nbody", actor=self.peer)
        await self.manager.control_chat_message("delete_message", message.message_id, actor=self.root)
        await self.manager.remove_notification_suppression(preference["preference_id"], actor=self.root)
        self.assertFalse(self.records("notification_summary_items"))
        self.assertTrue(self.manager._messaging.view(self.root, message.message_id, include_deleted=True).values["deleted"])

    async def test_departure_before_suppression_ends_does_not_summarize_archived_chat(self):
        preference = await self.manager.set_notification_suppression(SuppressionPreference(scope="all"), actor=self.root)
        message = await self.manager.send_team_message(self.team.team_id, "Retained history", actor=self.peer)
        await self.manager.close_team_conversation(self.team.team_id)
        await self.manager.remove_notification_suppression(preference["preference_id"], actor=self.root)
        self.assertFalse(self.records("notification_summary_items"))
        self.assertEqual(self.manager._messaging.view(self.root, message.message_id).values["view_kind"], "frozen")
        self.assertTrue(self.manager.list_team_messages(self.team.team_id, actor=self.root).items)

    async def test_departure_after_summary_creation_removes_its_archived_source_counts(self):
        preference = await self.manager.set_notification_suppression(SuppressionPreference(scope="all"), actor=self.root)
        await self.manager.send_team_message(self.team.team_id, "Retained history", actor=self.peer)
        await self.manager.remove_notification_suppression(preference["preference_id"], actor=self.root)
        summary = next(row for row in self.manager._activity.pending_notices(self.root.agent_id)
            if self.manager._activity.summary_event(row) is not None)
        self.assertEqual(self.manager._activity.summary_counts(summary)[0]["count"], 1)
        await self.manager.close_team_conversation(self.team.team_id)
        self.assertFalse(self.manager._activity.summary_counts(summary))
        self.assertNotIn(summary, self.manager._activity.pending_notices(self.root.agent_id))

    async def test_expiration_waits_for_its_receipt_before_releasing_original_notices(self):
        preference = await self.manager.set_notification_suppression(
            SuppressionPreference(scope="all", countdown=WakeDuration(minutes=5)), actor=self.root)
        receipt = await self.manager.deliver_agent_mail(self.root.agent_id, message_type="ordinary", payload={})
        self.clock.advance(300)
        # Before the expiration task can commit, an arrival or another active
        # context cannot release every original reminder individually.
        notice = self.manager._records.index[("agent_notifications", (receipt.notification_ids[0],))]
        self.assertTrue(self.manager._activity.suppressed(notice))
        timer = self.manager._activity.suppression_timers[preference["preference_id"]]
        await asyncio.wait_for(timer, 10)
        self.assertTrue(self.manager._activity.covered_notice_ids())

    async def test_new_overlapping_preference_does_not_strand_an_earlier_summary(self):
        first = await self.manager.set_notification_suppression(SuppressionPreference(scope="all"), actor=self.root)
        await self.manager.deliver_agent_mail(self.root.agent_id, message_type="ordinary", payload={})
        await self.manager.remove_notification_suppression(first["preference_id"], actor=self.root)
        original_summary = self.manager._activity.pending_notices(self.root.agent_id)[0]
        second = await self.manager.set_notification_suppression(SuppressionPreference(scope="all"), actor=self.root)
        self.assertFalse(self.manager._activity.pending_notices(self.root.agent_id))
        self.manager._activity.schedule_notice.reset_mock()
        await self.manager.remove_notification_suppression(second["preference_id"], actor=self.root)
        self.manager._activity.schedule_notice.assert_called_with(original_summary.values["notification_id"])
        self.assertEqual(len(self.records("notification_summary_items")), 1)
