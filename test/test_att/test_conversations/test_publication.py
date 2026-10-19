"""Receipt-bound publication and three independent information surfaces."""

import asyncio

from ai_team_team import ToolBusinessError
from ._support import ChatTestCase


class PublicationTests(ChatTestCase):
    async def test_direct_send_is_atomic_idempotent_and_directionally_limited(self):
        first = await self.manager.send_direct_message(self.other.agent_id, "# Hello\nBody", actor=self.root, operation_key="first")
        again = await self.manager.send_direct_message(self.other.agent_id, "# Hello\nBody", actor=self.root, operation_key="first")
        self.assertEqual(first, again)
        self.assertEqual(first.durability, "durable")
        self.assertEqual(len(self.records("chat_messages")), 1)
        results = await asyncio.gather(*(self.manager.send_direct_message(self.other.agent_id, str(index), actor=self.root)
            for index in range(3)), return_exceptions=True)
        self.assertEqual(sum(isinstance(item, ToolBusinessError) for item in results), 1)
        self.assertEqual(self.manager.inspect_direct_relationship(self.other.agent_id, actor=self.root).remaining_messages, 0)
        self.assertEqual(self.manager.inspect_direct_relationship(self.root.agent_id, actor=self.other).remaining_messages, 3)
        await self.manager.send_direct_message(self.root.agent_id, "Reverse direction", actor=self.other)
        self.assertEqual(len(self.manager.list_direct_messages(self.root.agent_id, actor=self.other).items), 4)
        self.assertFalse(self.root.agent_inbox)

    async def test_team_source_has_personal_views_and_preview_never_marks_read(self):
        team = self.team()
        result = await self.manager.send_team_message(team.team_id, "```md\n# Code\n```\n# Heading\nBody", actor=self.root)
        page = self.manager.list_team_messages(team.team_id, actor=self.other)
        self.assertEqual(page.items[0].title, "Heading")
        self.assertEqual(page.items[0].message_id, result.message_id)
        self.assertEqual(page.unread_count, 1)
        self.assertEqual(len(self.records("chat_personal_views")), len(team.members))
        self.assertFalse(self.other.agent_inbox)
        self.assertFalse(self.manager.broker.peer_messages)
        self.manager.config.conversations.title_max_characters = 1
        self.assertEqual(self.manager.list_team_messages(team.team_id, actor=self.other).items[0].title, "Heading")
