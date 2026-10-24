"""Restore cannot rewind or rewrite the destination's committed Journal."""

import asyncio
import copy
import sqlite3
import threading
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from ai_team_team import StateRestoreError

from ._support import invocation_graph, make_manager


class RestoreJournalBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def checkpoint(self, *, interrupted=False, payload=None):
        manager, path, _client = make_manager(self)
        library = manager.libraries[manager.root_ai.private_doc_library_id]
        library.write_file("notes.txt", "checkpoint file")
        manager._memory.record_event("checkpoint_fixture", agent=manager.root_ai, payload=payload)
        if interrupted:
            await manager._records.commit(invocation_graph(manager.root_ai.agent_id))
        await manager.save_state()
        state = await manager._persistence.read(path, reconcile=False)
        return manager, path, library, state

    def journal_rows(self, path):
        with closing(sqlite3.connect(path)) as database:
            return database.execute(
                "SELECT event_id, sequence, event_type, payload "
                "FROM system_memory_events ORDER BY sequence"
            ).fetchall()

    async def assert_rejected_without_publication(self, manager, path, library, state, reason):
        root = manager.root_ai
        original_events = dict(manager._memory.events)
        rows = self.journal_rows(path)
        root_directory = Path(manager.config.workspace_root) / ".att_doc_libs"
        directories = sorted(root_directory.iterdir())
        with patch.object(
            manager, "_publish_staged_libraries", wraps=manager._publish_staged_libraries
        ) as publish:
            with self.assertRaisesRegex(StateRestoreError, reason):
                await manager._apply_state_snapshot(state)
            publish.assert_not_called()
        self.assertIs(manager.root_ai, root)
        self.assertIs(manager.libraries[library.lib_id], library)
        self.assertEqual(dict(manager._memory.events), original_events)
        self.assertEqual(self.journal_rows(path), rows)
        self.assertEqual(sorted(root_directory.iterdir()), directories)
        self.assertFalse(manager._resources.blocked)
        self.assertIsNone(manager._persistence._error)
        with closing(sqlite3.connect(path)) as database:
            self.assertEqual(database.execute("SELECT count(*) FROM publication_manifests").fetchone(), (0,))
        await manager.flush_state()

    async def test_stale_checkpoint_rejects_before_recovery_can_reuse_an_event_sequence(self):
        manager, path, library, state = await self.checkpoint(interrupted=True)
        late = manager._memory.record_event("late_completed_work", agent=manager.root_ai)
        library.write_file("notes.txt", "live file must survive")
        await manager.flush_state()
        self.assertGreater(late.sequence, max(event["sequence"] for event in state["memory_events"]))
        await self.assert_rejected_without_publication(
            manager, path, library, state, "omits committed Journal events"
        )
        self.assertEqual(library.read_text("notes.txt"), "live file must survive")
        following = manager._memory.record_event("after_rejected_restore", agent=manager.root_ai)
        self.assertGreater(following.sequence, late.sequence)
        await manager.save_state()
        self.assertEqual(self.journal_rows(path)[-1][0], following.event_id)
        await manager.close()  # Rejection must not resurface as a writer failure.

    async def test_matching_ids_cannot_hide_changed_immutable_event_values(self):
        manager, path, library, state = await self.checkpoint()
        changes = (
            ("payload", {"changed": True}),
            ("sequence", state["memory_events"][-1]["sequence"] + 10),
            ("invocation_id", "changed-context"),
            ("redacted", True),
        )
        for field, value in changes:
            with self.subTest(field=field):
                changed = copy.deepcopy(state)
                changed["memory_events"][-1][field] = value
                await self.assert_rejected_without_publication(
                    manager, path, library, changed, "changes immutable Journal event"
                )
        await manager.save_state()

    @staticmethod
    def boolean_number_substitutions():
        for original, replacement in ((1, True), (True, 1), (0, False), (False, 0)):
            for nested in (False, True):
                def payload(value):
                    return {"outer": [{"value": value}]} if nested else {"value": value}

                yield original, replacement, nested, payload(original), payload(replacement)

    async def test_restore_rejects_boolean_number_substitutions_in_json_payloads(self):
        for original, replacement, nested, payload, changed_payload in self.boolean_number_substitutions():
            with self.subTest(original=original, replacement=replacement, nested=nested):
                manager, path, library, state = await self.checkpoint(payload=payload)
                changed = copy.deepcopy(state)
                changed["memory_events"][-1]["payload"] = changed_payload
                await self.assert_rejected_without_publication(
                    manager, path, library, changed, "changes immutable Journal event"
                )
                await manager.save_state()
                await manager.close()

    async def test_writer_rejects_boolean_number_substitutions_and_propagates_the_error(self):
        for original, replacement, nested, payload, changed_payload in self.boolean_number_substitutions():
            with self.subTest(original=original, replacement=replacement, nested=nested):
                manager, path, _library, state = await self.checkpoint(payload=payload)
                original_rows = self.journal_rows(path)
                changed = {**state["memory_events"][-1], "payload": changed_payload}
                delta = {"full": False, "memory_events": [changed]}
                with self.assertRaisesRegex(ValueError, "Immutable journal event") as raised:
                    await asyncio.wrap_future(manager._persistence.submit(path, delta))
                self.assertEqual(self.journal_rows(path), original_rows)
                for boundary in (manager.flush_state, manager.save_state, manager.close):
                    with self.assertRaises(ValueError) as repeated:
                        await boundary()
                    self.assertIs(repeated.exception, raised.exception)

    async def test_json_object_key_order_does_not_change_an_immutable_event(self):
        payload = {"number": 1, "nested": {"enabled": True, "items": [0, False, "text", None]}}
        reordered = {"nested": {"items": [0, False, "text", None], "enabled": True}, "number": 1}
        manager, path, _library, state = await self.checkpoint(payload=payload)
        original_rows = self.journal_rows(path)
        state["memory_events"][-1]["payload"] = reordered
        await manager._persistence.validate_restore_journal(path, state["memory_events"])
        for full in (False, True):
            with self.subTest(full=full):
                dirty = manager._new_dirty_state()
                dirty["full"] = full
                snapshot = manager._capture_state_snapshot(dirty)
                snapshot["memory_events"] = state["memory_events"]
                await asyncio.wrap_future(manager._persistence.submit(path, snapshot))
                self.assertEqual(self.journal_rows(path), original_rows)
        await manager.save_state()

    async def test_matching_maximum_sequence_does_not_allow_an_omitted_middle_event(self):
        manager, path, library, state = await self.checkpoint()
        manager._memory.record_event("later_fixture", agent=manager.root_ai)
        await manager.save_state()
        state = await manager._persistence.read(path, reconcile=False)
        maximum = max(event["sequence"] for event in state["memory_events"])
        del state["memory_events"][1]
        self.assertEqual(max(event["sequence"] for event in state["memory_events"]), maximum)
        await self.assert_rejected_without_publication(
            manager, path, library, state, "omits committed Journal events"
        )

    async def test_preflight_includes_already_accepted_writes_before_comparing_the_journal(self):
        manager, path, library, state = await self.checkpoint()
        entered, release = threading.Event(), threading.Event()
        flushing = asyncio.Event()
        original_write = manager._persistence._write
        original_flush = manager._persistence.flush
        restoring = None

        def write(db_path, snapshot):
            if any(event["event_type"] == "late_pending_fixture" for event in snapshot.get("memory_events", ())):
                entered.set()
                if not release.wait(10):
                    raise TimeoutError("The accepted Journal write was not released.")
            return original_write(db_path, snapshot)

        async def flush():
            if asyncio.current_task() is restoring:
                flushing.set()
            return await original_flush()

        with (
            patch.object(manager._persistence, "_write", write),
            patch.object(manager._persistence, "flush", flush),
        ):
            try:
                manager._memory.record_event("late_pending_fixture", agent=manager.root_ai)
                self.assertTrue(await asyncio.to_thread(entered.wait, 5))
                restoring = asyncio.create_task(manager._apply_state_snapshot(state))
                await asyncio.wait_for(flushing.wait(), 5)
                self.assertFalse(restoring.done())
                release.set()
                with self.assertRaisesRegex(StateRestoreError, "omits committed Journal events"):
                    await asyncio.wait_for(restoring, 10)
            finally:
                release.set()
                if restoring is not None:
                    await asyncio.gather(restoring, return_exceptions=True)
        self.assertIsNone(manager._persistence._error)
        await manager.save_state()
        self.assertEqual(library.read_text("notes.txt"), "checkpoint file")

    async def test_public_restore_compares_the_checkpoint_database_not_the_old_runtime_database(self):
        source, source_path, _library, state = await self.checkpoint()
        checkpoint = str(Path(source.config.workspace_root) / "independent.sqlite")
        with closing(sqlite3.connect(source_path)) as original:
            with closing(sqlite3.connect(checkpoint)) as frozen:
                original.backup(frozen)
        source._memory.record_event("original_process_tail", agent=source.root_ai)
        await source.flush_state()
        original_rows = self.journal_rows(source_path)
        await source.close()

        replacement, _old_path, _client = make_manager(self)
        await replacement.save_state()
        await replacement.load_state(checkpoint)
        self.assertEqual(replacement.root_ai.agent_id, state["agents"][0]["agent_id"])
        self.assertEqual(self.journal_rows(source_path), original_rows)
        following = replacement._memory.record_event("after_independent_restore", agent=replacement.root_ai)
        self.assertEqual(following.sequence, max(event["sequence"] for event in state["memory_events"]) + 1)
        await replacement.save_state()
        self.assertEqual(self.journal_rows(checkpoint)[-1][0], following.event_id)
        self.assertEqual(self.journal_rows(source_path), original_rows)

    async def test_empty_target_preflight_does_not_create_database_tables(self):
        manager, path, _client = make_manager(self)
        self.assertFalse(Path(path).exists())
        await manager._persistence.validate_restore_journal(path, ())
        self.assertFalse(Path(path).exists())
        self.assertNotIn(str(Path(path).resolve()), manager._persistence._stores)
