import asyncio
import copy
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from unittest.mock import patch

from ai_team_team import (
    ATTConfig,
    ATTManager,
    Agent,
    ApprovalPrincipal,
    ParentApprovalCommunicationConfig,
    StateRestoreError,
)
from test.governance_client import PersonalGovernanceClient


class GovernancePersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.workspace = tempfile.TemporaryDirectory(prefix="att-governance-state-")
        self.addCleanup(self.workspace.cleanup)
        self.client = PersonalGovernanceClient(respond=False)
        self.manager = ATTManager(
            Agent("Root", "Root", self.client),
            ATTConfig(
                workspace_root=self.workspace.name,
                enable_memory_compression=False,
                communication=ParentApprovalCommunicationConfig(),
            ),
            os.path.join(self.workspace.name, "state.sqlite"),
        )
        self.manager.register_llm_client("default", self.client)
        self.addAsyncCleanup(self.manager.close)

    async def pending(self):
        manager = self.manager
        first = manager.create_agent_team(manager.root_ai)
        second = manager.create_agent_team(manager.root_ai)
        result = await manager.broker.request_peer_communication(
            first, second, first.members[0].agent_id, "Persistent public rationale."
        )
        async with asyncio.timeout(10):
            while manager._emergency_tasks:
                await asyncio.gather(*tuple(manager._emergency_tasks))
                await asyncio.sleep(0)
        return result.request_id, next(iter(manager._governance.rounds.values()))

    async def test_unread_and_read_pending_choices_restore_independently(self):
        request_id, item = await self.pending()
        root_id = self.manager.root_ai.agent_id
        message_id = self.manager.root_ai.agent_inbox[0]["message_id"]
        await self.manager.mark_agent_inbox_read(root_id, [message_id])
        await self.manager.save_state()
        state = await self.manager._persistence.read(self.manager.db_path)
        await self.manager._apply_state_snapshot(state)
        restored = self.manager._governance.rounds[item.round_id]
        self.assertFalse(restored.ballots)
        self.assertIsNotNone(self.manager.root_ai.agent_inbox[0]["read_at"])
        self.assertEqual(
            self.manager.broker.communication_requests[request_id].status.value, "PENDING"
        )
        self.assertEqual(len(self.manager.list_governance_requests(actor=self.manager.root_ai)), 1)

    async def test_submission_commit_failure_rolls_back_ballot_and_public_history(self):
        _, item = await self.pending()
        root = self.manager.root_ai
        before = copy.deepcopy(root.message_history)
        token = self.manager._active_tool_agent.set(root)
        try:
            with patch.object(
                self.manager, "_commit_dirty_state", side_effect=OSError("disk failure")
            ):
                with self.assertRaisesRegex(OSError, "disk failure"):
                    await self.manager.submit_governance_choice(
                        item.round_id, {"approved": True}, actor=root
                    )
        finally:
            self.manager._active_tool_agent.reset(token)
        self.assertFalse(self.manager._governance.rounds[item.round_id].ballots)
        self.assertEqual(root.message_history, before)
        self.assertFalse(
            any(
                "Public governance choice" in str(event.payload)
                for event in self.manager._memory.events.values()
            )
        )
        await self.manager.flush_state()
        with closing(sqlite3.connect(self.manager.db_path)) as database:
            self.assertEqual(
                database.execute("SELECT COUNT(*) FROM governance_ballots").fetchone()[0], 0
            )

    async def test_corruption_is_rejected_before_runtime_or_files_change(self):
        _, item = await self.pending()
        await self.manager.save_state()
        state = await self.manager._persistence.read(self.manager.db_path)
        root = self.manager.root_ai
        library = self.manager.libraries[root.private_doc_library_id]
        library.write_file("note.txt", "Keep this original private file.")
        cases = []
        for key, value in (
            ("principal", {"kind": "agent", "principal_id": state["teams"][0]["members"][0]}),
            ("voter_agent_ids", ["missing-agent"]),
            ("business_id", "missing-request"),
            ("round_number", 3),
            ("choice_kind", "model"),
            ("status", "APPROVED"),
            ("created_at", float("nan")),
            ("created_at", float("inf")),
            ("resolved_at", float("nan")),
        ):
            broken = copy.deepcopy(state)
            broken["governance_rounds"][0][key] = value
            cases.append(broken)
        broken = copy.deepcopy(state)
        broken["agent_inboxes"][root.agent_id][0]["payload"]["round_id"] = "missing-round"
        cases.append(broken)
        broken = copy.deepcopy(state)
        broken["agent_inboxes"][root.agent_id] = []
        cases.append(broken)
        for broken in cases:
            with self.subTest(state=broken["governance_rounds"][0]):
                with self.assertRaises(StateRestoreError):
                    await self.manager._apply_state_snapshot(broken)
                self.assertIs(self.manager.root_ai, root)
                self.assertEqual(library.read_file("note.txt"), "Keep this original private file.")

    async def test_new_records_commit_within_an_outer_suppression_batch(self):
        async with self.manager.suppress_auto_save():
            request_id, item = await self.pending()
            with closing(sqlite3.connect(self.manager.db_path)) as database:
                self.assertEqual(
                    database.execute("SELECT COUNT(*) FROM governance_rounds").fetchone()[0], 1
                )
                self.assertEqual(database.execute("PRAGMA foreign_key_check").fetchall(), [])
        await self.manager.flush_state()
        state = await self.manager._persistence.read(self.manager.db_path)
        self.manager._validate_state_snapshot(state)
        self.assertEqual(state["governance_rounds"][0]["business_id"], request_id)

    async def test_authoritative_decisions_without_matching_explicit_choices_are_rejected(self):
        _, item = await self.pending()
        token = self.manager._active_tool_agent.set(self.manager.root_ai)
        try:
            await self.manager.submit_governance_choice(
                item.round_id, {"approved": True}, actor=self.manager.root_ai
            )
        finally:
            self.manager._active_tool_agent.reset(token)
        async with asyncio.timeout(5):
            while self.manager._emergency_tasks:
                await asyncio.gather(*tuple(self.manager._emergency_tasks))
                await asyncio.sleep(0)
        await self.manager.save_state()
        state = await self.manager._persistence.read(self.manager.db_path)
        self.manager._validate_state_snapshot(state)
        broken = copy.deepcopy(state)
        broken["governance_rounds"] = []
        broken["agent_inboxes"][self.manager.root_ai.agent_id] = []
        with self.assertRaisesRegex(StateRestoreError, "matching explicit voting round"):
            self.manager._validate_state_snapshot(broken)

    async def test_sqlite_reader_rejects_conflicting_identity_and_orphaned_ballots(self):
        _, item = await self.pending()
        await self.manager.save_state()
        with closing(sqlite3.connect(self.manager.db_path)) as database:
            original = database.execute(
                "SELECT data FROM governance_rounds WHERE round_id=?", (item.round_id,)
            ).fetchone()[0]
            damaged = json.loads(original)
            damaged["round_id"] = "conflicting-round-id"
            database.execute(
                "UPDATE governance_rounds SET data=? WHERE round_id=?",
                (json.dumps(damaged), item.round_id),
            )
            database.commit()
        with self.assertRaisesRegex(StateRestoreError, "identity is inconsistent"):
            await self.manager._persistence.read(self.manager.db_path)
        with closing(sqlite3.connect(self.manager.db_path)) as database:
            database.execute(
                "UPDATE governance_rounds SET data=? WHERE round_id=?", (original, item.round_id)
            )
            database.execute(
                "INSERT INTO governance_ballots VALUES (?, ?, ?, ?, ?)",
                (
                    "orphan-ballot",
                    "missing-round",
                    self.manager.root_ai.agent_id,
                    json.dumps({"approved": True, "reason": ""}),
                    item.created_at,
                ),
            )
            database.commit()
        with self.assertRaisesRegex(StateRestoreError, "no originating round"):
            await self.manager._persistence.read(self.manager.db_path)
        with closing(sqlite3.connect(self.manager.db_path)) as database:
            database.execute("DELETE FROM governance_ballots WHERE ballot_id=?", ("orphan-ballot",))
            database.commit()

    async def test_interrupted_failover_restores_expired_mail_without_replaying_choices(self):
        principal = ApprovalPrincipal(kind="agent", principal_id=self.manager.root_ai.agent_id)
        task = asyncio.create_task(
            self.manager.broker.decision_provider.decide_agent_model(
                principal, "Bounded public choice.", ["spare"]
            )
        )
        async with asyncio.timeout(5):
            while not self.manager._governance.rounds or self.manager._emergency_tasks:
                await asyncio.sleep(0.01)
        await self.manager.save_state()
        state = await self.manager._persistence.read(self.manager.db_path)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        await self.manager._apply_state_snapshot(state)
        item = next(iter(self.manager._governance.rounds.values()))
        self.assertEqual(item.status, "EXPIRED")
        self.assertFalse(item.ballots)
        self.assertEqual(len(self.manager.root_ai.agent_inbox), 1)

    async def test_pending_migration_restores_all_personal_ballots_and_progress(self):
        first = self.manager.create_agent_team(self.manager.root_ai)
        second = self.manager.create_agent_team(self.manager.root_ai)
        moving = self.manager.create_agent_team(first)
        result = await self.manager.negotiate_and_execute_migration(
            moving, second, "Preserve pending migration."
        )
        async with asyncio.timeout(5):
            while self.manager._emergency_tasks:
                await asyncio.gather(*tuple(self.manager._emergency_tasks))
                await asyncio.sleep(0)
        self.assertEqual(result.status, "PENDING")
        await self.manager.save_state()
        state = await self.manager._persistence.read(self.manager.db_path)
        await self.manager._apply_state_snapshot(state)
        self.assertEqual(
            self.manager.inspect_migration_request(result.request_id).status, "PENDING"
        )
        self.assertEqual(self.manager.teams[moving.team_id].parent_team.team_id, first.team_id)
        self.assertEqual(len(self.manager._governance.rounds), 3)
        for item in self.manager._governance.rounds.values():
            for actor_id in item.voter_agent_ids:
                actor = self.manager._agents_by_id[actor_id]
                token = self.manager._active_tool_agent.set(actor)
                try:
                    await self.manager.submit_governance_choice(
                        item.round_id, {"approved": True}, actor=actor
                    )
                finally:
                    self.manager._active_tool_agent.reset(token)
        async with asyncio.timeout(5):
            while self.manager._emergency_tasks:
                await asyncio.gather(*tuple(self.manager._emergency_tasks))
                await asyncio.sleep(0)
        self.assertEqual(
            self.manager.inspect_migration_request(result.request_id).status, "EXECUTED"
        )
        self.assertEqual(self.manager.teams[moving.team_id].parent_team.team_id, second.team_id)
        await self.manager.save_state()
        self.manager._validate_state_snapshot(
            await self.manager._persistence.read(self.manager.db_path)
        )

    async def test_optional_memory_indexes_the_same_personal_governance_turn(self):
        self.client.respond = True
        original = self.client.generate

        async def with_memory_labels(prompt=None, require_json=False, **kwargs):
            if require_json:
                return json.dumps(
                    {
                        "title": "Public governance",
                        "summary": "I considered a public communication request and submitted my choice.",
                        "tags": ["governance"],
                    }
                )
            return await original(prompt=prompt, require_json=False, **kwargs)

        self.client.generate = with_memory_labels
        self.manager.config.episodic_memory.enabled = True
        _, item = await self.pending()
        await self.manager.flush_memory_indexing()
        cards = list(self.manager._memory.cards.values())
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].agent_id, self.manager.root_ai.agent_id)
        self.assertIsNone(cards[0].origin_team_id)
        self.assertEqual(item.status, "APPROVED")
        await self.manager.save_state()
        state = await self.manager._persistence.read(self.manager.db_path)
        self.manager._validate_state_snapshot(state)
        await self.manager._apply_state_snapshot(state)
        self.assertEqual(len(self.manager._memory.cards), 1)
