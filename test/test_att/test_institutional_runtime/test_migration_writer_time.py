"""SQLite preparation and lost responses cannot consume a new cooldown."""

import asyncio
import threading
from unittest.mock import AsyncMock, patch

from ai_team_team.database.persistence.records import record_digest
from test.governance_client import settle_governance_activity, submit_case_ballots
from test.test_att.test_agent_activity._support import ActivityTestCase


class MigrationWriterTimeTests(ActivityTestCase):
    async def pending_detachment(self, *, mode="include"):
        self.manager = self.make_manager(self.root, durable=True)
        self.manager.register_runtime_clock(self.clock)
        self.manager.config.migration_cooldown_downtime = mode
        parent = self.manager.create_agent_team(self.root)
        child = self.manager.create_agent_team(self.root, parent=parent)
        with patch.object(self.manager._migration, "schedule"), patch.object(
                self.manager._migration, "complete_request", new=AsyncMock()):
            admitted = await self.manager.negotiate_and_execute_migration(child, None, "Voluntary departure.")
        return parent, child, admitted.request_id

    async def assert_writer_wait_does_not_spend_cooldown(self, *, boundary, mode="include", cancel=False):
        parent, child, request_id = await self.pending_detachment(mode=mode)
        store = self.manager._persistence._store(self.manager.db_path)
        entered, release = asyncio.Event(), threading.Event()
        loop = asyncio.get_running_loop()
        target = store if boundary == "materialize" else store._validation
        attribute = "_materialize" if boundary == "materialize" else "prepare"
        original = getattr(target, attribute)

        def blocked(value):
            if boundary != "materialize" or value.get("_acceptance_times"):
                loop.call_soon_threadsafe(entered.set)
                if not release.wait(10):
                    raise AssertionError("The test did not release the SQLite preparation worker.")
            return original(value)

        with patch.object(target, attribute, blocked), patch.object(self.manager._activity, "schedule_notice"):
            pending = asyncio.create_task(self.manager._migration.complete_request(request_id))
            try:
                await asyncio.wait_for(entered.wait(), 5)
                self.assertIs(child.parent_team, parent)
                self.assertNotIn(f"TOPOLOGY-{request_id}", self.manager._records.receipts)
                self.assertFalse(self.records("team_position_cooldowns"))
                self.clock.advance(601)
                if cancel:
                    pending.cancel()
            finally:
                release.set()
            if cancel:
                with self.assertRaises(asyncio.CancelledError):
                    await pending
            else:
                await pending
            await settle_governance_activity(self.manager)
        self.assertTrue(child.is_independent)
        self.assertEqual(self.manager.inspect_migration_request(request_id).resolved_at, 601)
        self.assertEqual(self.manager._migration.remaining_cooldown(child.team_id), 600)
        self.assertFalse(self.manager._persistence._acceptance_clocks)
        receipt, rows = self.manager._records.receipts[f"TOPOLOGY-{request_id}"]
        self.assertEqual(receipt.record_digest, await asyncio.to_thread(record_digest, rows))
        state = await self.manager._persistence.read(self.manager.db_path)
        self.manager._validate_state_snapshot(state)
        event = next(row for row in state["records"] if row.table_name == "team_topology_events"
            and row.values["event_id"] == f"POSITION-{request_id}")
        self.assertEqual(event.values["created_at"], 601)
        self.assertEqual(state["migration_requests"][0]["resolved_at"], 601)
        row = next(row for row in state["records"] if row.table_name == "team_position_cooldowns")
        self.assertEqual(row.values["deadline"] if mode == "include" else row.values["remaining_seconds"],
            1201 if mode == "include" else 600)

    async def test_slow_sql_materialization_does_not_spend_the_cooldown(self):
        await self.assert_writer_wait_does_not_spend_cooldown(boundary="materialize")

    async def test_slow_sql_graph_validation_does_not_spend_the_cooldown(self):
        await self.assert_writer_wait_does_not_spend_cooldown(boundary="validation")

    async def test_remaining_accounting_shares_the_final_sql_commit_time(self):
        await self.assert_writer_wait_does_not_spend_cooldown(boundary="validation", mode="exclude")

    async def test_cancellation_after_submission_preserves_the_sql_bound_position(self):
        await self.assert_writer_wait_does_not_spend_cooldown(boundary="validation", cancel=True)

    async def test_invalid_final_clock_reading_rolls_back_the_entire_transaction(self):
        parent, child, request_id = await self.pending_detachment()
        with patch.object(self.manager._persistence, "_acceptance_time", side_effect=ValueError("Invalid final clock")):
            with self.assertRaisesRegex(ValueError, "Invalid final clock"):
                await self.manager._migration.complete_request(request_id)
        self.assertIs(child.parent_team, parent)
        self.assertEqual(self.manager.inspect_migration_request(request_id).status, "PENDING")
        self.assertFalse(self.records("team_position_cooldowns"))
        self.assertFalse(self.manager._persistence._acceptance_clocks)
        self.assertNotIn(f"TOPOLOGY-{request_id}", self.manager._records.receipts)
        state = await asyncio.to_thread(self.manager._persistence._read, self.manager.db_path, False)
        self.manager._validate_state_snapshot(state)
        self.assertFalse(any(row.table_name == "team_position_cooldowns" for row in state["records"]))
        self.assertEqual(state["migration_requests"][0]["status"], "PENDING")
        with self.assertRaisesRegex(ValueError, "Invalid final clock"):
            await self.manager.close()

    async def test_pending_delta_coalescing_preserves_the_timed_operation_and_clock(self):
        _parent, child, request_id = await self.pending_detachment()
        store = self.manager._persistence._store(self.manager.db_path)
        entered, queued, release = asyncio.Event(), asyncio.Event(), threading.Event()
        loop = asyncio.get_running_loop()
        materialize = store._materialize
        lookup = self.manager._persistence.receipt
        submit = self.manager._persistence.submit
        block_next = False

        def blocked(snapshot):
            nonlocal block_next
            if block_next:
                block_next = False
                loop.call_soon_threadsafe(entered.set)
                if not release.wait(10):
                    raise AssertionError("The queued-delta test did not release its earlier write.")
            return materialize(snapshot)

        async def before_preparation(path, operation_id, **kwargs):
            nonlocal block_next
            previous = await lookup(path, operation_id, **kwargs)
            if operation_id == f"TOPOLOGY-{request_id}":
                block_next = True
                self.manager._auto_save(configs=True)
                await asyncio.wait_for(entered.wait(), 5)
            return previous

        def observe_submission(*args, **kwargs):
            future = submit(*args, **kwargs)
            if args[1].get("_acceptance_times"):
                queued.set()
            return future

        with patch.object(store, "_materialize", blocked), patch.object(self.manager._persistence, "receipt", before_preparation), \
                patch.object(self.manager._persistence, "submit", observe_submission), patch.object(self.manager._activity, "schedule_notice"):
            pending = asyncio.create_task(self.manager._migration.complete_request(request_id))
            try:
                await asyncio.wait_for(queued.wait(), 5)
                self.assertIsNotNone(self.manager._persistence._pending_snapshot)
                self.manager._auto_save(configs=True)
                self.assertEqual(len(self.manager._persistence._pending_snapshot["_acceptance_times"]), 1)
                self.clock.advance(601)
            finally:
                release.set()
            await pending
            await settle_governance_activity(self.manager)
        self.assertTrue(child.is_independent)
        self.assertEqual(self.manager._migration.remaining_cooldown(child.team_id), 600)
        self.assertEqual(self.manager.inspect_migration_request(request_id).resolved_at, 601)
        self.assertFalse(self.manager._persistence._acceptance_clocks)
        state = await self.manager._persistence.read(self.manager.db_path)
        self.manager._validate_state_snapshot(state)
        self.assertEqual(state["migration_requests"][0]["resolved_at"], 601)

    async def test_parent_acceptance_event_cooldown_and_receipt_share_one_final_time(self):
        self.manager = self.make_manager(self.root, durable=True)
        self.manager.register_runtime_clock(self.clock)
        child = self.manager.create_agent_team(self.root)
        complete = self.manager._migration.complete_request
        with patch.object(self.manager._activity, "schedule_notice"), patch.object(
                self.manager._migration, "complete_request", new=AsyncMock()):
            admitted = await self.manager.negotiate_and_execute_migration(child, self.root, "Explicit Root Agent acceptance.")
            await settle_governance_activity(self.manager)
            for case in tuple(self.manager._governance.cases.values()):
                if case.business_id == admitted.request_id:
                    await submit_case_ballots(self.manager, case)
            await settle_governance_activity(self.manager)
        store = self.manager._persistence._store(self.manager.db_path)
        materialize = store._materialize
        entered, release = asyncio.Event(), threading.Event()
        loop = asyncio.get_running_loop()

        def advance_during_write(snapshot):
            if snapshot.get("_acceptance_times"):
                loop.call_soon_threadsafe(entered.set)
                if not release.wait(10):
                    raise AssertionError("The attachment test did not release its writer.")
            return materialize(snapshot)

        with patch.object(store, "_materialize", advance_during_write), patch.object(self.manager._activity, "schedule_notice"):
            pending = asyncio.create_task(complete(admitted.request_id))
            try:
                await asyncio.wait_for(entered.wait(), 5)
                self.clock.advance(601)
            finally:
                release.set()
            await pending
            await settle_governance_activity(self.manager)
        receipt, records = self.manager._records.receipts[f"TOPOLOGY-{admitted.request_id}"]
        self.assertEqual({row.table_name for row in records},
            {"parent_acceptances", "team_topology_events", "team_position_cooldowns"})
        self.assertEqual(receipt.record_digest, await asyncio.to_thread(record_digest, records))
        self.assertEqual(next(row for row in records if row.table_name == "parent_acceptances").values["created_at"], 601)
        self.assertEqual(self.manager._migration.remaining_cooldown(child.team_id), 600)
        state = await self.manager._persistence.read(self.manager.db_path)
        self.manager._validate_state_snapshot(state)

    async def test_remaining_cooldown_counts_online_time_after_sql_commit_before_observation(self):
        _parent, child, request_id = await self.pending_detachment(mode="exclude")
        settle = self.manager._records._settle_publication
        committed, release = asyncio.Event(), asyncio.Event()

        async def delayed_observation(future, *args, **kwargs):
            if args[2] == f"TOPOLOGY-{request_id}":
                await asyncio.shield(future)
                committed.set()
                await release.wait()
            return await settle(future, *args, **kwargs)

        with patch.object(self.manager._records, "_settle_publication", delayed_observation), \
                patch.object(self.manager._activity, "schedule_notice"):
            pending = asyncio.create_task(self.manager._migration.complete_request(request_id))
            try:
                await asyncio.wait_for(committed.wait(), 5)
                self.clock.advance(300)
            finally:
                release.set()
            await pending
            await settle_governance_activity(self.manager)
        self.assertEqual(self.manager._migration.remaining_cooldown(child.team_id), 300)
        self.assertEqual(self.manager.inspect_migration_request(request_id).resolved_at, 0)
        await self.manager.save_state()
        state = await self.manager._persistence.read(self.manager.db_path)
        self.manager._validate_state_snapshot(state)
        cooldown = next(row for row in state["records"] if row.table_name == "team_position_cooldowns")
        self.assertEqual(cooldown.values["remaining_seconds"], 300)

