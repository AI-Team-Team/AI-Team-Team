"""Withdrawing a lifecycle fence resumes original timers and addressed arrivals."""

import asyncio
from unittest.mock import Mock, patch

from ai_team_team import Agent, StatePersistenceError
from ai_team_team.core.activity.contracts import SuppressionPreference, WakeDuration
from test.test_att.test_agent_activity._support import ActivityTestCase, call, idle


class LifecycleTimerTests(ActivityTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.manager.register_runtime_clock(self.clock)
        self.person = self.manager.register_agent(Agent("Person", "Researcher", self.client))

    async def sleeping_person(self):
        self.steps(call("set_activity_intent", {"intent": {"kind": "sleep", "countdown": {"minutes": 5}}}), idle())
        admitted = await self.manager.activate_agent(self.person.agent_id)
        await self.wait(admitted, "sleep")

    async def expire_during_death_commit(self, *, reject):
        await self.sleeping_person()
        entered, release = asyncio.Event(), asyncio.Event()
        original = self.manager._records.commit
        async def commit(records, **kwargs):
            if str(kwargs.get("operation_id", "")).startswith("DEATH-"):
                entered.set()
                await release.wait()
                if reject:
                    raise StatePersistenceError("Rejected retained-death receipt")
            return await original(records, **kwargs)
        with patch.object(self.manager._records, "commit", commit):
            dying = asyncio.create_task(self.manager.mark_agent_dead(self.person.agent_id, confirm=True))
            try:
                await asyncio.wait_for(entered.wait(), 10)
                timer = self.manager._activity.timers[self.person.agent_id]
                self.clock.advance(300)
                await asyncio.wait_for(timer, 10)
                self.assertEqual(len(self.client.requests), 1)
            finally:
                release.set()
                if reject:
                    with self.assertRaises(StatePersistenceError):
                        await asyncio.wait_for(dying, 10)
                else:
                    await asyncio.wait_for(dying, 10)

    async def test_rejected_death_rearms_an_expired_sleep_without_resetting_its_deadline(self):
        await self.expire_during_death_commit(reject=True)
        self.assertEqual(self.person.lifecycle_state, "active")
        self.assertFalse(self.manager._agent_registry.lifecycle_pending)
        async with asyncio.timeout(10):
            while self.manager.inspect_agent_activity(self.person.agent_id).intent != "idle":
                await asyncio.sleep(0)
        await self.settle()
        self.assertEqual(self.manager.inspect_agent_activity(self.person.agent_id).intent, "idle")
        self.assertEqual(self.records("sleep_plans")[0].values["status"], "expired")
        self.assertEqual(len(self.client.requests), 2)

    async def test_committed_death_never_rearms_the_expired_sleep(self):
        await self.expire_during_death_commit(reject=False)
        await self.settle()
        self.assertEqual(self.person.lifecycle_state, "dead")
        self.assertNotIn(self.person.agent_id, self.manager._activity.timers)
        self.assertEqual(self.records("sleep_plans")[0].values["status"], "cancelled")
        self.assertEqual(len(self.client.requests), 1)

    async def test_rejected_death_resumes_timed_suppression_expiration(self):
        self.manager._activity.schedule_notice = Mock()
        team = self.manager.bootstrap_agent_team(self.root, existing_members=[self.person],
            member_configs={"Peer1": {"model": "fixture"}, "Peer2": {"model": "fixture"}})
        preference = await self.manager.set_notification_suppression(
            SuppressionPreference(scope="all", countdown=WakeDuration(minutes=5)), actor=self.person)
        original = self.manager._records.commit
        async def reject(records, **kwargs):
            if str(kwargs.get("operation_id", "")).startswith("DEATH-"):
                raise StatePersistenceError("Rejected retained-death receipt")
            return await original(records, **kwargs)
        await team.state_lock.acquire()
        with patch.object(self.manager._records, "commit", reject):
            dying = asyncio.create_task(self.manager.mark_agent_dead(self.person.agent_id, confirm=True))
            try:
                async with asyncio.timeout(10):
                    while self.person.agent_id not in self.manager._agent_registry.lifecycle_pending:
                        await asyncio.sleep(0)
                timer = self.manager._activity.suppression_timers[preference["preference_id"]]
                self.clock.advance(300)
                await asyncio.wait_for(timer, 10)
            finally:
                team.state_lock.release()
                with self.assertRaises(StatePersistenceError):
                    await asyncio.wait_for(dying, 10)
        async with asyncio.timeout(10):
            while True:
                row = self.manager._records.index[("notification_suppression", (preference["preference_id"],))]
                if row.values["status"] == "expired":
                    break
                await asyncio.sleep(0)
        self.assertEqual(row.values["status"], "expired")
        self.assertEqual(row.values["remaining_seconds"], 0)
        self.assertEqual(self.person.lifecycle_state, "active")
        self.assertFalse(self.client.requests)

    async def test_rejected_death_rechecks_protected_arrivals_received_behind_its_fence(self):
        owner = self.person.agent_id
        team = self.manager.bootstrap_agent_team(self.root, existing_members=[self.person],
            member_configs={"Peer1": {"model": "fixture"}, "Peer2": {"model": "fixture"}})
        source = self.manager.create_agent_team(self.root)
        original = self.manager._records.commit
        async def reject(records, **kwargs):
            if str(kwargs.get("operation_id", "")).startswith("DEATH-"):
                raise StatePersistenceError("Rejected retained-death receipt")
            return await original(records, **kwargs)
        original_notice = self.manager._activity.schedule_notice
        def schedule_owner(notification_id):
            notice = self.manager._records.index[("agent_notifications", (notification_id,))]
            if notice.values["agent_id"] == owner:
                original_notice(notification_id)
        self.manager._activity.schedule_notice = Mock(side_effect=schedule_owner)
        self.steps(idle())
        await team.state_lock.acquire()
        with patch.object(self.manager._records, "commit", reject):
            dying = asyncio.create_task(self.manager.mark_agent_dead(owner, confirm=True))
            try:
                async with asyncio.timeout(10):
                    while owner not in self.manager._agent_registry.lifecycle_pending:
                        await asyncio.sleep(0)
                # A real permission transaction publishes its protected notice,
                # although this person's admission is temporarily fenced.
                await self.manager._library_service.change_permission(source, source.doc_library.lib_id,
                    "/", team.team_id, "READ")
                self.assertFalse(self.client.requests)
            finally:
                team.state_lock.release()
                with self.assertRaises(StatePersistenceError):
                    await asyncio.wait_for(dying, 10)
        await self.settle()
        self.assertEqual(self.person.lifecycle_state, "active")
        self.assertTrue(any(row.values["status"] == "presented" for row in self.records("notification_claims")))
        self.assertEqual(sum(row.values["agent_id"] == owner for row in self.records("model_requests")), 1)
