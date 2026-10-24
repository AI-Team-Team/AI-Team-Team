"""Position cooldowns do not run during asynchronous record preparation."""

import asyncio
import threading
from unittest.mock import AsyncMock, patch

from ai_team_team.database.persistence.records import record_digest
from test.governance_client import settle_governance_activity
from test.test_att.test_agent_activity._support import ActivityTestCase


class MigrationCommitTimeTests(ActivityTestCase):
    async def assert_preparation_preserves_full_cooldown(self, *, durable, boundary, mode="include"):
        from ai_team_team.core.manager import durable_records

        if durable:
            self.manager = self.make_manager(self.root, durable=True)
        self.manager.register_runtime_clock(self.clock)
        self.manager.config.migration_cooldown_downtime = mode
        parent = self.manager.create_agent_team(self.root)
        child = self.manager.create_agent_team(self.root, parent=parent)
        with patch.object(self.manager._migration, "schedule"), patch.object(
                self.manager._migration, "complete_request", new=AsyncMock()):
            admitted = await self.manager.negotiate_and_execute_migration(child, None, "Explicit departure.")
        entered, release = asyncio.Event(), threading.Event()
        loop = asyncio.get_running_loop()
        target = durable_records if boundary == "digest" else self.manager._records._validation
        attribute = "record_digest" if boundary == "digest" else "prepare"
        original = getattr(target, attribute)

        def prepare(value):
            rows = value if boundary == "digest" else value["records"]
            if any(row.table_name == "team_position_cooldowns" for row in rows):
                loop.call_soon_threadsafe(entered.set)
                if not release.wait(10):
                    raise AssertionError("The test did not release the preparation worker.")
            return original(value)

        with patch.object(target, attribute, prepare), patch.object(self.manager._activity, "schedule_notice"):
            pending = asyncio.create_task(self.manager._migration.complete_request(admitted.request_id))
            try:
                await asyncio.wait_for(entered.wait(), 5)
                self.assertIs(child.parent_team, parent)
                self.assertFalse(self.records("team_position_cooldowns"))
                self.assertNotIn(f"TOPOLOGY-{admitted.request_id}", self.manager._records.receipts)
                self.clock.advance(601)
            finally:
                release.set()
            await pending
            await settle_governance_activity(self.manager)
        self.assertTrue(child.is_independent)
        self.assertEqual(self.manager._migration.remaining_cooldown(child.team_id), 600)
        self.assertEqual(self.manager.inspect_migration_request(admitted.request_id).resolved_at, 601)
        cooldown = self.records("team_position_cooldowns")[0]
        self.assertEqual(cooldown.values["sampled_at"], 601)
        receipt, rows = self.manager._records.receipts[f"TOPOLOGY-{admitted.request_id}"]
        self.assertEqual(receipt.record_digest, await asyncio.to_thread(record_digest, rows))
        event = next(row for row in rows if row.table_name == "team_topology_events")
        self.assertEqual(event.values["created_at"], 601)
        self.clock.advance(599)
        self.assertEqual(self.manager._migration.remaining_cooldown(child.team_id), 1)
        if durable:
            state = await self.manager._persistence.read(self.manager.db_path)
            self.manager._validate_state_snapshot(state)
            persisted = next(row for row in state["records"] if row.table_name == "team_position_cooldowns")
            self.assertEqual(persisted.values["deadline"], 1201)

    async def test_volatile_digest_preparation_does_not_spend_wall_cooldown(self):
        await self.assert_preparation_preserves_full_cooldown(durable=False, boundary="digest")

    async def test_durable_digest_preparation_does_not_spend_wall_cooldown(self):
        await self.assert_preparation_preserves_full_cooldown(durable=True, boundary="digest")

    async def test_graph_validation_wait_does_not_spend_wall_cooldown(self):
        await self.assert_preparation_preserves_full_cooldown(durable=False, boundary="validation")

    async def test_remaining_mode_uses_the_same_successful_position_time(self):
        await self.assert_preparation_preserves_full_cooldown(durable=False, boundary="validation", mode="exclude")
