"""Exact interval visibility, frozen history, and token-gated explicit reads."""

import asyncio
from unittest.mock import patch

from ai_team_team import Agent, FileReadRangeError, FileVersionChangedError, ToolArgumentError
from test.test_att.test_autonomous_activity_phase0._fixtures import AsyncBarrier
from ._support import ChatTestCase


class HistoryAndReadTests(ChatTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.manager.register_token_counter("fixture", len)

    async def test_leave_edit_withdraw_rejoin_never_unlocks_an_absence_gap(self):
        team = self.team()
        original = await self.manager.send_team_message(team.team_id, "# Earlier\nBefore departure", actor=self.root)
        own_fields = (self.other.system_instructions, self.other.role, self.other.llm_client,
                      self.other.messages, self.other.private_doc_library_id, self.other.agent_inbox)
        await self.manager._messaging.replace_members(team, [member for member in team.members if member is not self.other], actor=self.root)
        await self.manager.edit_chat_message(original.message_id, "# Later\nAfter departure", actor=self.root)
        hidden = await self.manager.send_team_message(team.team_id, "# Hidden\nAbsence", actor=self.root)
        await self.manager.withdraw_chat_message(original.message_id, actor=self.root)
        await self.manager._messaging.replace_members(team, [*team.members, self.other], actor=self.root)
        latest = await self.manager.send_team_message(team.team_id, "# Return\nAfter return", actor=self.root)
        page = self.manager.list_team_messages(team.team_id, actor=self.other)
        self.assertEqual([item.message_id for item in page.items], [original.message_id, latest.message_id])
        self.assertEqual(page.items[0].title, "Earlier")
        self.assertTrue(page.items[0].frozen)
        self.assertFalse(self.manager.list_team_messages(team.team_id, actor=self.other, query="Hidden").items)
        with self.assertRaises(PermissionError):
            await self.manager.read_chat_message(hidden.message_id, actor=self.other)
        with self.assertRaises(PermissionError):
            await self.manager.read_chat_message(original.message_id, actor=self.other, version=2)
        self.assertIn("Before departure", (await self.manager.read_chat_message(original.message_id, actor=self.other)).content)
        self.assertEqual(own_fields, (self.other.system_instructions, self.other.role, self.other.llm_client,
                                     self.other.messages, self.other.private_doc_library_id, self.other.agent_inbox))

    async def test_authority_is_captured_not_inferred_from_personal_history(self):
        team = self.team()
        item = await self.manager.send_team_message(team.team_id, "Previously authorized", actor=self.other)
        await self.manager._messaging.replace_members(team, [member for member in team.members if member is not self.other], actor=self.root)
        for operation in (self.manager.edit_chat_message(item.message_id, "Not allowed", actor=self.other),
                          self.manager.withdraw_chat_message(item.message_id, actor=self.other),
                          self.manager.send_team_message(team.team_id, "Not allowed", actor=self.other)):
            with self.assertRaises(PermissionError):
                await operation
        self.assertEqual((await self.manager.read_chat_message(item.message_id, actor=self.other)).content, "Previously authorized")

    async def test_partial_unicode_read_marks_only_returned_source_and_checks_continuation(self):
        first = await self.manager.send_direct_message(self.other.agent_id, "一二三四五六七八", actor=self.root)
        second = await self.manager.send_direct_message(self.other.agent_id, "Not read", actor=self.root)
        self.manager.config.file_read.max_read_tokens = 3
        result = await self.manager.read_chat_message(first.message_id, actor=self.other)
        self.assertEqual(result.content, "一二三")
        self.assertEqual((result.next_line, result.next_character), (1, 4))
        continuation = await self.manager.read_chat_message(first.message_id, actor=self.other, start_character=4,
            character_count=2, expected_file_version=result.file_version)
        self.assertEqual(continuation.content, "四五")
        page = self.manager.list_direct_messages(self.root.agent_id, actor=self.other)
        self.assertEqual(page.unread_count, 1)
        self.assertEqual([item.message_id for item in page.items if item.unread], [second.message_id])
        await self.manager.edit_chat_message(first.message_id, "Replacement", actor=self.root)
        with self.assertRaises(FileVersionChangedError):
            await self.manager.read_chat_message(first.message_id, actor=self.other, expected_file_version=result.file_version)
        with self.assertRaises(FileReadRangeError):
            await self.manager.read_chat_message(first.message_id, actor=self.other, start_character=999)
        self.assertEqual(self.manager.list_direct_messages(self.root.agent_id, actor=self.other).unread_count, 2)

    async def test_changes_while_counting_do_not_return_or_mark_a_stale_source(self):
        message = await self.manager.send_direct_message(self.other.agent_id, "Before", actor=self.root)
        barrier = AsyncBarrier()

        async def count(text):
            await barrier.pause()
            return len(text)

        self.manager.register_token_counter("fixture", count)
        reading = asyncio.create_task(self.manager.read_chat_message(message.message_id, actor=self.other))
        await barrier.wait_entered()
        await self.manager.edit_chat_message(message.message_id, "After", actor=self.root)
        barrier.release()
        with self.assertRaises(FileVersionChangedError):
            await reading
        self.assertEqual(self.manager.list_direct_messages(self.root.agent_id, actor=self.other).unread_count, 1)

    async def test_personal_delete_survives_edit_and_can_be_explicitly_restored(self):
        item = await self.manager.send_direct_message(self.other.agent_id, "V1", actor=self.root)
        await self.manager.control_chat_message("delete_message", item.message_id, actor=self.other)
        notices = len(self.records("agent_notifications"))
        await self.manager.edit_chat_message(item.message_id, "V2", actor=self.root)
        self.assertFalse(self.manager.list_direct_messages(self.root.agent_id, actor=self.other).items)
        self.assertEqual(len(self.records("agent_notifications")), notices)
        with self.assertRaises(PermissionError):
            await self.manager.read_chat_message(item.message_id, actor=self.other)
        await self.manager.control_chat_message("restore_message", item.message_id, actor=self.other)
        self.assertEqual((await self.manager.read_chat_message(item.message_id, actor=self.other)).content, "V2")
        await self.manager.control_chat_message("mark_message_unread", item.message_id, actor=self.other)
        self.assertEqual(self.manager.list_direct_messages(self.root.agent_id, actor=self.other).unread_count, 1)
        self.assertEqual(len(self.records("agent_notifications")), notices)

    async def test_list_search_pagination_and_reply_do_not_expose_hidden_sources(self):
        team = self.team()
        outsider = self.manager.register_agent(Agent("Outsider", "Observer", self.client))
        secret = await self.manager.send_direct_message(outsider.agent_id, "Secret source", actor=self.root)
        public = await self.manager.send_team_message(team.team_id, "# Public\nReply", actor=self.root, reply_to=secret.message_id)
        self.assertIsNone((await self.manager.read_chat_message(public.message_id, actor=self.other)).reply_message_id)
        with self.assertRaises(PermissionError):
            self.manager.list_team_messages(team.team_id, actor=outsider)
        with self.assertRaises(PermissionError):
            await self.manager.send_team_message(team.team_id, "Forged reply", actor=self.other, reply_to=secret.message_id)
        await self.manager.send_team_message(team.team_id, "Second", actor=self.root)
        page = self.manager.list_team_messages(team.team_id, actor=self.other, limit=1)
        self.assertEqual(page.total_count, 2)
        self.assertNotIn("sequence", page.model_dump_json())
        next_page = self.manager.list_team_messages(team.team_id, actor=self.other, limit=1, cursor=page.next_cursor)
        self.assertEqual(len(next_page.items), 1)
        with self.assertRaises(ToolArgumentError):
            self.manager.list_team_messages(team.team_id, actor=self.root, cursor=page.next_cursor)

    async def test_failed_read_commit_does_not_return_body_or_change_read_state(self):
        item = await self.manager.send_direct_message(self.other.agent_id, "Body", actor=self.root)
        before = self.manager._records.snapshot()
        with patch.object(self.manager._records, "commit", side_effect=RuntimeError("Injected failure")):
            with self.assertRaisesRegex(RuntimeError, "Injected"):
                await self.manager.read_chat_message(item.message_id, actor=self.other)
        self.assertEqual(before, self.manager._records.snapshot())

    async def test_archive_closes_membership_and_preserves_inspection_and_personal_controls(self):
        team = self.team()
        item = await self.manager.send_team_message(team.team_id, "Archive evidence", actor=self.root)
        await self.manager.close_team_conversation(team.team_id)
        self.assertFalse(team.members)
        self.assertEqual(team._lifecycle_state, "dissolved")
        self.assertNotIn(team.team_id, self.manager.list_entities(entity_type="agent_team").model_dump_json())
        self.assertTrue((await self.manager.read_chat_message(item.message_id, actor=self.other)).frozen)
        await self.manager.control_chat_message("delete_message", item.message_id, actor=self.other)
        await self.manager.control_chat_message("restore_message", item.message_id, actor=self.other)
        with self.assertRaises(PermissionError):
            await self.manager.send_team_message(team.team_id, "Cannot publish", actor=self.root)
        with self.assertRaises(ValueError):
            self.manager.create_agent_team(team, parent=team, member_configs={"A": {"model": "fixture"}, "B": {"model": "fixture"}, "C": {"model": "fixture"}})
        from ai_team_team.core.activity.contracts import AgentTeamScope
        with self.assertRaises(PermissionError):
            await self.manager.activate_agent(self.other.agent_id, scope=AgentTeamScope(team_id=team.team_id))
        await self.manager.save_state()
        await self.manager.load_state(self.path)
        owner = self.manager._agents_by_id[self.other.agent_id]
        self.assertTrue(self.manager.list_team_messages(team.team_id, actor=owner).items[0].frozen)
