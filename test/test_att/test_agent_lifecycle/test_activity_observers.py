"""Death settles personal observers even if their admitted worker never starts."""

import asyncio

from ai_team_team import Agent
from test.test_att.test_agent_activity._support import ActivityTestCase, idle
from test.test_att.test_runtime_contracts._fixtures import AsyncBarrier, ModelStep


class LifecycleObserverTests(ActivityTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.manager.config.activity.max_concurrent_activities = 1
        self.person = self.manager.register_agent(Agent("QueuedPerson", "Researcher", self.client))
        self.barrier = AsyncBarrier()
        self.addCleanup(self.barrier.release)

    async def occupy_worker(self):
        self.client.steps.append(ModelStep(idle(), self.barrier))
        await self.manager.activate_agent(self.root.agent_id)
        await asyncio.wait_for(self.barrier.wait_entered(), 10)

    async def test_queued_death_fails_all_checkpoint_and_interaction_waiters(self):
        await self.occupy_worker()
        admission = await self.manager.activate_agent(self.person.agent_id)
        observers = [asyncio.create_task(self.manager.wait_for_activity_checkpoint(admission.admission_id))
                     for _ in range(2)]
        interaction = asyncio.create_task(self.manager.execute_agent_interaction(self.person, "Explicitly answer this instruction"))
        observers.append(interaction)
        try:
            async with asyncio.timeout(10):
                while (len(self.manager._activity.waiters.get(admission.admission_id, ())) != 2
                        or not self.manager._activity.sessions[self.person.agent_id].interaction_waiters):
                    await asyncio.sleep(0)
            session = self.manager._activity.sessions[self.person.agent_id]
            self.assertTrue(session.queued)
            self.assertFalse(session.running)
            await self.manager.mark_agent_dead(self.person.agent_id, confirm=True)
            outcomes = await asyncio.wait_for(asyncio.gather(*observers, return_exceptions=True), 10)
            self.assertTrue(all(isinstance(error, asyncio.CancelledError) for error in outcomes))
            self.assertEqual(self.person.lifecycle_state, "dead")
            self.assertNotIn(admission.admission_id, self.manager._activity.waiters)
            self.assertEqual(len(self.client.requests), 1)
        finally:
            for observer in observers:
                observer.cancel()
            await asyncio.gather(*observers, return_exceptions=True)
            self.barrier.release()

    async def test_death_settles_observers_of_earlier_owned_admissions(self):
        self.steps(idle())
        old = await self.manager.activate_agent(self.person.agent_id)
        completed = await self.wait(old)
        await self.settle()
        await self.occupy_worker()
        current = await self.manager.activate_agent(self.person.agent_id)
        old_observer = asyncio.create_task(self.manager.wait_for_activity_checkpoint(old.admission_id, intent="continuing"))
        new_observer = asyncio.create_task(self.manager.wait_for_activity_checkpoint(current.admission_id))
        try:
            async with asyncio.timeout(10):
                while not all(identifier in self.manager._activity.waiters for identifier in (old.admission_id, current.admission_id)):
                    await asyncio.sleep(0)
            await self.manager.mark_agent_dead(self.person.agent_id, confirm=True)
            for observer in (old_observer, new_observer):
                with self.assertRaises(asyncio.CancelledError):
                    await asyncio.wait_for(observer, 10)
            # A factual checkpoint that was already completed is still readable.
            self.assertEqual(await self.manager.wait_for_activity_checkpoint(old.admission_id), completed)
        finally:
            old_observer.cancel()
            new_observer.cancel()
            await asyncio.gather(old_observer, new_observer, return_exceptions=True)
            self.barrier.release()

    async def test_cancelled_observer_does_not_break_queued_death_or_other_waiters(self):
        await self.occupy_worker()
        admission = await self.manager.activate_agent(self.person.agent_id)
        observer = asyncio.create_task(self.manager.wait_for_activity_checkpoint(admission.admission_id))
        try:
            async with asyncio.timeout(10):
                while admission.admission_id not in self.manager._activity.waiters:
                    await asyncio.sleep(0)
            observer.cancel()
            await asyncio.gather(observer, return_exceptions=True)
            await self.manager.mark_agent_dead(self.person.agent_id, confirm=True)
            with self.assertRaises(asyncio.CancelledError):
                await self.manager.wait_for_activity_checkpoint(admission.admission_id)
            self.assertFalse(self.manager._activity.waiters)
        finally:
            observer.cancel()
            await asyncio.gather(observer, return_exceptions=True)
            self.barrier.release()
