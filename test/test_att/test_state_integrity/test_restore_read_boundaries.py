"""Read-only checkpoint preflight and cancellation-safe reconciliation."""

import asyncio
import sqlite3
import threading
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from ai_team_team import StateRestoreError
from ai_team_team.database.persistence.store import DatabaseStore

from ._support import make_manager


class RestoreReadBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_checkpoints_are_rejected_without_schema_or_wal_writes(self):
        for initialized in (False, True):
            with self.subTest(sqlite_header=initialized):
                manager, path, client = make_manager(self, volatile=True)
                source = Path(path)
                if initialized:
                    with closing(sqlite3.connect(path)) as database:
                        database.execute("PRAGMA user_version = 0")
                else:
                    source.touch()
                before = source.read_bytes()
                root = manager.root_ai
                library = manager.libraries[root.private_doc_library_id]
                library.write_file("original.txt", "original state")
                with self.assertRaises(StateRestoreError):
                    await manager.load_state(path)
                self.assertEqual(source.read_bytes(), before)
                self.assertFalse(Path(f"{path}-wal").exists())
                self.assertFalse(Path(f"{path}-shm").exists())
                self.assertIs(manager.root_ai, root)
                self.assertEqual(library.read_text("original.txt"), "original state")
                self.assertFalse(manager._resources.blocked)
                self.assertEqual(client.requests, [])

    async def _cancel_reconciliation_read(self, *, fail):
        manager, path, client = make_manager(self)
        await manager.save_state()
        root = manager.root_ai
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        original = manager._persistence._read

        def paused_read(source, reconcile=True):
            if not reconcile:
                return original(source, reconcile)
            entered.set()
            try:
                if not release.wait(5):
                    raise TimeoutError("The reconciliation test was not released.")
                if fail:
                    raise StateRestoreError("Injected reconciliation failure")
                return original(source, reconcile)
            finally:
                finished.set()

        with patch.object(manager._persistence, "_read", paused_read):
            task = asyncio.create_task(manager.load_state(path))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 5))
                for _ in range(3):
                    task.cancel()
                    await asyncio.sleep(0.01)
                    self.assertFalse(task.done())
                    self.assertTrue(manager._resources.blocked)
                    self.assertTrue(manager._restore_in_progress)
            finally:
                release.set()
                result = (await asyncio.gather(task, return_exceptions=True))[0]
                self.assertTrue(await asyncio.to_thread(finished.wait, 5))
        if fail:
            self.assertIsInstance(result, StateRestoreError)
            self.assertIn("Injected reconciliation failure", str(result))
        else:
            self.assertIsInstance(result, asyncio.CancelledError)
        self.assertIs(manager.root_ai, root)
        self.assertFalse(manager._resources.blocked)
        self.assertFalse(manager._restore_in_progress)
        self.assertEqual(client.requests, [])

    async def test_close_disposes_a_store_created_by_accepted_preparation(self):
        manager, path, client = make_manager(self)
        entered, release = threading.Event(), threading.Event()
        disposed = []
        original_prepare = manager._persistence._prepare
        original_close = DatabaseStore.close

        def paused_prepare(source):
            entered.set()
            if not release.wait(5):
                raise TimeoutError("The engine disposal test was not released.")
            return original_prepare(source)

        def observed_close(store):
            disposed.append(store.db_path)
            return original_close(store)

        with patch.object(manager._persistence, "_prepare", paused_prepare), patch.object(DatabaseStore, "close", observed_close):
            preparing = asyncio.create_task(manager._persistence.prepare_runtime(path))
            close_task = None
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 5))
                self.assertEqual(manager._persistence._stores, {})
                close_task = asyncio.create_task(manager.close())
                await asyncio.sleep(0.02)
                self.assertFalse(close_task.done())
            finally:
                release.set()
                results = await asyncio.gather(preparing, *([close_task] if close_task else []), return_exceptions=True)
        self.assertEqual(results, [None, None])
        self.assertEqual(disposed, [str(Path(path).resolve())])
        self.assertTrue(all(lease._file.closed for lease in manager._persistence._leases.values()))
        self.assertEqual(client.requests, [])

    async def test_repeated_cancel_keeps_restore_guard_until_reconciliation_finishes(self):
        await self._cancel_reconciliation_read(fail=False)

    async def test_reconciliation_failure_is_not_hidden_by_caller_cancellation(self):
        await self._cancel_reconciliation_read(fail=True)

    async def test_runtime_preparation_settles_its_worker_after_repeated_cancellation(self):
        manager, path, client = make_manager(self)
        await manager.save_state()
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        original = manager._persistence._prepare

        def paused_prepare(source):
            entered.set()
            try:
                if not release.wait(5):
                    raise TimeoutError("The preparation test was not released.")
                return original(source)
            finally:
                finished.set()

        with patch.object(manager._persistence, "_prepare", paused_prepare):
            task = asyncio.create_task(manager._persistence.prepare_runtime(path))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 5))
                for _ in range(3):
                    task.cancel()
                    await asyncio.sleep(0.01)
                    self.assertFalse(task.done())
            finally:
                release.set()
                result = (await asyncio.gather(task, return_exceptions=True))[0]
                self.assertTrue(await asyncio.to_thread(finished.wait, 5))
        self.assertIsInstance(result, asyncio.CancelledError)
        self.assertEqual(client.requests, [])

    async def test_close_keeps_writer_ownership_until_early_restore_finishes(self):
        manager, path, client = make_manager(self)
        await manager.save_state()
        entered, release = threading.Event(), threading.Event()
        original = manager._persistence._read

        def paused_read(source, reconcile=True):
            if reconcile:
                entered.set()
                if not release.wait(5):
                    raise TimeoutError("The shutdown test was not released.")
            return original(source, reconcile)

        with patch.object(manager._persistence, "_read", paused_read):
            restoring = asyncio.create_task(manager.load_state(path))
            close_task = None
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 5))
                close_task = asyncio.create_task(manager.close())
                await asyncio.sleep(0.02)
                self.assertFalse(close_task.done())
                self.assertFalse(manager._persistence._closed)
                self.assertTrue(manager._resources.blocked)
            finally:
                release.set()
                results = await asyncio.gather(restoring, *([close_task] if close_task else []), return_exceptions=True)
        self.assertEqual(results, [None, None])
        self.assertTrue(manager._closed)
        with closing(sqlite3.connect(path)) as database:
            self.assertEqual(database.execute("SELECT status FROM publication_manifests").fetchall(), [("published",)])
        self.assertEqual(client.requests, [])
