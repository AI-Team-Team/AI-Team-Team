"""Shared withdrawal facts cannot be erased or disagree with source projections."""

import asyncio
import sqlite3
import unittest
from contextlib import closing

from ai_team_team import StatePersistenceError, StateRestoreError
from ai_team_team.database.persistence.records import DomainRecord, merge_records, thaw

from ._chat_support import install_chat, withdrawal_delta
from ._support import make_manager, record


class WithdrawalProjectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_confirmed_withdrawal_cannot_be_removed_or_replaced_in_either_mode(self):
        for volatile in (False, True):
            for kind in ("direct", "team"):
                with self.subTest(volatile=volatile, kind=kind):
                    manager, _, client = make_manager(self, volatile=volatile)
                    await install_chat(manager, kind=kind)
                    await manager._records.commit(withdrawal_delta(manager))
                    projection = manager._records.index[("chat_message_projections", ("message",))]
                    before, version = manager._records.snapshot(), manager._state_version
                    for identifier in (None, "another-withdrawal"):
                        changed = DomainRecord.capture("chat_message_projections", {**thaw(projection.values), "withdrawal_id": identifier, "state_version": projection.version + 1})
                        with self.assertRaisesRegex(StatePersistenceError, "message withdrawal"):
                            merge_records((projection,), (changed,))
                        with self.assertRaises(StatePersistenceError):
                            await manager._records.commit((changed,))
                        self.assertEqual(manager._records.snapshot(), before)
                        self.assertEqual(manager._state_version, version)
                    same = DomainRecord.capture("chat_message_projections", {**thaw(projection.values), "state_version": projection.version + 1})
                    await manager._records.commit((same,))
                    self.assertEqual(manager._records.index[projection.identity], same)
                    self.assertEqual(client.requests, [])

    async def test_sql_writer_independently_rejects_reopening_a_withdrawn_message(self):
        manager, path, _ = make_manager(self)
        await install_chat(manager)
        await manager._records.commit(withdrawal_delta(manager))
        projection = manager._records.index[("chat_message_projections", ("message",))]
        changed = DomainRecord.capture("chat_message_projections", {**thaw(projection.values), "withdrawal_id": None, "state_version": projection.version + 1})
        with self.assertRaisesRegex(StatePersistenceError, "message withdrawal"):
            await asyncio.to_thread(manager._persistence._store(path).write, {"full": False, "records": (changed,)})
        with closing(sqlite3.connect(path)) as database:
            self.assertEqual(database.execute("SELECT withdrawal_id, state_version FROM chat_message_projections").fetchone(), ("withdrawal", projection.version))
            self.assertEqual(database.execute("PRAGMA foreign_key_check").fetchall(), [])

    async def test_withdrawal_and_source_projection_must_commit_together(self):
        for volatile in (False, True):
            with self.subTest(volatile=volatile):
                manager, path, client = make_manager(self, volatile=volatile)
                await install_chat(manager)
                before = manager._records.snapshot()
                records = withdrawal_delta(manager, include_projection=False)
                with self.assertRaisesRegex(StateRestoreError, "current withdrawal projection"):
                    if volatile:
                        await manager._records.commit(records)
                    else:
                        await asyncio.to_thread(manager._persistence._store(path).write, {"full": False, "records": records})
                self.assertEqual(manager._records.snapshot(), before)
                await manager._records.commit(withdrawal_delta(manager))
                self.assertEqual(manager._records.index[("chat_message_projections", ("message",))].values["withdrawal_id"], "withdrawal")
                self.assertEqual(client.requests, [])

    async def test_corrupt_missing_projection_is_rejected_before_restore_publication(self):
        for kind in ("direct", "team"):
            with self.subTest(kind=kind):
                manager, path, client = make_manager(self)
                await install_chat(manager, kind=kind)
                await manager._records.commit(withdrawal_delta(manager))
                root, before = manager.root_ai, manager._records.snapshot()
                library = manager.libraries[root.private_doc_library_id]
                library.write_file("original.txt", "Unchanged personal fixture")
                await manager.save_state()
                with closing(sqlite3.connect(path)) as database:
                    database.execute("UPDATE chat_message_projections SET withdrawal_id=NULL")
                    database.commit()
                    self.assertEqual(database.execute("PRAGMA foreign_key_check").fetchall(), [])
                with self.assertRaisesRegex(StateRestoreError, "current withdrawal projection"):
                    await manager.load_state(path)
                self.assertIs(manager.root_ai, root)
                self.assertEqual(manager._records.snapshot(), before)
                self.assertEqual(library.read_text("original.txt"), "Unchanged personal fixture")
                self.assertFalse(manager._resources.blocked)
                self.assertEqual(client.requests, [])

    async def test_detached_checkpoint_validation_does_not_repair_a_missing_projection(self):
        manager, path, _ = make_manager(self)
        await install_chat(manager)
        await manager._records.commit(withdrawal_delta(manager))
        state = await manager._persistence.read(path, reconcile=False)
        projection = next(row for row in state["records"] if row.table_name == "chat_message_projections")
        state["records"] = tuple(DomainRecord.capture(row.table_name, {**thaw(row.values), "withdrawal_id": None})
                                 if row.identity == projection.identity else row for row in state["records"])
        with self.assertRaisesRegex(StateRestoreError, "current withdrawal projection"):
            await asyncio.to_thread(manager._validate_state_snapshot, state)
        self.assertEqual(manager._records.index[projection.identity], projection)

    async def test_later_withdrawal_preserves_frozen_views_read_evidence_and_previews(self):
        manager, path, client = make_manager(self)
        team, _, recipient = await install_chat(manager, kind="team")
        interval = next(row for row in manager._records.snapshot() if row.table_name == "membership_intervals" and row.values["team_id"] == team.team_id and row.values["agent_id"] == recipient.agent_id)
        previous_view = next(row for row in manager._records.snapshot() if row.table_name == "chat_personal_views" and row.values["agent_id"] == recipient.agent_id)
        view = DomainRecord.capture("chat_personal_views", {**thaw(previous_view.values), "read_at": 2.5, "read_revision_number": 1, "state_version": previous_view.version + 1})
        notice = record("agent_notifications", notification_id="reminder", agent_id=recipient.agent_id, source_kind="team_message",
                        chat_message_id="message", classification="ordinary", deduplication_key="message-reminder", arrival_generation=1, created_at=2.0)
        preview = record("chat_reminder_previews", notification_id="reminder", agent_id=recipient.agent_id, revision_id="revision",
                         preview={"title": "Fixture title", "body": "Captured fixture preview"}, visibility={"view_id": view.values["view_id"], "interval_id": interval.values["interval_id"]})
        await manager._records.commit((view, notice, preview))
        with manager._resources.mutation():
            team.members.remove(recipient)
        manager._auto_save(teams={team.team_id})
        leave = manager._records.index[interval.identity].values["leave_event_id"]
        cutoff = manager._records.index[("chat_events", (leave,))].values["sequence"]
        frozen = DomainRecord.capture("chat_personal_views", {**thaw(view.values), "view_kind": "frozen", "departure_cutoff": cutoff, "state_version": view.version + 1})
        await manager._records.commit((frozen,))
        await manager._records.commit(withdrawal_delta(manager))
        await manager.save_state()
        await manager.load_state(path)
        self.assertEqual(manager._records.index[frozen.identity], frozen)
        self.assertEqual(manager._records.index[preview.identity], preview)
        self.assertEqual(manager._records.index[notice.identity], notice)
        self.assertIsNone(frozen.values["withdrawal_id"])
        self.assertEqual(manager._records.index[("chat_message_projections", ("message",))].values["withdrawal_id"], "withdrawal")
        self.assertEqual(merge_records((frozen,), (frozen,)), (frozen,))
        self.assertEqual(client.requests, [])
