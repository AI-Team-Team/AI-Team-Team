"""Recovery cannot discard admitted countdown work or reset a rejected restore's deadlines."""

import asyncio
from unittest.mock import patch

from ai_team_team import StateRestoreError
from ai_team_team.core.activity.contracts import SuppressionPreference, WakeDuration
from ai_team_team.core.manager.restore import preparation
from test.test_att.test_agent_activity._support import ActivityTestCase, call, idle


class CountdownHandoffTests(ActivityTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        await self.manager.close()
        self.manager = self.make_manager(self.root, durable=True)
        self.manager.register_runtime_clock(self.clock)
        self.manager.config.activity.countdown_checkpoint_seconds = 3600

    async def countdown(self, kind):
        if kind == "sleep":
            self.steps(call("set_activity_intent", {"intent": {"kind": "sleep", "countdown": {"minutes": 5}}}), idle())
            admission = await self.manager.activate_agent(self.root.agent_id)
            await self.wait(admission, "sleep")
            await self.settle()
            identifier = self.root.agent_id
            timer = self.manager._activity.timers[identifier]
        else:
            result = await self.manager.set_notification_suppression(
                SuppressionPreference(scope="all", countdown=WakeDuration(minutes=5)), actor=self.root)
            identifier = result["preference_id"]
            timer = self.manager._activity.suppression_timers[identifier]
        await self.manager.save_state()
        return identifier, timer

    async def assert_expired(self, kind, identifier, timer):
        await asyncio.wait_for(timer, 10)
        if kind == "sleep":
            async with asyncio.timeout(10):
                while self.manager.inspect_agent_activity(identifier).intent != "idle":
                    await asyncio.sleep(0)
            await self.settle()
            self.assertEqual(self.records("sleep_plans")[0].values["status"], "expired")
            self.assertEqual(len(self.client.requests), 2)
        else:
            row = self.manager._records.index[("notification_suppression", (identifier,))]
            self.assertEqual(row.values["status"], "expired")
            self.assertEqual(row.values["remaining_seconds"], 0)
            self.assertFalse(self.client.requests)
        self.assertFalse(self.manager._activity.countdown_handoffs)

    def restore_wait_barrier(self, timer):
        waiting = asyncio.Event()
        original = self.manager._activity.restore_finished.wait

        async def wait():
            if asyncio.current_task() is timer:
                waiting.set()
            return await original()

        return waiting, wait

    async def lock_handoff_excludes_restore(self, kind):
        identifier, timer = await self.countdown(kind)
        original_root = self.manager.root_ai
        await self.manager._activity.lock.acquire()
        held = True
        try:
            self.clock.advance(300)
            async with asyncio.timeout(10):
                while not self.manager._activity.countdown_handoffs:
                    await asyncio.sleep(0)
            self.assertFalse(timer.done())
            # Lock.release wakes its waiter later. The handoff must still own
            # the old generation during this unlocked scheduling interval.
            self.manager._activity.lock.release()
            held = False
            self.assertFalse(self.manager._activity.lock.locked())
            with self.assertRaises(StateRestoreError):
                await self.manager.load_state(self.manager.db_path)
            self.assertIs(self.manager.root_ai, original_root)
            self.assertFalse(self.records("publication_manifests"))
            await self.assert_expired(kind, identifier, timer)
        finally:
            if held:
                self.manager._activity.lock.release()

    async def test_sleep_expiry_owns_its_generation_while_the_activity_lock_is_queued(self):
        await self.lock_handoff_excludes_restore("sleep")

    async def test_suppression_expiry_owns_its_generation_while_the_activity_lock_is_queued(self):
        await self.lock_handoff_excludes_restore("suppression")

    async def failed_restore_releases_expiry(self, kind, *, cancel=False):
        identifier, timer = await self.countdown(kind)
        entered, release = asyncio.Event(), asyncio.Event()
        original_root = self.manager.root_ai
        original_records = self.manager._records.snapshot()
        original = preparation.prepare_domain_recovery
        waiting, wait_restore = self.restore_wait_barrier(timer)

        async def prepare(*args, **kwargs):
            await original(*args, **kwargs)
            entered.set()
            await release.wait()
            raise StateRestoreError("Injected detached recovery rejection")

        with patch.object(preparation, "prepare_domain_recovery", prepare), patch.object(
                self.manager._activity.restore_finished, "wait", wait_restore):
            loading = asyncio.create_task(self.manager.load_state(self.manager.db_path))
            try:
                await asyncio.wait_for(entered.wait(), 10)
                self.clock.advance(300)
                await asyncio.wait_for(waiting.wait(), 10)
                self.assertFalse(timer.done())
                self.assertFalse(self.manager._activity.countdown_handoffs)
                self.assertEqual(self.manager._records.snapshot(), original_records)
                if cancel:
                    loading.cancel()
                release.set()
                # Once accepted, a concrete restore error outranks observer
                # cancellation; neither may replace this manager's countdown.
                with self.assertRaises(StateRestoreError):
                    await asyncio.wait_for(loading, 10)
                self.assertIs(self.manager.root_ai, original_root)
                await self.assert_expired(kind, identifier, timer)
            finally:
                release.set()
                await asyncio.gather(loading, return_exceptions=True)

    async def test_rejected_recovery_releases_the_original_expired_sleep(self):
        await self.failed_restore_releases_expiry("sleep")

    async def test_rejected_recovery_releases_the_original_expired_suppression(self):
        await self.failed_restore_releases_expiry("suppression")

    async def test_cancelled_observer_does_not_lose_expiry_when_recovery_rejects(self):
        await self.failed_restore_releases_expiry("sleep", cancel=True)

    async def test_successful_publication_uses_one_new_timer_and_discards_the_old_one(self):
        owner, timer = await self.countdown("sleep")
        entered, release = asyncio.Event(), asyncio.Event()
        original = preparation.prepare_domain_recovery
        old_root = self.manager.root_ai
        waiting, wait_restore = self.restore_wait_barrier(timer)

        async def prepare(*args, **kwargs):
            result = await original(*args, **kwargs)
            entered.set()
            await release.wait()
            return result

        with patch.object(preparation, "prepare_domain_recovery", prepare), patch.object(
                self.manager._activity.restore_finished, "wait", wait_restore):
            loading = asyncio.create_task(self.manager.load_state(self.manager.db_path))
            try:
                await asyncio.wait_for(entered.wait(), 10)
                self.clock.advance(300)
                await asyncio.wait_for(waiting.wait(), 10)
                self.assertEqual(len(self.client.requests), 1)
                release.set()
                await asyncio.wait_for(loading, 10)
                await asyncio.gather(timer, return_exceptions=True)
                self.assertIsNot(self.manager.root_ai, old_root)
                self.assertEqual(self.manager.root_ai.agent_id, owner)
                async with asyncio.timeout(10):
                    while self.manager.inspect_agent_activity(owner).intent != "idle":
                        await asyncio.sleep(0)
                await self.settle()
                self.assertEqual(len(self.client.requests), 2)
                self.assertTrue(timer.cancelled())
            finally:
                release.set()
                await asyncio.gather(loading, return_exceptions=True)

    async def test_checkpoint_sampling_handoff_also_excludes_restore(self):
        self.manager.config.activity.countdown_checkpoint_seconds = 30
        await self.countdown("sleep")
        await self.manager._activity.lock.acquire()
        held = True
        try:
            self.clock.advance(30)
            async with asyncio.timeout(10):
                while not self.manager._activity.countdown_handoffs:
                    await asyncio.sleep(0)
            self.manager._activity.lock.release()
            held = False
            with self.assertRaises(StateRestoreError):
                await self.manager.load_state(self.manager.db_path)
            async with asyncio.timeout(10):
                while self.records("sleep_plans")[0].values["remaining_seconds"] != 270:
                    await asyncio.sleep(0)
            self.assertFalse(self.manager._activity.fatal_errors)
            self.assertEqual(self.manager.inspect_agent_activity(self.root.agent_id).intent, "sleep")
        finally:
            if held:
                self.manager._activity.lock.release()
