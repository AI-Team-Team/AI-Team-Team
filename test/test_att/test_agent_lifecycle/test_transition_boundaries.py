"""Restore and retained death cannot publish over each other's identities."""

import asyncio
from pathlib import Path
from unittest.mock import Mock, patch

from ai_team_team import Agent, StateRestoreError
from ai_team_team.core.exceptions import RuntimeAdmissionClosedError
from ai_team_team.core.manager.agent_lifecycle import death
from ai_team_team.core.manager.restore import preparation
from test.test_att.test_agent_activity._support import ActivityTestCase


class LifecycleTransitionTests(ActivityTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.manager.config.model_token_limits["fixture"] = 0
        self.manager._activity.schedule_notice = Mock()
        self.person = self.manager.register_agent(Agent("Person", "Researcher", self.client))
        self.team = self.manager.bootstrap_agent_team(self.root, existing_members=[self.person],
            member_configs={"Peer1": {"model": "fixture"}, "Peer2": {"model": "fixture"}})
        self.path = str(Path(self.workspace.name) / "lifecycle.sqlite")
        await self.manager.save_state(self.path)

    async def assert_waiting_death_blocks_restore(self, *, direct=False):
        state = await self.manager._persistence.read(self.path, reconcile=False) if direct else None
        original_root, original_library = self.manager.root_ai, self.team.doc_library
        await self.team.state_lock.acquire()
        dying = asyncio.create_task(self.manager.mark_agent_dead(self.person.agent_id, confirm=True))
        try:
            async with asyncio.timeout(10):
                while self.person.agent_id not in self.manager._agent_registry.lifecycle_pending:
                    await asyncio.sleep(0)
            self.assertFalse(self.person.lifecycle_lock.locked())
            with self.assertRaisesRegex(StateRestoreError, "lifecycle transition"):
                if direct:
                    await self.manager._apply_state_snapshot(state)
                else:
                    await self.manager.load_state(self.path)
            self.assertIs(self.manager.root_ai, original_root)
            self.assertIs(self.manager.teams[self.team.team_id], self.team)
            self.assertIs(self.manager._agents_by_id[self.person.agent_id], self.person)
            self.assertIs(self.manager.libraries[original_library.lib_id], original_library)
            self.assertFalse(self.records("publication_manifests"))
        finally:
            self.team.state_lock.release()
            await asyncio.wait_for(dying, 10)
        self.assertEqual(self.person.lifecycle_state, "dead")
        self.assertEqual(len(self.team.members), 2)
        self.assertFalse(self.client.requests)

    async def test_load_rejects_a_death_waiting_for_the_team_lock(self):
        await self.assert_waiting_death_blocks_restore()

    async def test_snapshot_publication_rejects_a_death_waiting_for_the_team_lock(self):
        await self.assert_waiting_death_blocks_restore(direct=True)

    async def test_load_rejects_an_admitted_death_before_its_lifecycle_fence(self):
        entered, release = asyncio.Event(), asyncio.Event()
        original = death._transition
        async def delayed(*args, **kwargs):
            entered.set()
            await release.wait()
            return await original(*args, **kwargs)
        with patch.object(death, "_transition", delayed):
            dying = asyncio.create_task(self.manager.mark_agent_dead(self.person.agent_id, confirm=True))
            try:
                await asyncio.wait_for(entered.wait(), 10)
                self.assertFalse(self.manager._agent_registry.lifecycle_pending)
                self.assertIn(self.person.agent_id, self.manager._agent_registry.death_tasks)
                with self.assertRaisesRegex(StateRestoreError, "lifecycle transition"):
                    await self.manager.load_state(self.path)
                self.assertIs(self.manager._agents_by_id[self.person.agent_id], self.person)
            finally:
                release.set()
                await asyncio.wait_for(dying, 10)

    async def test_death_admission_rejects_an_already_started_restore(self):
        entered, release = asyncio.Event(), asyncio.Event()
        original = preparation.prepare_domain_recovery
        async def delayed(*args, **kwargs):
            entered.set()
            await release.wait()
            return await original(*args, **kwargs)
        with patch.object(preparation, "prepare_domain_recovery", delayed):
            loading = asyncio.create_task(self.manager.load_state(self.path))
            try:
                await asyncio.wait_for(entered.wait(), 10)
                with self.assertRaises(RuntimeAdmissionClosedError):
                    await self.manager.mark_agent_dead(self.person.agent_id, confirm=True)
                self.assertFalse(self.manager._agent_registry.lifecycle_pending)
                self.assertFalse(self.manager._agent_registry.death_tasks)
            finally:
                release.set()
                await asyncio.wait_for(loading, 10)
        self.assertEqual(self.manager._agents_by_id[self.person.agent_id].lifecycle_state, "active")
        self.assertFalse(self.client.requests)
