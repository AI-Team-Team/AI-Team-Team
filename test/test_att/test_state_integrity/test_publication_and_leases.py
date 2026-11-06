"""Live-process publication faults, cancellation, and stale managed workers."""

import asyncio
import os
import sqlite3
import threading
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from ai_team_team import Agent, StateRestoreError
from ai_team_team.doc_library import DocumentLibrary
from ai_team_team.database.persistence.publication import PublicationJournal
from ai_team_team.core.manager.restore import manifest as manifests

from ._support import execution, invocation_graph, make_manager


class PublicationTests(unittest.IsolatedAsyncioTestCase):
    async def checkpoint(self):
        manager, path, client = make_manager(self)
        manager.register_agent(Agent("Second", "Researcher", client))
        libraries = tuple(manager.libraries.values())
        for library in libraries:
            library.write_file("notes.txt", "checkpoint")
        await manager.save_state()
        for library in libraries:
            library._restore_all_files({"notes.txt": "live original"})
        return manager, path, client, libraries

    def assert_original(self, manager, root, libraries):
        self.assertIs(manager.root_ai, root)
        for library in libraries:
            self.assertIs(manager.libraries[library.lib_id], library)
            self.assertEqual(library.read_text("notes.txt"), "live original")
        self.assertFalse(manager._resources.blocked)
        self.assertFalse((Path(manager.config.workspace_root) / ".att_doc_libs/.att-publication.json").exists())

    async def test_file_staging_failure_does_not_publish_or_leave_staging_directories(self):
        manager, path, client, libraries = await self.checkpoint()
        root = manager.root_ai
        with patch.object(DocumentLibrary, "_restore_all_files", side_effect=OSError("Injected staging failure")):
            with self.assertRaisesRegex(StateRestoreError, "staging failure"):
                await manager.load_state(path)
        self.assert_original(manager, root, libraries)
        self.assertEqual(list((Path(manager.config.workspace_root) / ".att_doc_libs").glob(".att-restore-*")), [])
        self.assertEqual(client.requests, [])

    async def test_prepared_manifest_commit_failure_removes_only_unpublished_intent(self):
        manager, path, client, libraries = await self.checkpoint()
        root = manager.root_ai
        with patch.object(manifests, "commit_manifest", side_effect=OSError("Injected preparation commit failure")):
            with self.assertRaisesRegex(StateRestoreError, "preparation commit failure"):
                await manager.load_state(path)
        self.assert_original(manager, root, libraries)
        with closing(sqlite3.connect(path)) as database:
            self.assertEqual(database.execute("SELECT count(*) FROM publication_manifests").fetchone(), (0,))
        self.assertEqual(client.requests, [])

    async def test_partial_directory_publication_rolls_back_all_files(self):
        manager, path, client, libraries = await self.checkpoint()
        root = manager.root_ai
        original = os.replace
        count = 0
        def fail_second(source, target, *args, **kwargs):
            nonlocal count
            if "-publication-" in str(target):
                count += 1
                if count == 2:
                    raise OSError("Injected second directory rename failure")
            return original(source, target, *args, **kwargs)
        with patch("ai_team_team.database.persistence.publication.os.replace", fail_second):
            with self.assertRaises(StateRestoreError):
                await manager.load_state(path)
        self.assert_original(manager, root, libraries)
        self.assertEqual(client.requests, [])

    async def test_registry_switch_failure_undoes_durable_recovery_additions(self):
        manager, path, _, libraries = await self.checkpoint()
        root = manager.root_ai
        await manager._records.commit((*invocation_graph(root.agent_id), execution(root.agent_id)))
        original = manager._agent_registry.replace_indexes
        calls = 0
        def fail_once(*args):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("Injected registry switch failure")
            return original(*args)
        with patch.object(manager._agent_registry, "replace_indexes", fail_once):
            with self.assertRaises(StateRestoreError):
                await manager.load_state(path)
        self.assert_original(manager, root, libraries)
        with closing(sqlite3.connect(path)) as database:
            self.assertEqual(database.execute("SELECT count(*) FROM recovery_incidents").fetchone(), (0,))
            self.assertEqual(database.execute("SELECT count(*) FROM agent_notifications").fetchone(), (0,))
            self.assertEqual(database.execute("SELECT status FROM publication_manifests").fetchone(), ("rolled_back",))

    async def test_commit_decision_failure_preserves_original_runtime(self):
        manager, path, _, libraries = await self.checkpoint()
        root = manager.root_ai
        original = manifests.commit_manifest
        async def fail_commit(manager, record, **kwargs):
            if record.values["status"] == "published":
                raise OSError("Injected durable decision failure")
            return await original(manager, record, **kwargs)
        with patch.object(manifests, "commit_manifest", fail_commit):
            with self.assertRaises(StateRestoreError):
                await manager.load_state(path)
        self.assert_original(manager, root, libraries)

    async def test_cancelled_caller_waits_for_accepted_publication(self):
        manager, path, _, libraries = await self.checkpoint()
        entered, release = asyncio.Event(), asyncio.Event()
        original = manifests.prepare_manifest
        async def slow_prepare(*args):
            entered.set()
            await release.wait()
            return await original(*args)
        with patch("ai_team_team.core.manager.restore.transaction.prepare_manifest", slow_prepare):
            task = asyncio.create_task(manager.load_state(path))
            await entered.wait()
            for _ in range(3):
                task.cancel()
                await asyncio.sleep(0)
                self.assertFalse(task.done())
                self.assertTrue(manager._resources.blocked)
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertFalse(manager._resources.blocked)
        self.assertEqual(manager.libraries[libraries[0].lib_id].read_text("notes.txt"), "checkpoint")
        with self.assertRaisesRegex(RuntimeError, "obsolete|no longer registered"):
            libraries[0].write_file("late.txt", "must not write")

    async def test_cleanup_failure_is_observational_and_reconciles_on_read(self):
        manager, path, _, libraries = await self.checkpoint()
        with patch.object(manager, "_discard_library_backups", side_effect=OSError("Injected cleanup failure")):
            await manager.load_state(path)
        current = manager.libraries[libraries[0].lib_id]
        self.assertEqual(current.read_text("notes.txt"), "checkpoint")
        await manager._persistence.read(path)
        self.assertFalse((Path(manager.config.workspace_root) / ".att_doc_libs/.att-publication.json").exists())
        with self.assertRaises(RuntimeError):
            libraries[0].delete_file("notes.txt")

    async def test_interruption_annotations_are_protected_and_deduplicated(self):
        manager, path, client, _ = await self.checkpoint()
        owner = manager.root_ai.agent_id
        await manager._records.commit((*invocation_graph(owner), execution(owner, status="running")))
        await manager.load_state(path)
        first = tuple(row for row in manager._records.snapshot() if row.table_name == "agent_notifications")
        self.assertEqual(len(first), 2)
        self.assertTrue(all(row.values["classification"] == "recovery" for row in first))
        self.assertEqual(manager._recovery_plan.affected_agents, (owner,))
        self.assertEqual(manager._records.index[("executions", ("execution",))].values["status"], "running")
        await manager.load_state(path)
        second = tuple(row for row in manager._records.snapshot() if row.table_name == "agent_notifications")
        self.assertEqual(first, second)
        self.assertEqual(client.requests, [])

    async def test_active_worker_prevents_restore_and_close_fences_final_write(self):
        manager, path, _, libraries = await self.checkpoint()
        library = libraries[0]
        entered, release = threading.Event(), threading.Event()
        original = os.fsync
        def blocked_sync(descriptor):
            if threading.current_thread().name.startswith("asyncio"):
                entered.set()
                release.wait(5)
            return original(descriptor)
        with patch("ai_team_team.doc_library.os.fsync", blocked_sync):
            worker = asyncio.create_task(asyncio.to_thread(library.write_file_atomic, "late.txt", "private content"))
            self.assertTrue(await asyncio.to_thread(entered.wait, 5))
            with self.assertRaisesRegex(StateRestoreError, "resource operations"):
                await manager.load_state(path)
            await manager.close()
            release.set()
            with self.assertRaisesRegex(RuntimeError, "closed|obsolete"):
                await worker
        self.assertFalse((Path(library.root_dir) / "late.txt").exists())

    async def test_prepared_staging_hash_change_is_rejected(self):
        manager, path, _, libraries = await self.checkpoint()
        root = manager.root_ai
        original = PublicationJournal.publish
        def tamper_then_publish(journal, staged):
            directory = Path(next(entry["staged"] for entry in journal.entries if entry["staged"]))
            (directory / "notes.txt").write_text("changed after validation", encoding="utf-8")
            original(journal, staged)
        with patch.object(PublicationJournal, "publish", tamper_then_publish):
            with self.assertRaisesRegex(StateRestoreError, "changed after validation"):
                await manager.load_state(path)
        self.assert_original(manager, root, libraries)

    async def test_close_settles_an_accepted_publication_before_releasing_writer(self):
        manager, path, _, _ = await self.checkpoint()
        entered, release = asyncio.Event(), asyncio.Event()
        original = manifests.prepare_manifest
        async def pause(*args):
            entered.set()
            await release.wait()
            return await original(*args)
        with patch("ai_team_team.core.manager.restore.transaction.prepare_manifest", pause):
            loading = asyncio.create_task(manager.load_state(path))
            await entered.wait()
            closing_task = asyncio.create_task(manager.close())
            await asyncio.sleep(0)
            closing_task.cancel()
            await asyncio.sleep(0)
            self.assertFalse(manager._persistence._closed)
            release.set()
            await loading
            with self.assertRaises(asyncio.CancelledError):
                await closing_task
        self.assertTrue(manager._closed)
        with closing(sqlite3.connect(path)) as database:
            self.assertEqual(database.execute("SELECT status FROM publication_manifests").fetchone(), ("published",))

    async def test_restore_into_volatile_host_adopts_durable_mode_and_monotonic_generation(self):
        source, path, client = make_manager(self)
        await source.save_state()
        await source.load_state(path)
        first_generation = source._resources.generation
        await source.close()
        target, _, _ = make_manager(self, volatile=True)
        await target.load_state(path)
        self.assertEqual(target.persistence_mode, "durable")
        self.assertGreater(target._resources.generation, first_generation)
        with closing(sqlite3.connect(path)) as database:
            self.assertEqual(int(database.execute("SELECT config_value FROM manager_config WHERE config_key='publication_generation'").fetchone()[0]), target._resources.generation)

    async def test_revoked_acl_blocks_a_worker_at_its_final_file_commit(self):
        manager, _, _ = make_manager(self, volatile=True)
        def create_team():
            return manager.bootstrap_agent_team(manager.root_ai, member_configs={
                f"Member-{index}": {"model": "fixture"} for index in range(manager.config.min_subagent_team_size)
            })
        source, other = create_team(), create_team()
        library = source.doc_library
        with manager._resources.mutation():
            manager.library_permissions[library.lib_id] = {"/": {other.team_id: "WRITE"}}
        entered, release = threading.Event(), threading.Event()
        original = os.fsync
        def pause(descriptor):
            if threading.current_thread().name.startswith("asyncio"):
                entered.set()
                release.wait(5)
            return original(descriptor)
        with patch("ai_team_team.doc_library.os.fsync", pause):
            team_token = manager._active_team.set(other)
            actor_token = manager._active_tool_agent.set(other.members[0])
            try:
                worker = asyncio.create_task(asyncio.to_thread(library.write_file_atomic, "rejected.txt", "not committed"))
            finally:
                manager._active_tool_agent.reset(actor_token)
                manager._active_team.reset(team_token)
            self.assertTrue(await asyncio.to_thread(entered.wait, 5))
            with manager._resources.mutation():
                del manager.library_permissions[library.lib_id]["/"][other.team_id]
            release.set()
            with self.assertRaisesRegex(PermissionError, "ACL"):
                await worker
        self.assertFalse((Path(library.root_dir) / "rejected.txt").exists())
