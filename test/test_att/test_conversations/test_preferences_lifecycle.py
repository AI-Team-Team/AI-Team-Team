"""Personal preferences admit only the same still-active identity after waiting."""

import asyncio

from ._support import ChatTestCase


class PreferenceLifecycleTests(ChatTestCase):
    async def test_waiting_preferences_reject_an_actor_retired_by_the_lifecycle_owner(self):
        async with self.other.lifecycle_lock:
            changing = asyncio.create_task(self.manager.set_chat_details(actor=self.other, team_details=False))
            await asyncio.sleep(0)
            self.assertFalse(changing.done())
            await self.manager._agent_registry.retire_locked(self.other.agent_id, "archive")
        with self.assertRaises(PermissionError):
            await changing
        self.assertFalse(self.records("chat_preferences"))
        self.assertFalse(self.records("chat_operations"))

    async def test_admitted_preferences_hold_the_lifecycle_gate_until_receipt(self):
        async with self.manager._activity.lock:
            changing = asyncio.create_task(self.manager.set_chat_details(actor=self.other, direct_details=False))
            await asyncio.sleep(0)
            self.assertTrue(self.other.lifecycle_lock.locked())
            retirement = asyncio.create_task(self.manager.retire_agent(self.other.agent_id, "archive"))
            await asyncio.sleep(0)
            self.assertFalse(retirement.done())
        self.assertEqual((await changing).status, "PREFERENCES_UPDATED")
        await retirement
        self.assertEqual(self.other.lifecycle_state, "archived")
        await self.manager.save_state()
        await self.manager.load_state(self.path)
        self.assertEqual(self.records("chat_preferences")[0].values["direct_details"], 0)
