"""History is retained independently from current pair-owned delivery authority."""

import asyncio
from unittest.mock import patch

from ai_team_team import ToolBusinessError
from ._support import ChatTestCase


class RelationshipTests(ChatTestCase):
    async def friendship(self):
        request = await self.manager.request_friendship(self.other.agent_id, actor=self.root)
        await self.manager.respond_friendship(request.request_id, "accept", actor=self.other)
        return request

    async def test_historical_acceptance_survives_removal_and_restore_without_restoring_authority(self):
        request = await self.friendship()
        await self.manager.send_direct_message(self.other.agent_id, "Retained history", actor=self.root)
        await self.manager.control_direct_relationship(self.other.agent_id, "remove_friendship", actor=self.root)
        stale = await self.manager.respond_friendship(request.request_id, "accept", actor=self.other)
        self.assertEqual(stale.status, "STALE_REQUEST")
        self.assertFalse(self.manager.inspect_direct_relationship(self.other.agent_id, actor=self.root).friendship)
        self.assertEqual(self.manager.list_friendship_requests(actor=self.root)[0].status, "accepted")
        await self.manager.save_state()
        await self.manager.load_state(self.path)
        root, other = self.manager.root_ai, self.manager._agents_by_id[self.other.agent_id]
        self.assertEqual(self.manager.list_friendship_requests(actor=root)[0].status, "accepted")
        self.assertEqual(self.manager.inspect_direct_relationship(other.agent_id, actor=root).generation, 2)
        new_request = await self.manager.request_friendship(other.agent_id, actor=root)
        self.assertNotEqual(new_request.request_id, request.request_id)
        await self.manager.respond_friendship(new_request.request_id, "accept", actor=other)
        self.assertTrue(self.manager.inspect_direct_relationship(other.agent_id, actor=root).friendship)

    async def test_blocks_are_independently_owned_and_only_final_clear_starts_a_new_period(self):
        request = await self.friendship()
        await self.manager.control_direct_relationship(self.other.agent_id, "block_agent", actor=self.root)
        await self.manager.control_direct_relationship(self.root.agent_id, "block_agent", actor=self.other)
        for sender, recipient in ((self.root, self.other), (self.other, self.root)):
            with self.assertRaises(ToolBusinessError):
                await self.manager.send_direct_message(recipient.agent_id, "Denied", actor=sender)
        await self.manager.control_direct_relationship(self.other.agent_id, "unblock_agent", actor=self.root)
        self.assertEqual(self.manager.inspect_direct_relationship(self.other.agent_id, actor=self.root).generation, 1)
        await self.manager.control_direct_relationship(self.root.agent_id, "unblock_agent", actor=self.other)
        relation = self.manager.inspect_direct_relationship(self.other.agent_id, actor=self.root)
        self.assertEqual(relation.generation, 2)
        self.assertFalse(relation.friendship)
        await self.manager.control_direct_relationship(self.root.agent_id, "unblock_agent", actor=self.other)
        self.assertEqual(self.manager.inspect_direct_relationship(self.other.agent_id, actor=self.root).generation, 2)
        self.assertEqual((await self.manager.respond_friendship(request.request_id, "accept", actor=self.other)).status, "STALE_REQUEST")

    async def test_crossed_requests_are_not_consent_and_cancellation_does_not_reset_allowance(self):
        await self.manager.send_direct_message(self.other.agent_id, "One", actor=self.root)
        first = await self.manager.request_friendship(self.other.agent_id, actor=self.root)
        same = await self.manager.request_friendship(self.other.agent_id, actor=self.root)
        self.assertEqual(first.request_id, same.request_id)
        await self.manager.request_friendship(self.root.agent_id, actor=self.other)
        self.assertFalse(self.manager.inspect_direct_relationship(self.other.agent_id, actor=self.root).friendship)
        await self.manager.respond_friendship(first.request_id, "cancel", actor=self.root)
        await self.manager.control_direct_relationship(self.other.agent_id, "remove_friendship", actor=self.root)
        relation = self.manager.inspect_direct_relationship(self.other.agent_id, actor=self.root)
        self.assertEqual((relation.generation, relation.remaining_messages), (1, 2))

    async def test_refusal_is_recipient_owned_and_requires_explicit_lifting(self):
        request = await self.manager.request_friendship(self.other.agent_id, actor=self.root)
        await self.manager.respond_friendship(request.request_id, "reject", actor=self.other)
        with self.assertRaises(ToolBusinessError):
            await self.manager.send_direct_message(self.other.agent_id, "Denied", actor=self.root)
        await self.manager.control_direct_relationship(self.other.agent_id, "lift_direct_refusal", actor=self.root)
        with self.assertRaises(ToolBusinessError):
            await self.manager.send_direct_message(self.other.agent_id, "Still denied", actor=self.root)
        await self.manager.control_direct_relationship(self.root.agent_id, "lift_direct_refusal", actor=self.other)
        await self.manager.send_direct_message(self.other.agent_id, "Allowed", actor=self.root)

    async def test_failed_write_does_not_consume_allowance_or_publish_an_arrival(self):
        await self.manager.save_state()
        before = self.manager._records.snapshot()
        with patch.object(self.manager._persistence, "submit", side_effect=RuntimeError("Injected writer failure")):
            with self.assertRaises(RuntimeError):
                await self.manager.send_direct_message(self.other.agent_id, "Not committed", actor=self.root)
        self.assertEqual(self.manager._records.snapshot(), before)
        self.assertEqual(self.manager.inspect_direct_relationship(self.other.agent_id, actor=self.root).remaining_messages, 3)
        self.assertFalse(self.records("chat_messages"))

    async def test_acceptance_racing_block_cannot_restore_friendship_through_block(self):
        request = await self.manager.request_friendship(self.other.agent_id, actor=self.root)
        await asyncio.gather(self.manager.respond_friendship(request.request_id, "accept", actor=self.other),
            self.manager.control_direct_relationship(self.other.agent_id, "block_agent", actor=self.root), return_exceptions=True)
        relation = self.manager.inspect_direct_relationship(self.other.agent_id, actor=self.root)
        self.assertTrue(relation.blocked_by_self)
        self.assertFalse(relation.friendship)
