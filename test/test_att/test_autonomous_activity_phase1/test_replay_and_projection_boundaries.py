"""Replay identity, ordered projections, and strict persisted evidence."""

import asyncio
import hashlib
import json
import sqlite3
import unittest
from contextlib import closing

from ai_team_team import StateRestoreError, TokenLimitExceededError
from ai_team_team.database.persistence import PersistenceCoordinator
from test.test_att.test_autonomous_activity_phase0._fixtures import AgentIdentitySnapshot

from ._support import hydrate_team_stream_id, invocation_graph, make_manager, model_request


class ReplayAndProjectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_record_order_does_not_change_replay_identity(self):
        for volatile in (False, True):
            with self.subTest(volatile=volatile):
                manager, path, client = make_manager(self, volatile=volatile)
                records = invocation_graph(manager.root_ai.agent_id)
                receipt = await manager._records.commit(records, operation_id="same-operation")
                version = manager._state_version
                self.assertEqual(await manager._records.commit(tuple(reversed(records)), operation_id="same-operation"), receipt)
                self.assertEqual(manager._state_version, version)
                if not volatile:
                    await manager.load_state(path)
                    self.assertEqual(await manager._records.commit(tuple(reversed(records)), operation_id="same-operation"), receipt)
                self.assertEqual(client.requests, [])

    async def test_explicit_invalid_operation_ids_never_generate_new_operations(self):
        manager, _, client = make_manager(self, volatile=True)
        records = invocation_graph(manager.root_ai.agent_id)
        version = manager._state_version
        for identifier in ("", " ", 0, False, [], {}, b"operation"):
            with self.subTest(identifier=identifier), self.assertRaises(ValueError):
                await manager._records.commit(records, operation_id=identifier)
            self.assertEqual(manager._state_version, version)
            self.assertEqual(manager._records.snapshot(), ())
            self.assertEqual(manager._records.receipts, {})
        receipt = await manager._records.commit(records, operation_id=None)
        self.assertEqual(len(receipt.operation_id), 32)
        self.assertEqual(client.requests, [])

    async def test_stream_identity_survives_export_restore_and_membership_changes(self):
        manager, path, client = make_manager(self, volatile=True)
        team = manager.create_agent_team(manager.root_ai, member_configs={
            f"Member-{index}": {"model": "fixture"} for index in range(manager.config.min_subagent_team_size + 1)
        })
        hydrate_team_stream_id(manager, team, "registered-stream")
        await manager.save_state(path)
        await manager.load_state(path)
        team = manager.teams[team.team_id]
        person = team.members[0]
        identity = AgentIdentitySnapshot.capture(person, manager)
        with manager._resources.mutation():
            team.members.remove(person)
        manager._auto_save(teams={team.team_id})
        await manager.flush_state()
        self.assertEqual(identity, AgentIdentitySnapshot.capture(person, manager))
        with closing(sqlite3.connect(path)) as database:
            self.assertEqual(database.execute("SELECT stream_id FROM chat_streams WHERE team_id=?", (team.team_id,)).fetchall(), [("registered-stream",)])
            self.assertEqual(database.execute("SELECT count(*) FROM membership_intervals WHERE team_id=? AND leave_event_id IS NOT NULL", (team.team_id,)).fetchone(), (1,))
            self.assertEqual(database.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual(client.requests, [])

    async def test_late_older_full_snapshot_cannot_overwrite_newer_delta(self):
        manager, path, _ = make_manager(self)
        await manager.save_state()
        older = manager._capture_state_snapshot(manager._new_dirty_state(full=True))
        manager.root_ai.role = "Updated role"
        manager._state_version += 1
        dirty = manager._new_dirty_state()
        dirty["configs"] = True
        dirty["agents"].add(manager.root_ai.agent_id)
        newer = manager._capture_state_snapshot(dirty)
        merged = PersistenceCoordinator._merge_snapshots(newer, older)
        self.assertEqual(merged["state_version"], newer["state_version"])
        await asyncio.wrap_future(manager._persistence.submit(path, merged))
        with closing(sqlite3.connect(path)) as database:
            self.assertEqual(database.execute("SELECT role FROM agents WHERE agent_id=?", (manager.root_ai.agent_id,)).fetchone(), ("Updated role",))

    async def test_invalid_numeric_evidence_is_rejected_before_publication(self):
        cases = (
            ("UPDATE agents SET state_version=?", 1.5),
            ("UPDATE agents SET state_version=?", -1),
            ("UPDATE teams SET state_version=?", 1.5),
            ("UPDATE agent_messages SET created_at=?", float("inf")),
            ("UPDATE libraries SET is_public_visible=? WHERE library_kind='team'", 2),
        )
        for sql, value in cases:
            with self.subTest(sql=sql, value=value):
                manager, path, client = make_manager(self)
                manager.create_agent_team(manager.root_ai, member_configs={
                    f"Member-{index}": {"model": "fixture"} for index in range(manager.config.min_subagent_team_size)
                })
                root = manager.root_ai
                root.messages.append({"role": "user", "content": "Fixture context"})
                library = manager.libraries[root.private_doc_library_id]
                library.write_file("original.txt", "unchanged")
                await manager.save_state()
                with closing(sqlite3.connect(path)) as database:
                    database.execute("PRAGMA ignore_check_constraints=ON")
                    database.execute(sql, (value,))
                    database.commit()
                with self.assertRaises(StateRestoreError):
                    await manager.load_state(path)
                self.assertIs(manager.root_ai, root)
                self.assertEqual(library.read_text("original.txt"), "unchanged")
                self.assertFalse(manager._resources.blocked)
                self.assertEqual(client.requests, [])

    async def test_receipt_shape_errors_remain_state_restore_errors(self):
        for damage in ("dependencies", "state_version", "malformed_json"):
            with self.subTest(damage=damage):
                manager, path, _ = make_manager(self)
                await manager._records.commit(invocation_graph(manager.root_ai.agent_id), operation_id="receipt")
                with closing(sqlite3.connect(path)) as database:
                    row = database.execute("SELECT operation_id, state_version, dependencies, record_digest FROM commit_receipts WHERE operation_id='receipt'").fetchone()
                    values = dict(zip(("operation_id", "state_version", "dependencies", "record_digest"), row))
                    values["dependencies"] = json.loads(values["dependencies"])
                    if damage == "malformed_json":
                        database.execute("UPDATE commit_receipts SET dependencies='[' WHERE operation_id='receipt'")
                    else:
                        values[damage] = {"not-a-list": []} if damage == "dependencies" else 1.5
                        digest = hashlib.sha256(json.dumps(values, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                        database.execute("UPDATE commit_receipts SET state_version=?, dependencies=?, digest=? WHERE operation_id='receipt'", (values["state_version"], json.dumps(values["dependencies"]), digest))
                    database.commit()
                with self.assertRaises(StateRestoreError):
                    await manager._persistence.receipt(path, "receipt", wait_pending=False)

    async def test_zero_limit_disables_even_zero_budget_reservations(self):
        manager, _, client = make_manager(self, volatile=True)
        manager.config.model_token_limits["fixture"] = 0
        for output_budget in (None, 0):
            with self.subTest(output_budget=output_budget), self.assertRaises(TokenLimitExceededError):
                manager.token_budget.reserve("fixture", 0, output_budget)
        await manager._records.commit(invocation_graph(manager.root_ai.agent_id))
        with self.assertRaises(TokenLimitExceededError):
            await manager.token_budget.reserve_request(model_request(manager.root_ai.agent_id), 0, 0)
        self.assertFalse(manager.token_budget.has_active_reservations())
        self.assertFalse(any(row.table_name == "model_token_claims" for row in manager._records.snapshot()))
        self.assertEqual(client.requests, [])
