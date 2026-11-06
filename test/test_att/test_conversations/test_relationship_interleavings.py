"""Seeded histories preserve current authority, quota, and stable ownership."""

import asyncio
from unittest.mock import patch

from ai_team_team import ToolBusinessError
from test.test_att.test_runtime_contracts._fixtures import LogicalClock

from ._relationship_schedules import exercise_relationship_schedule
from ._support import ChatTestCase


class RelationshipScheduleTests(ChatTestCase):
    async def test_concurrent_sends_and_edits_share_the_same_directional_allowance(self):
        first = await self.manager.send_direct_message(self.other.agent_id, "Initial", actor=self.root)
        operations = [self.manager.edit_chat_message(first.message_id, f"Edit {index}", actor=self.root) for index in range(3)]
        operations += [self.manager.send_direct_message(self.other.agent_id, f"New {index}", actor=self.root) for index in range(3)]
        results = await asyncio.gather(*operations, return_exceptions=True)
        failures = [result for result in results if isinstance(result, BaseException)]
        self.assertEqual(len(failures), 4)
        self.assertTrue(all(isinstance(result, ToolBusinessError) for result in failures))
        self.assertEqual(self.manager.inspect_direct_relationship(self.other.agent_id, actor=self.root).remaining_messages, 0)
        self.assertEqual(self.manager.inspect_direct_relationship(self.root.agent_id, actor=self.other).remaining_messages, 3)
        self.assertEqual(len(self.records("chat_revisions")), 3)

    async def test_old_generation_and_friendship_era_edits_charge_the_current_period(self):
        old = await self.manager.send_direct_message(self.other.agent_id, "Stranger era", actor=self.root)
        invitation = await self.manager.request_friendship(self.other.agent_id, actor=self.root)
        await self.manager.respond_friendship(invitation.request_id, "accept", actor=self.other)
        friendly = await self.manager.send_direct_message(self.other.agent_id, "Friendship era", actor=self.root)
        await self.manager.control_direct_relationship(self.other.agent_id, "remove_friendship", actor=self.root)
        await self.manager.edit_chat_message(old.message_id, "Current delivery one", actor=self.root)
        await self.manager.edit_chat_message(friendly.message_id, "Current delivery two", actor=self.root)
        await self.manager.send_direct_message(self.other.agent_id, "Current delivery three", actor=self.root)
        with self.assertRaises(ToolBusinessError):
            await self.manager.edit_chat_message(old.message_id, "Forbidden fourth delivery", actor=self.root)
        view = self.manager.inspect_direct_relationship(self.other.agent_id, actor=self.root)
        self.assertEqual((view.generation, view.friendship, view.remaining_messages), (2, False, 0))
        self.assertEqual(self.manager.list_friendship_requests(actor=self.root)[0].status, "accepted")

    async def test_failed_edit_preserves_allowance_reminders_and_withdrawal_deadline(self):
        clock = LogicalClock()
        self.addCleanup(clock.close)
        self.manager.register_runtime_clock(clock)
        self.manager.config.conversations.withdrawal_window_seconds = 10
        message = await self.manager.send_direct_message(self.other.agent_id, "Accepted source", actor=self.root)
        before = self.manager._records.snapshot()
        clock.advance(11)
        with patch.object(self.manager._persistence, "submit", side_effect=OSError("Synthetic rejected write")):
            with self.assertRaises(OSError):
                await self.manager.edit_chat_message(message.message_id, "Unaccepted revision", actor=self.root)
        self.assertEqual(self.manager._records.snapshot(), before)
        self.assertEqual(self.manager.inspect_direct_relationship(self.other.agent_id, actor=self.root).remaining_messages, 2)
        with self.assertRaises(ToolBusinessError):
            await self.manager.withdraw_chat_message(message.message_id, actor=self.root)

    async def test_seeded_relationship_periods_edits_and_receipt_replays(self):
        await exercise_relationship_schedule(self, 20261029, 32, restore_every=8)
