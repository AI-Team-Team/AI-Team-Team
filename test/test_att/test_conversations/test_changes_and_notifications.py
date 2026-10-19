"""Append-only changes, withdrawal evidence, and independent personal reminders."""

from unittest.mock import patch

from pydantic import ValidationError

from ai_team_team import ConversationConfig, ToolArgumentError, ToolBusinessError
from test.test_att.test_autonomous_activity_phase0._fixtures import LogicalClock
from ._support import ChatTestCase


class ChangeAndNoticeTests(ChatTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.clock = LogicalClock(wall_time=100)
        self.addCleanup(self.clock.close)
        self.manager.register_runtime_clock(self.clock)
        self.manager.register_token_counter("fixture", len)

    async def test_window_can_exceed_ten_minutes_and_history_uses_its_applied_value(self):
        self.manager.config.conversations.withdrawal_window_seconds = 1200
        item = await self.manager.send_direct_message(self.other.agent_id, "Window source", actor=self.root)
        self.clock.advance(5)
        await self.manager.withdraw_chat_message(item.message_id, actor=self.root)
        self.assertEqual(self.records("chat_withdrawals")[0].values["window_seconds"], 1200)
        self.manager.config.conversations.withdrawal_window_seconds = 1
        await self.manager.save_state()
        await self.manager.load_state(self.path)
        self.assertEqual(self.records("chat_withdrawals")[0].values["window_seconds"], 1200)
        for value in (0, -1, float("inf"), float("nan"), True):
            with self.assertRaises(ValidationError):
                ConversationConfig(withdrawal_window_seconds=value)

    async def test_successful_edit_renews_window_but_failed_edit_does_not(self):
        self.manager.config.conversations.withdrawal_window_seconds = 10
        team = self.team()
        item = await self.manager.send_team_message(team.team_id, "V1", actor=self.root)
        self.clock.advance(11)
        with self.assertRaises(ToolBusinessError):
            await self.manager.withdraw_chat_message(item.message_id, actor=self.root)
        with patch.object(self.manager._records, "commit", side_effect=RuntimeError("Injected failure")):
            with self.assertRaises(RuntimeError):
                await self.manager.edit_chat_message(item.message_id, "Failed V2", actor=self.root)
        with self.assertRaises(ToolBusinessError):
            await self.manager.withdraw_chat_message(item.message_id, actor=self.root)
        await self.manager.edit_chat_message(item.message_id, "V2", actor=self.root)
        self.clock.advance(9)
        await self.manager.withdraw_chat_message(item.message_id, actor=self.root)
        self.assertEqual(len(self.records("chat_revisions")), 2)

    async def test_withdrawal_preserves_read_receipts_and_only_personal_reminder_preview(self):
        team = self.team()
        item = await self.manager.send_team_message(team.team_id, "# Heading\nCaptured preview", actor=self.root)
        reader = team.members[2]
        await self.manager.read_chat_message(item.message_id, actor=reader)
        before = {row.values["agent_id"]: row.values["read_at"] for row in self.records("chat_personal_views")}
        notices = self.records("agent_notifications")
        await self.manager.withdraw_chat_message(item.message_id, actor=self.root)
        after = {row.values["agent_id"]: row.values["read_at"] for row in self.records("chat_personal_views")}
        self.assertEqual(before, after)
        self.assertEqual(notices, self.records("agent_notifications"))
        self.assertIn("Captured preview", self.manager._messaging.frame_summaries(self.other))
        self.assertNotIn("Captured preview", self.manager.list_team_messages(team.team_id, actor=self.other).model_dump_json())
        self.assertFalse(self.manager.list_team_messages(team.team_id, actor=self.other, query="Captured").items)
        self.assertIn("withdrew", (await self.manager.read_chat_message(item.message_id, actor=self.other)).content)
        with self.assertRaises(PermissionError):
            await self.manager.read_chat_message(item.message_id, actor=self.other, version=1)
        self.assertNotIn("Captured preview", self.manager._messaging.frame_summaries(self.other))

    async def test_details_counts_and_deleted_or_departed_notices_are_independent(self):
        team = self.team()
        item = await self.manager.send_team_message(team.team_id, "# Title\nHidden when details disabled", actor=self.root)
        await self.manager.set_chat_details(actor=self.other, team_details=False)
        summary = self.manager._messaging.frame_summaries(self.other)
        self.assertIn("1 unread", summary)
        self.assertNotIn("Hidden when", summary)
        await self.manager.control_chat_message("delete_message", item.message_id, actor=self.other)
        notice = next(row for row in self.records("agent_notifications") if row.values["agent_id"] == self.other.agent_id)
        self.assertFalse(self.manager._activity.notice_pending(notice))
        await self.manager.control_chat_message("restore_message", item.message_id, actor=self.other)
        await self.manager._messaging.replace_members(team, [member for member in team.members if member is not self.other], actor=self.root)
        self.assertFalse(self.manager._activity.notice_pending(notice))
        self.assertEqual(self.manager._messaging.frame_summaries(self.other), "")
        self.assertEqual(self.manager.list_team_messages(team.team_id, actor=self.other).unread_count, 1)

    async def test_title_limits_unicode_untitled_and_fenced_headings(self):
        team = self.team()
        for body, title in (("No heading", None), ("~~~\n# Code\n~~~\n# Title\nBody", "Title"),
                            ("    # Indented\n# 实际标题\nBody", "实际标题"), ("Setext\n===\nBody", "Setext")):
            item = await self.manager.send_team_message(team.team_id, body, actor=self.root)
            view = self.manager._messaging.view(self.other, item.message_id)
            self.assertEqual(self.manager._messaging.summary(view, self.manager._records.index).title, title)
        before = len(self.records("chat_messages"))
        with self.assertRaises(ToolArgumentError):
            await self.manager.send_direct_message(self.other.agent_id, "# " + "A" * 201, actor=self.root)
        self.assertEqual(len(self.records("chat_messages")), before)

    async def test_direct_edit_cannot_bypass_stranger_allowance_or_block(self):
        item = await self.manager.send_direct_message(self.other.agent_id, "One", actor=self.root)
        await self.manager.edit_chat_message(item.message_id, "Two", actor=self.root)
        await self.manager.edit_chat_message(item.message_id, "Three", actor=self.root)
        with self.assertRaises(ToolBusinessError):
            await self.manager.edit_chat_message(item.message_id, "Fourth delivery", actor=self.root)
        await self.manager.control_direct_relationship(self.root.agent_id, "block_agent", actor=self.other)
        with self.assertRaises(ToolBusinessError):
            await self.manager.edit_chat_message(item.message_id, "Blocked delivery", actor=self.root)
        await self.manager.withdraw_chat_message(item.message_id, actor=self.root)

    async def test_every_retained_unread_preview_is_inspectable_without_reopening_the_source(self):
        item = await self.manager.send_direct_message(self.other.agent_id, "Preview V1", actor=self.root)
        await self.manager.edit_chat_message(item.message_id, "Preview V2", actor=self.root)
        await self.manager.withdraw_chat_message(item.message_id, actor=self.root)
        self.manager.config.conversations.summary_preview_limit = 1
        summary = self.manager._messaging.frame_summaries(self.other)
        self.assertIn("Showing 1 of 2 eligible previews", summary)
        page = self.manager.list_chat_reminders(actor=self.other, message_id=item.message_id, limit=1)
        self.assertEqual(page.total_count, 2)
        self.assertEqual(page.items[0].preview, "Preview V1")
        next_page = self.manager.list_chat_reminders(actor=self.other, message_id=item.message_id, cursor=page.next_cursor, limit=1)
        self.assertEqual(next_page.items[0].preview, "Preview V2")
        self.assertEqual(self.manager.list_direct_messages(self.root.agent_id, actor=self.other).unread_count, 1)
        with self.assertRaises(PermissionError):
            await self.manager.read_chat_message(item.message_id, actor=self.other, version=1)

    async def test_reading_an_old_revision_does_not_clear_a_new_unread_revision(self):
        item = await self.manager.send_direct_message(self.other.agent_id, "Earlier", actor=self.root)
        await self.manager.edit_chat_message(item.message_id, "Latest", actor=self.root)
        read = await self.manager.read_chat_message(item.message_id, actor=self.other, version=1)
        self.assertEqual(read.content, "Earlier")
        self.assertEqual(self.manager.list_direct_messages(self.root.agent_id, actor=self.other).unread_count, 1)
        reminders = self.manager.list_chat_reminders(actor=self.other)
        self.assertEqual([item.version for item in reminders.items], [2])
        await self.manager.read_chat_message(item.message_id, actor=self.other)
        self.assertFalse(self.manager.list_chat_reminders(actor=self.other).items)

    async def test_disabled_details_and_page_counts_do_not_parse_unreturned_bodies(self):
        team = self.team()
        for index in range(3):
            await self.manager.send_team_message(team.team_id, f"# Title {index}\nBody {index}", actor=self.root)
        await self.manager.set_chat_details(actor=self.other, team_details=False)
        with patch("ai_team_team.core.manager.messaging.views.extract", side_effect=AssertionError("Unexpected body parsing")):
            self.assertIn("3 unread", self.manager._messaging.frame_summaries(self.other))
        from ai_team_team.core.manager.messaging.markdown import extract
        with patch("ai_team_team.core.manager.messaging.views.extract", wraps=extract) as parsing:
            self.assertEqual(self.manager.list_team_messages(team.team_id, actor=self.other, limit=1).total_count, 3)
        self.assertEqual(parsing.call_count, 1)

    async def test_callbacks_and_discovery_never_contain_chat_payloads(self):
        observed = []
        self.manager.on_system_event = lambda *arguments: observed.append(arguments)
        payload = "PAYLOAD_MUST_NOT_ENTER_PUBLIC_CALLBACKS"
        await self.manager.send_direct_message(self.other.agent_id, payload, actor=self.root)
        await self.manager.flush_callbacks()
        self.assertNotIn(payload, str(observed))
        self.assertNotIn(payload, self.manager.list_entities().model_dump_json())
