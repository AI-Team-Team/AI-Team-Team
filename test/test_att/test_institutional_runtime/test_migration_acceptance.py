"""Live migration constraints and position clocks bind after admission waits."""

import asyncio
from unittest.mock import AsyncMock, patch

from ai_team_team import ToolBusinessError
from test.governance_client import settle_governance_activity, submit_case_ballots
from test.test_att.test_agent_activity._support import ActivityTestCase
from ._lock_support import ObservedLock


class MigrationAcceptanceTests(ActivityTestCase):
    async def pending_detachment(self):
        parent = self.manager.create_agent_team(self.root)
        child = self.manager.create_agent_team(self.root, parent=parent)
        with patch.object(self.manager._migration, "schedule"), patch.object(
                self.manager._migration, "complete_request", new=AsyncMock()):
            admitted = await self.manager.negotiate_and_execute_migration(child, None, "Explicit voluntary departure.")
        self.assertEqual(admitted.status, "PENDING")
        return parent, child, admitted.request_id

    async def assert_live_switch_rechecked(self, *, durable, boundary):
        if durable:
            self.manager = self.make_manager(self.root, durable=True)
        parent, child, request_id = await self.pending_detachment()
        owner = self.manager if boundary == "runtime" else self.manager._records
        attribute = "_runtime_gate" if boundary == "runtime" else "lock"
        gate = ObservedLock(getattr(owner, attribute))
        with patch.object(owner, attribute, gate):
            async with gate:
                pending = asyncio.create_task(self.manager._migration.complete_request(request_id))
                await gate.wait_for_attempt(pending)
                self.manager.config.allow_unilateral_detachment = False
            with self.assertRaises(ToolBusinessError):
                await pending
        self.assertIs(child.parent_team, parent)
        self.assertEqual(self.manager.inspect_migration_request(request_id).status, "PENDING")
        self.assertFalse(self.records("team_position_cooldowns"))
        self.assertNotIn(f"TOPOLOGY-{request_id}", self.manager._records.receipts)
        self.manager.config.allow_unilateral_detachment = True
        with patch.object(self.manager._activity, "schedule_notice"):
            await self.manager._migration.complete_request(request_id)
            await settle_governance_activity(self.manager)
        self.assertTrue(child.is_independent)

    async def test_volatile_detachment_rechecks_host_disable_after_runtime_gate_wait(self):
        await self.assert_live_switch_rechecked(durable=False, boundary="runtime")

    async def test_durable_detachment_rechecks_host_disable_after_runtime_gate_wait(self):
        await self.assert_live_switch_rechecked(durable=True, boundary="runtime")

    async def test_detachment_rechecks_host_disable_after_record_lock_wait(self):
        await self.assert_live_switch_rechecked(durable=False, boundary="records")

    async def test_queued_record_factory_pins_the_clock_without_starting_the_cooldown(self):
        self.manager.register_runtime_clock(self.clock)
        _parent, child, request_id = await self.pending_detachment()
        gate = ObservedLock(self.manager._runtime_gate)
        with patch.object(self.manager, "_runtime_gate", gate), patch.object(self.manager._activity, "schedule_notice"):
            async with gate:
                pending = asyncio.create_task(self.manager._migration.complete_request(request_id))
                await gate.wait_for_attempt(pending)
                self.assertFalse(self.records("team_position_cooldowns"))
                with self.assertRaises(RuntimeError):
                    self.manager.register_runtime_clock(self.clock.restarted(offline_seconds=0))
                self.clock.advance(601)
            await pending
            await settle_governance_activity(self.manager)
        self.assertEqual(self.manager._migration.remaining_cooldown(child.team_id), 600)

    async def test_final_authority_check_rejects_disable_after_record_production(self):
        from ai_team_team.core.manager import durable_records

        parent, child, request_id = await self.pending_detachment()
        digest = durable_records.record_digest

        def during_preparation(records):
            if any(row.table_name == "team_position_cooldowns" for row in records):
                self.manager.config.allow_unilateral_detachment = False
            return digest(records)

        with patch.object(durable_records, "record_digest", during_preparation):
            with self.assertRaises(ToolBusinessError):
                await self.manager._migration.complete_request(request_id)
        self.assertIs(child.parent_team, parent)
        self.assertEqual(self.manager.inspect_migration_request(request_id).status, "PENDING")
        self.assertFalse(self.records("team_position_cooldowns"))

    async def test_parent_to_parent_migration_rechecks_its_separate_live_switch(self):
        parent = self.manager.create_agent_team(self.root)
        target = self.manager.create_agent_team(self.root)
        child = self.manager.create_agent_team(self.root, parent=parent)
        resolve = self.manager._migration.complete_request
        with patch.object(self.manager._activity, "schedule_notice"), patch.object(
                self.manager._migration, "complete_request", new=AsyncMock()):
            admitted = await self.manager.negotiate_and_execute_migration(child, target, "Request a different parent.")
            await settle_governance_activity(self.manager)
            cases = [case for case in self.manager._governance.cases.values() if case.business_id == admitted.request_id]
            for case in cases:
                await submit_case_ballots(self.manager, case)
            await settle_governance_activity(self.manager)
        self.assertIn(target.team_id, {case.principal.principal_id for case in cases})
        self.assertTrue(all(case.status == "APPROVED" for case in self.manager._governance.cases.values()
            if case.business_id == admitted.request_id))
        gate = ObservedLock(self.manager._runtime_gate)
        with patch.object(self.manager, "_runtime_gate", gate):
            async with gate:
                pending = asyncio.create_task(resolve(admitted.request_id))
                await gate.wait_for_attempt(pending)
                self.manager.config.enable_migration = False
            with self.assertRaises(ToolBusinessError):
                await pending
        self.assertIs(child.parent_team, parent)
        self.assertFalse(self.records("parent_acceptances"))
        self.assertFalse(self.records("team_position_cooldowns"))
        self.assertEqual(self.manager.inspect_migration_request(admitted.request_id).status, "PENDING")

    async def test_durable_receipt_lookup_wait_does_not_spend_the_cooldown(self):
        self.manager = self.make_manager(self.root, durable=True)
        self.manager.register_runtime_clock(self.clock)
        _parent, child, request_id = await self.pending_detachment()
        lookup = self.manager._persistence.receipt

        async def slow_lookup(path, operation_id, **kwargs):
            if operation_id == f"TOPOLOGY-{request_id}":
                self.clock.advance(601)
            return await lookup(path, operation_id, **kwargs)

        with patch.object(self.manager._persistence, "receipt", slow_lookup), patch.object(self.manager._activity, "schedule_notice"):
            await self.manager._migration.complete_request(request_id)
            await settle_governance_activity(self.manager)
        self.assertEqual(self.manager.inspect_migration_request(request_id).resolved_at, 601)
        self.assertEqual(self.manager._migration.remaining_cooldown(child.team_id), 600)

    async def assert_cooldown_starts_at_admission(self, *, durable, mode, boundary):
        if durable:
            self.manager = self.make_manager(self.root, durable=True)
        self.manager.register_runtime_clock(self.clock)
        self.manager.config.migration_cooldown_downtime = mode
        _parent, child, request_id = await self.pending_detachment()
        owner = self.manager if boundary == "runtime" else self.manager._records
        attribute = "_runtime_gate" if boundary == "runtime" else "lock"
        gate = ObservedLock(getattr(owner, attribute))
        with patch.object(self.manager._activity, "schedule_notice"), patch.object(owner, attribute, gate):
            async with gate:
                pending = asyncio.create_task(self.manager._migration.complete_request(request_id))
                await gate.wait_for_attempt(pending)
                self.clock.advance(601)
            await pending
            await settle_governance_activity(self.manager)
        row = self.records("team_position_cooldowns")[0]
        event = next(row for row in self.records("team_topology_events") if row.values["event_id"] == f"POSITION-{request_id}")
        self.assertEqual(event.values["created_at"], 601)
        self.assertEqual(row.values["sampled_at"], 601)
        self.assertEqual(self.manager.inspect_migration_request(request_id).resolved_at, 601)
        self.assertEqual(self.manager._migration.remaining_cooldown(child.team_id), 600)
        if mode == "include":
            self.assertEqual(row.values["deadline"], 1201)
        self.clock.advance(599)
        self.assertEqual(self.manager._migration.remaining_cooldown(child.team_id), 1)
        if durable:
            await self.manager.save_state()
            state = await self.manager._persistence.read(self.manager.db_path)
            self.manager._validate_state_snapshot(state)
            retained = next(row for row in state["records"] if row.table_name == "team_position_cooldowns")
            self.assertEqual(retained.values["deadline"] if mode == "include" else retained.values["remaining_seconds"],
                1201 if mode == "include" else 1)

    async def test_volatile_wall_cooldown_does_not_run_before_runtime_admission(self):
        await self.assert_cooldown_starts_at_admission(durable=False, mode="include", boundary="runtime")

    async def test_durable_wall_cooldown_does_not_run_before_runtime_admission(self):
        await self.assert_cooldown_starts_at_admission(durable=True, mode="include", boundary="runtime")

    async def test_wall_cooldown_does_not_run_before_record_lock_admission(self):
        await self.assert_cooldown_starts_at_admission(durable=False, mode="include", boundary="records")

    async def test_durable_remaining_cooldown_remains_consistent_with_its_position(self):
        await self.assert_cooldown_starts_at_admission(durable=True, mode="exclude", boundary="runtime")
