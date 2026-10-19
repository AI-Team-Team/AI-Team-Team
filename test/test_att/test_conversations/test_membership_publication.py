"""Shared-person lifecycle locks and recipient-safe membership rollback."""

import asyncio
import threading
from unittest.mock import patch

from ai_team_team import Agent
from test.test_att.test_autonomous_activity_phase0._fixtures import AgentIdentitySnapshot
from ._support import ChatTestCase


class MembershipPublicationTests(ChatTestCase):
    async def test_a_queued_invocation_cannot_block_its_owners_chat_lifecycle_gate(self):
        entered = asyncio.Event()

        async def queued():
            entered.set()
            async with self.root.invocation_guard():
                return "Later invocation"

        async with self.root.invocation_guard():
            waiter = asyncio.create_task(queued())
            try:
                await entered.wait()
                await asyncio.sleep(0)
                result = await asyncio.wait_for(self.manager.send_direct_message(self.other.agent_id,
                    "Current invocation can publish", actor=self.root), 10)
                self.assertEqual(result.status, "DELIVERED")
            finally:
                waiter.cancel()
                await asyncio.gather(waiter, return_exceptions=True)

    async def test_join_and_retirement_are_serialized_without_changing_owned_fields(self):
        team = self.team()
        person = self.manager.register_agent(Agent("Joining", "Researcher", self.client))
        identity = AgentIdentitySnapshot.capture(person, self.manager)
        await self.manager.save_state()
        entered, release = threading.Event(), threading.Event()
        store = self.manager._persistence._store(self.path)
        original = store.write

        def slow(snapshot):
            entered.set()
            if not release.wait(10):
                raise TimeoutError("The test did not release its relationship writer.")
            return original(snapshot)

        with patch.object(store, "write", slow):
            joining = asyncio.create_task(self.manager._messaging.replace_members(team,
                [*team.members, person], actor=self.root))
            retirement = None
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 5))
                self.assertNotIn(person, team.members)
                retirement = asyncio.create_task(self.manager.retire_agent(person.agent_id, "archive"))
                await asyncio.sleep(0)
                self.assertFalse(retirement.done())
            finally:
                release.set()
            await joining
            with self.assertRaisesRegex(ValueError, "still belongs"):
                await retirement
        self.assertEqual(AgentIdentitySnapshot.capture(person, self.manager), identity)
        self.assertIn(person, team.members)

    async def test_failed_relationship_mail_rolls_back_only_its_own_appended_message(self):
        team = self.team()
        before = list(self.other.agent_inbox)

        async def fail(*_records, **_kwargs):
            self.manager._inbox.notify(self.other.agent_id, "independent_notice", {"source": "another producer"})
            raise RuntimeError("Injected membership failure")

        with patch.object(self.manager._records, "commit", fail):
            with self.assertRaisesRegex(RuntimeError, "membership failure"):
                await self.manager._messaging.replace_members(team, [member for member in team.members if member is not self.other],
                    actor=self.root, mail_specs=((self.other.agent_id, "staged_membership_notice", {}),))
        self.assertIn(self.other, team.members)
        self.assertEqual(self.other.agent_inbox[:len(before)], before)
        self.assertEqual([mail["message_type"] for mail in self.other.agent_inbox[len(before):]], ["independent_notice"])
