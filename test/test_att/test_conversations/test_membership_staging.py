"""Pending membership identities and proposals never leak into ordinary saves."""

import asyncio
import json
import sqlite3
import threading
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from ai_team_team import Agent, StateRestoreError
from ai_team_team.core.manager.registrations import AgentRegistration
from ._support import ChatTestCase


class MembershipStagingTests(ChatTestCase):
    def proposal(self, team):
        team.proposals["staged-proposal"] = {
            "proposal_id": "staged-proposal", "action": "add", "target": "StagedMember",
            "status": "approved", "votes": {}, "initiator_type": "AT", "initiator_name": "AT",
            "initiator_agent_id": None, "rationale": "An approved membership change",
            "proposed_details": {"model": "fixture"},
        }

    async def prepared(self, count=1):
        async with asyncio.timeout(10):
            while len(self.manager._agent_registry.pending) != count or any(
                item.library is None for item in self.manager._agent_registry.pending.values()
            ):
                await asyncio.sleep(0)
        return tuple(self.manager._agent_registry.pending.values())

    async def test_parallel_full_save_and_cancel_preserve_only_committed_state(self):
        team = self.team()
        self.proposal(team)
        await self.manager.save_state()
        known = set(self.manager._agents_by_id)
        entered, release = asyncio.Event(), asyncio.Event()
        original_flush = self.manager.flush_state
        saving = None

        async def delayed_flush():
            if asyncio.current_task() is saving:
                entered.set()
                await release.wait()
            await original_flush()

        with patch.object(self.manager, "flush_state", delayed_flush):
            saving = asyncio.create_task(self.manager.save_state())
            await asyncio.wait_for(entered.wait(), 10)
            async with self.manager._activity.lock:
                changing = asyncio.create_task(self.manager._membership._apply_deferred_membership_changes(team))
                try:
                    (reservation,) = await self.prepared()
                    self.assertEqual(set(self.manager._agents_by_id), known)
                    self.assertNotIn("executed", team.proposals["staged-proposal"]["proposed_details"])
                    self.assertNotIn(reservation.agent.name, self.manager.list_entities().model_dump_json())
                    release.set()
                    await asyncio.wait_for(saving, 10)
                finally:
                    release.set()
                    changing.cancel()
                    await asyncio.gather(changing, return_exceptions=True)
        self.assertFalse(self.manager._agent_registry.pending)
        self.assertFalse(Path(reservation.library.root_dir).exists())
        with closing(sqlite3.connect(self.path)) as database:
            self.assertFalse(database.execute("SELECT agent_id FROM agents WHERE agent_id=?", (reservation.agent.agent_id,)).fetchall())
            details = database.execute("SELECT proposed_details FROM team_proposals WHERE proposal_id='staged-proposal'").fetchone()[0]
            self.assertNotIn("executed", json.loads(details))
        await self.manager.load_state(self.path)
        team = self.manager.teams[team.team_id]
        await self.manager._membership._apply_deferred_membership_changes(team)
        self.assertEqual(sum(member.role == "StagedMember" for member in team.members), 1)

    async def test_accepted_cancel_publishes_every_identity_and_skips_stale_proposal_snapshots(self):
        team = self.team()
        self.proposal(team)
        await self.manager.save_state()
        entered, release = threading.Event(), threading.Event()
        store = self.manager._persistence._store(self.path)
        original_write = store.write

        def slow(snapshot):
            entered.set()
            if not release.wait(10):
                raise TimeoutError("The test did not release the membership writer.")
            return original_write(snapshot)

        with patch.object(store, "write", slow):
            changing = asyncio.create_task(self.manager._membership._apply_deferred_membership_changes(team))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 5))
                (reservation,) = tuple(self.manager._agent_registry.pending.values())
                self.assertNotIn(reservation.agent.agent_id, self.manager._agents_by_id)
                self.assertNotIn("executed", team.proposals["staged-proposal"]["proposed_details"])
                with self.assertRaisesRegex(ValueError, "reserved"):
                    self.manager.register_agent(Agent(reservation.agent.name, "Conflicting", self.client))
                self.manager._auto_save(proposals={team.team_id})
                changing.cancel()
                await asyncio.sleep(0)
                changing.cancel()
            finally:
                release.set()
            with self.assertRaises(asyncio.CancelledError):
                await changing
        self.assertIn(reservation.agent, team.members)
        self.assertIs(self.manager._agents_by_id[reservation.agent.agent_id], reservation.agent)
        self.assertEqual(reservation.agent.private_doc_library_id, reservation.library_id)
        self.assertFalse(self.manager._agent_registry.pending)
        await self.manager.flush_state()
        await self.manager.load_state(self.path)
        restored = self.manager.teams[team.team_id]
        self.assertTrue(restored.proposals["staged-proposal"]["proposed_details"]["executed"])
        await self.manager._membership._apply_deferred_membership_changes(restored)
        self.assertEqual(sum(member.role == "StagedMember" for member in restored.members), 1)

    async def test_failure_releases_only_this_staged_identity_and_workspace(self):
        team = self.team()
        self.proposal(team)
        before = (set(self.manager._agents_by_id), set(self.manager.libraries))
        directories = set(Path(self.manager.config.workspace_root, ".att_doc_libs").iterdir())
        with patch.object(self.manager._records, "commit", side_effect=RuntimeError("Injected membership rejection")):
            with self.assertRaisesRegex(RuntimeError, "rejection"):
                await self.manager._membership._apply_deferred_membership_changes(team)
        self.assertEqual(before, (set(self.manager._agents_by_id), set(self.manager.libraries)))
        self.assertEqual(directories, set(Path(self.manager.config.workspace_root, ".att_doc_libs").iterdir()))
        self.assertFalse(self.manager._agent_registry.pending)
        self.assertNotIn("executed", team.proposals["staged-proposal"]["proposed_details"])
        await self.manager.save_state()
        await self.manager.load_state(self.path)

    async def test_concurrent_teams_reserve_unique_names_and_restore_rejects_pending_registrations(self):
        first, second = self.team(), self.team()
        self.proposal(first)
        self.proposal(second)
        second.proposals = {"second-staged-proposal": {**second.proposals["staged-proposal"], "proposal_id": "second-staged-proposal"}}
        await self.manager.save_state()
        async with self.manager._activity.lock:
            tasks = [asyncio.create_task(self.manager._membership._apply_deferred_membership_changes(team))
                     for team in (first, second)]
            try:
                reservations = await self.prepared(2)
                self.assertEqual(len({item.agent.name for item in reservations}), 2)
                with self.assertRaisesRegex(StateRestoreError, "registrations"):
                    await self.manager.load_state(self.path)
            except BaseException:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                raise
        await asyncio.wait_for(asyncio.gather(*tasks), 10)
        self.assertFalse(self.manager._agent_registry.pending)
        self.assertTrue(all(item.agent in first.members or item.agent in second.members for item in reservations))

    async def test_repeated_cancellation_during_multi_agent_staging_releases_every_reservation(self):
        team = self.team()
        before = (set(self.manager._agents_by_id), set(self.manager.libraries))
        directories = set(Path(self.manager.config.workspace_root, ".att_doc_libs").iterdir())
        entered, release = threading.Event(), threading.Event()
        original = AgentRegistration.prepare

        def slow(registration):
            entered.set()
            if not release.wait(10):
                raise TimeoutError("The test did not release private workspace staging.")
            return original(registration)

        async def add_many():
            async with self.manager._messaging.membership_transaction(team) as change:
                for index in range(3):
                    person = Agent(f"Staged-{index}", "Researcher", self.client)
                    change.register_agent(person)
                    change.members.append(person)

        with patch.object(AgentRegistration, "prepare", slow):
            changing = asyncio.create_task(add_many())
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 5))
                self.assertEqual(len(self.manager._agent_registry.pending), 3)
                changing.cancel()
                await asyncio.sleep(0)
                changing.cancel()
            finally:
                release.set()
            with self.assertRaises(asyncio.CancelledError):
                await changing
        self.assertFalse(self.manager._agent_registry.pending)
        self.assertEqual(before, (set(self.manager._agents_by_id), set(self.manager.libraries)))
        self.assertEqual(directories, set(Path(self.manager.config.workspace_root, ".att_doc_libs").iterdir()))

    async def test_real_writer_failure_does_not_publish_new_people_or_executed_proposals(self):
        team = self.team()
        self.proposal(team)
        await self.manager.save_state()
        before = (set(self.manager._agents_by_id), set(self.manager.libraries))
        directories = set(Path(self.manager.config.workspace_root, ".att_doc_libs").iterdir())
        store = self.manager._persistence._store(self.path)
        with patch.object(store, "write", side_effect=RuntimeError("Injected membership disk failure")):
            with self.assertRaisesRegex(RuntimeError, "disk failure"):
                await self.manager._membership._apply_deferred_membership_changes(team)
        self.assertEqual(before, (set(self.manager._agents_by_id), set(self.manager.libraries)))
        self.assertEqual(directories, set(Path(self.manager.config.workspace_root, ".att_doc_libs").iterdir()))
        self.assertFalse(self.manager._agent_registry.pending)
        self.assertNotIn("executed", team.proposals["staged-proposal"]["proposed_details"])
        with self.assertRaisesRegex(RuntimeError, "disk failure"):
            await self.manager.flush_state()
        with self.assertRaisesRegex(RuntimeError, "disk failure"):
            await self.manager.close()

    async def test_cleanup_waiting_for_topology_never_retains_resource_authority(self):
        registration = self.manager._agent_registry.reserve(Agent("PendingCleanup", "Researcher", self.client))
        await asyncio.to_thread(registration.prepare)
        directory = Path(registration.directory)
        entered, release = threading.Event(), threading.Event()

        def hold_topology():
            with self.manager._topology_lock:
                entered.set()
                if not release.wait(10):
                    raise TimeoutError("The test did not release its topology reader.")

        holder = asyncio.create_task(asyncio.to_thread(hold_topology))
        cleanup = None
        try:
            self.assertTrue(await asyncio.to_thread(entered.wait, 5))
            cleanup = asyncio.create_task(asyncio.to_thread(registration.release))
            async with asyncio.timeout(5):
                while directory.exists():
                    await asyncio.sleep(0)
            self.assertFalse(cleanup.done())
            await asyncio.wait_for(asyncio.to_thread(self.manager._resources.check_authority), 5)
        finally:
            release.set()
            await holder
            if cleanup is not None:
                await cleanup
        self.assertFalse(self.manager._agent_registry.pending)
