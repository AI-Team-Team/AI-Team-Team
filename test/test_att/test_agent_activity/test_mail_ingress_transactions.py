"""Mail admission and rollback cover lifecycle waits and record preparation."""

import asyncio
from unittest.mock import patch

from ai_team_team import Agent, StatePersistenceError

from ._support import ActivityTestCase, idle


class MailIngressTransactionTests(ActivityTestCase):
    async def test_waiting_delivery_revalidates_a_retired_or_deleted_recipient(self):
        for policy in ("retain", "archive", "delete"):
            with self.subTest(policy=policy):
                recipient = self.manager.register_agent(Agent(policy, "Researcher", self.client))
                waiting = asyncio.Event()
                delivery = None
                original = self.manager._activity.lock.acquire

                async def acquire():
                    if asyncio.current_task() is delivery:
                        waiting.set()
                    return await original()

                with patch.object(self.manager._activity.lock, "acquire", acquire):
                    async with self.manager._activity.lock:
                        delivery = asyncio.create_task(self.manager.deliver_agent_mail(
                            recipient.agent_id, message_type="note", payload={}
                        ))
                        await asyncio.wait_for(waiting.wait(), 5)
                        await self.manager.retire_agent(
                            recipient.agent_id, policy=policy, confirm_delete=policy == "delete"
                        )
                    with self.assertRaises(PermissionError):
                        await asyncio.wait_for(delivery, 5)
                self.assertFalse(recipient.agent_inbox)
                self.assertFalse(self.records("agent_notifications"))
                self.assertFalse(self.manager._activity.activating)
        self.assertFalse(self.client.requests)

    async def test_every_postappend_preparation_failure_rolls_back_the_mail(self):
        for target in ("dirty", "records"):
            with self.subTest(target=target):
                owner = self.manager if target == "dirty" else self.manager._activity
                name = "_new_dirty_state" if target == "dirty" else "mail_records"
                with patch.object(owner, name, side_effect=ValueError("Synthetic capture failure")):
                    with self.assertRaisesRegex(ValueError, "Synthetic capture"):
                        await self.manager.deliver_agent_mail(
                            self.root.agent_id, message_type="note", payload={}
                        )
                self.assertFalse(self.root.agent_inbox)
                self.assertFalse(self.records("agent_notifications"))
                self.assertFalse(self.manager._activity.activating)

    async def test_rejected_or_cancelled_commit_leaves_no_unaccepted_source(self):
        for error in (StatePersistenceError("Synthetic failed mail commit"), asyncio.CancelledError()):
            with self.subTest(error=type(error).__name__):
                with patch.object(self.manager._records, "commit", side_effect=error):
                    with self.assertRaises(type(error)):
                        await self.manager.deliver_agent_mail(
                            self.root.agent_id, message_type="note", payload={}
                        )
                self.assertFalse(self.root.agent_inbox)
                self.assertFalse(self.records("agent_notifications"))
                self.assertFalse(self.manager._activity.activating)

    async def test_cancelled_observer_keeps_accepted_mail_and_its_dispatch(self):
        committed, release = asyncio.Event(), asyncio.Event()
        original = self.manager._records.commit

        async def commit(records, **kwargs):
            receipt = await original(records, **kwargs)
            if any(row.table_name == "agent_notifications" for row in records):
                committed.set()
                await release.wait()
            return receipt

        self.steps(idle())
        with patch.object(self.manager._records, "commit", commit):
            delivery = asyncio.create_task(self.manager.deliver_agent_mail(
                self.root.agent_id, message_type="note", payload={}
            ))
            try:
                await asyncio.wait_for(committed.wait(), 5)
                delivery.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await delivery
            finally:
                release.set()
                await asyncio.gather(delivery, return_exceptions=True)
        await self.settle()
        self.assertEqual(len(self.root.agent_inbox), 1)
        self.assertEqual(len(self.records("agent_notifications")), 1)
        self.assertEqual(self.records("notification_claims")[0].values["status"], "presented")
        self.assertEqual(len(self.client.requests), 1)
