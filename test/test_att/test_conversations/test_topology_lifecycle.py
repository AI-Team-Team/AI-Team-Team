"""Archive reservations and migration lifecycle checks share publication safety."""

import asyncio
import sqlite3
import threading
from contextlib import closing
from unittest.mock import AsyncMock, patch

from ai_team_team import StateRestoreError
from test.test_att.test_autonomous_activity_phase1._support import make_manager
from test.governance_client import settle_governance_activity, submit_case_ballots
from ._support import ChatTestCase


class TopologyLifecycleTests(ChatTestCase):
    def new_team(self, creator=None):
        return self.manager.create_agent_team(creator or self.root, parent=creator, member_configs={
            role: {"model": "fixture"} for role in ("Research", "Review", "Integrate")
        })

    async def test_archive_fences_new_children_until_its_real_writer_receipt(self):
        parent = self.new_team()
        await self.manager.save_state()
        entered, release = threading.Event(), threading.Event()
        store = self.manager._persistence._store(self.path)
        original = store.write

        def slow(snapshot):
            entered.set()
            if not release.wait(10):
                raise TimeoutError("The archive writer was not released.")
            return original(snapshot)

        with patch.object(store, "write", slow):
            closing = asyncio.create_task(self.manager.close_team_conversation(parent.team_id))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 5))
                self.assertEqual(getattr(parent, "_lifecycle_state", "active"), "active")
                before = set(self.manager.teams), set(self.manager._agents_by_id), set(self.manager.libraries)
                with self.assertRaisesRegex(ValueError, "awaiting commit"):
                    self.new_team(parent)
                self.assertEqual(before, (set(self.manager.teams), set(self.manager._agents_by_id), set(self.manager.libraries)))
                # An unrelated synchronous provisioning operation remains usable.
                unrelated = self.new_team()
                self.assertIsNone(unrelated.parent_team)
            finally:
                release.set()
                await closing
        self.assertEqual(parent._lifecycle_state, "dissolved")
        self.assertFalse(self.manager._topology.transition_pending)
        await self.manager.save_state()
        await self.manager.load_state(self.path)

    async def test_preexisting_staging_rechecks_the_archive_reservation_at_publication(self):
        parent = self.new_team()
        await self.manager.save_state()
        staged, finish_staging = threading.Event(), threading.Event()
        committing, finish_commit = asyncio.Event(), asyncio.Event()
        create, commit = self.manager._create_agent_team, self.manager._records.commit

        def paused_create(*args, **kwargs):
            value = create(*args, **kwargs)
            staged.set()
            if not finish_staging.wait(10):
                raise TimeoutError("Team staging was not released.")
            return value

        async def paused_commit(*args, **kwargs):
            committing.set()
            await finish_commit.wait()
            return await commit(*args, **kwargs)

        before = set(self.manager.teams), set(self.manager._agents_by_id), set(self.manager.libraries)
        with patch.object(self.manager, "_create_agent_team", paused_create), patch.object(self.manager._records, "commit", paused_commit):
            creating = asyncio.create_task(asyncio.to_thread(self.new_team, parent))
            closing = None
            try:
                self.assertTrue(await asyncio.to_thread(staged.wait, 5))
                closing = asyncio.create_task(self.manager.close_team_conversation(parent.team_id))
                await asyncio.wait_for(committing.wait(), 5)
                finish_staging.set()
                with self.assertRaisesRegex(ValueError, "awaiting commit"):
                    await asyncio.wait_for(creating, 5)
                self.assertEqual(before, (set(self.manager.teams), set(self.manager._agents_by_id), set(self.manager.libraries)))
                with self.assertRaisesRegex(StateRestoreError, "topology transition"):
                    await self.manager.load_state(self.path)
            finally:
                finish_staging.set()
                finish_commit.set()
                await asyncio.gather(*(task for task in (creating, closing) if task), return_exceptions=True)
        self.assertEqual(parent._lifecycle_state, "dissolved")

    async def test_failed_archive_releases_the_reservation_in_both_durability_modes(self):
        for volatile in (False, True):
            with self.subTest(volatile=volatile):
                manager, _, _ = make_manager(self, volatile=volatile)
                manager.config.max_delegation_depth = 3
                team = manager.create_agent_team(manager.root_ai, parent=manager.root_ai)
                records = manager._records.snapshot()
                with patch.object(manager._records, "commit", side_effect=RuntimeError("Injected archive failure")):
                    with self.assertRaisesRegex(RuntimeError, "archive failure"):
                        await manager.close_team_conversation(team.team_id)
                self.assertFalse(manager._topology.transition_pending)
                self.assertEqual(manager._records.snapshot(), records)
                self.assertEqual(getattr(team, "_lifecycle_state", "active"), "active")
                child = manager.create_agent_team(team, parent=team)
                self.assertIs(child.parent_team, team)
                grandchild = manager.create_agent_team(child, parent=child)
                await manager.close_team_conversation(team.team_id)
                self.assertIsNone(child.organizational_parent)
                self.assertIs(grandchild.parent_team, child)
                self.assertNotIn(("team_position_cooldowns", (child.team_id,)), manager._records.index)
                self.assertFalse(manager._topology.transition_pending)

    async def test_cancelled_archive_retains_its_reservation_through_receipt_settlement(self):
        team = self.new_team()
        await self.manager.save_state()
        entered, release = threading.Event(), threading.Event()
        store = self.manager._persistence._store(self.path)
        original = store.write

        def slow(snapshot):
            entered.set()
            if not release.wait(10):
                raise TimeoutError("The cancelled archive writer was not released.")
            return original(snapshot)

        with patch.object(store, "write", slow):
            closing = asyncio.create_task(self.manager.close_team_conversation(team.team_id))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 5))
                closing.cancel()
                await asyncio.sleep(0)
                closing.cancel()
                with self.assertRaisesRegex(ValueError, "awaiting commit"):
                    self.new_team(team)
            finally:
                release.set()
            with self.assertRaises(asyncio.CancelledError):
                await closing
        self.assertEqual(team._lifecycle_state, "dissolved")
        self.assertFalse(self.manager._topology.transition_pending)
        await self.manager.load_state(self.path)

    async def test_migration_rejects_dissolved_or_provisional_endpoints_in_both_modes(self):
        for volatile in (False, True):
            with self.subTest(volatile=volatile):
                manager, path, _ = make_manager(self, volatile=volatile)
                manager.config.migration_policy = "permissive"
                moving = manager.create_agent_team(manager.root_ai, parent=manager.root_ai)
                target = manager.create_agent_team(manager.root_ai, parent=manager.root_ai)
                target._publication_pending = True
                denied = await manager.negotiate_and_execute_migration(moving, target, "Provisional target")
                self.assertEqual(denied.status, "DENIED")
                target._publication_pending = False
                await manager.close_team_conversation(target.team_id)
                for source, destination in ((moving, target), (target, moving)):
                    denied = await manager.negotiate_and_execute_migration(source, destination, "Dissolved endpoint")
                    self.assertEqual(denied.status, "DENIED")
                    self.assertIsNone(source.parent_team)
                self.assertFalse(manager._migration.requests)
                await manager.save_state(path)
                await manager.load_state(path)

    async def test_pending_migration_rechecks_lifecycle_when_approval_finishes(self):
        self.manager.config.migration_policy = "permissive"
        moving, target = self.new_team(), self.new_team()
        with patch.object(self.manager._migration, "complete_request", new_callable=AsyncMock):
            pending = await self.manager.negotiate_and_execute_migration(moving, target, "Approved later")
        self.assertEqual(pending.status, "PENDING")
        await self.manager.close_team_conversation(target.team_id)
        await self.manager._migration.complete_request(pending.request_id)
        self.assertEqual(self.manager._migration.requests[pending.request_id].status, "STALE")
        self.assertIsNone(moving.parent_team)

    async def test_archive_waits_for_migration_receipt_then_detaches_the_child(self):
        self.manager.config.migration_policy = "permissive"
        moving, target = self.new_team(), self.new_team()
        result = await self.manager.negotiate_and_execute_migration(moving, target, "Attach first")
        await settle_governance_activity(self.manager)
        with patch.object(self.manager._governance, "schedule_resolution"):
            for case in tuple(self.manager._governance.cases.values()):
                if case.business_id == result.request_id:
                    await submit_case_ballots(self.manager, case)
        entered, release, archive_waiting = asyncio.Event(), asyncio.Event(), asyncio.Event()
        original = self.manager._records.commit

        class ObservedLock(asyncio.Lock):
            async def acquire(self):
                if self.locked():
                    archive_waiting.set()
                return await super().acquire()

        self.manager._topology.transition_lock = ObservedLock()

        async def paused_commit(*args, **kwargs):
            if str(kwargs.get("operation_id", "")).startswith("TOPOLOGY-"):
                entered.set()
                await release.wait()
            return await original(*args, **kwargs)

        with patch.object(self.manager._records, "commit", paused_commit):
            migrating = asyncio.create_task(self.manager._migration.complete_request(result.request_id))
            closing = None
            try:
                await asyncio.wait_for(entered.wait(), 5)
                self.assertIsNone(moving.organizational_parent)
                closing = asyncio.create_task(self.manager.close_team_conversation(target.team_id))
                await asyncio.wait_for(archive_waiting.wait(), 5)
                self.assertFalse(closing.done())
            finally:
                release.set()
                await migrating
                if closing is not None:
                    await closing
        self.assertEqual(self.manager.inspect_migration_request(result.request_id).status, "EXECUTED")
        self.assertIsNone(moving.organizational_parent)
        self.assertEqual(target._lifecycle_state, "dissolved")
        cooldown = self.manager._records.index[("team_position_cooldowns", (moving.team_id,))]
        events = [row for row in self.manager._records.snapshot()
            if row.table_name == "team_topology_events" and row.values["team_id"] == moving.team_id]
        self.assertEqual([row.values["transition"] for row in events], ["creation", "attachment", "parent_loss"])
        self.assertEqual(cooldown.values["event_id"], events[-2].values["event_id"])
        await self.manager.save_state()
        await self.manager.load_state(self.path)

    async def test_sql_validation_rejects_a_parent_edge_to_an_archived_team(self):
        moving, target = self.new_team(), self.new_team()
        await self.manager.close_team_conversation(target.team_id)
        await self.manager.save_state()
        dirty = self.manager._new_dirty_state()
        dirty["teams"].add(moving.team_id)
        snapshot = self.manager._capture_state_snapshot(dirty)
        snapshot["teams"] = [{**row, "parent_team_id": target.team_id, "parent_agent_id": None,
                              "state_version": row["state_version"] + 1} for row in snapshot["teams"]]
        store = self.manager._persistence._store(self.path)
        with self.assertRaisesRegex((ValueError, StateRestoreError), "organizational edge|parent cannot be dissolved"):
            await asyncio.to_thread(store.write, snapshot)
        self.assertIsNone(moving.parent_team)
        with closing(sqlite3.connect(self.path)) as database:
            self.assertEqual(database.execute("SELECT parent_team_id FROM teams WHERE team_id=?", (moving.team_id,)).fetchone(), (None,))

    async def test_archived_child_retains_provenance_when_its_parent_is_later_archived(self):
        parent = self.new_team()
        child = self.new_team(parent)
        author = child.members[0]
        message = await self.manager.send_team_message(child.team_id, "Retained child archive", actor=author)
        await self.manager.close_team_conversation(child.team_id)
        await self.manager.close_team_conversation(parent.team_id)
        await self.manager.save_state()
        await self.manager.load_state(self.path)
        restored_child = self.manager.teams[child.team_id]
        self.assertEqual(restored_child._lifecycle_state, "dissolved")
        self.assertEqual(restored_child.parent_team.team_id, parent.team_id)
        owner = self.manager._agents_by_id[author.agent_id]
        self.assertEqual(self.manager.list_team_messages(child.team_id, actor=owner).items[0].message_id, message.message_id)
        denied = await self.manager.negotiate_and_execute_migration(restored_child, self.manager.teams[parent.team_id], "No archive authority")
        self.assertEqual(denied.status, "DENIED")
