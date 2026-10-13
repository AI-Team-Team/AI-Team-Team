"""Schema preflight, physical corruption, and process interruption boundaries."""

import os
import sqlite3
import subprocess
import sys
import unittest
from contextlib import closing
from pathlib import Path

from ai_team_team import ATTConfig, ATTManager, Agent, StateRestoreError
from ai_team_team.database.persistence.store import DatabaseStore

from ._support import invocation_graph, make_manager, model_request


class PhysicalSchemaTests(unittest.IsolatedAsyncioTestCase):
    async def test_schema_eleven_is_rejected_before_root_files_or_wal_changes(self):
        manager, path, client = make_manager(self)
        await manager.save_state()
        await manager.close()
        with closing(sqlite3.connect(path)) as connection:
            connection.execute("UPDATE manager_config SET config_value='11' WHERE config_key='schema_version'")
            connection.commit()
        before = Path(path).read_bytes()
        workspace = Path(manager.config.workspace_root)
        before_files = {str(item.relative_to(workspace)) for item in workspace.rglob("*") if item.is_file()}
        with self.assertRaisesRegex(StateRestoreError, "Unsupported state schema"):
            ATTManager(Agent("NewRoot", "Architect", client), ATTConfig(workspace_root=str(workspace)), db_path=path)
        self.assertEqual(Path(path).read_bytes(), before)
        after_files = {str(item.relative_to(workspace)) for item in workspace.rglob("*") if item.is_file()}
        self.assertEqual(after_files, before_files)

    async def test_supported_layout_is_not_healed_when_table_or_index_is_missing(self):
        for kind in ("table", "index"):
            with self.subTest(kind=kind):
                manager, path, _ = make_manager(self)
                await manager.save_state()
                await manager.close()
                with closing(sqlite3.connect(path)) as connection:
                    if kind == "table":
                        connection.execute("DROP TABLE executions")
                    else:
                        connection.execute("DROP INDEX uq_live_activity_owner")
                    connection.commit()
                before = Path(path).read_bytes()
                with self.assertRaises(StateRestoreError):
                    DatabaseStore(path)
                self.assertEqual(Path(path).read_bytes(), before)

    async def test_stale_generation_and_cross_owner_records_are_rejected_before_publication(self):
        other_id = "00000000-0000-0000-0000-000000000002"
        for column, value in (("runtime_generation", 9), ("agent_id", other_id), ("scope_team_id", "missing-team")):
            with self.subTest(column=column):
                manager, path, client = make_manager(self)
                manager.register_agent(Agent("Other", "Researcher", client, agent_id=other_id))
                await manager._records.commit(invocation_graph(manager.root_ai.agent_id))
                original_root = manager.root_ai
                library = manager.libraries[original_root.private_doc_library_id]
                library.write_file("original.txt", "must remain")
                await manager.flush_state()
                with closing(sqlite3.connect(path)) as connection:
                    connection.execute("PRAGMA ignore_check_constraints=ON")
                    connection.execute(f"UPDATE activity_invocations SET {column}=?", (value,))
                    connection.commit()
                with self.assertRaises(StateRestoreError):
                    await manager.load_state(path)
                self.assertIs(manager.root_ai, original_root)
                self.assertEqual(library.read_text("original.txt"), "must remain")
                self.assertEqual(client.requests, [])

    async def test_request_only_delta_requires_concrete_frame(self):
        manager, _, _ = make_manager(self, volatile=True)
        with self.assertRaisesRegex(Exception, "concrete durable prerequisite"):
            await manager._records.commit((model_request(manager.root_ai.agent_id),))
        self.assertEqual(manager._records.snapshot(), ())

    async def test_process_crash_reconciles_prepared_and_committed_directories(self):
        for decision in ("prepared", "published"):
            with self.subTest(decision=decision):
                manager, path, client = make_manager(self)
                library = manager.libraries[manager.root_ai.private_doc_library_id]
                library.write_file("note.txt", "checkpoint")
                await manager.save_state()
                library._restore_all_files({"note.txt": "old live files"})
                await manager.close()
                script = '''
import os, sqlite3, sys, tempfile, time, uuid
from pathlib import Path
from types import SimpleNamespace
from ai_team_team.database.persistence.publication import PublicationJournal
from ai_team_team.database.persistence.lease import WriterLease
from ai_team_team.database.persistence.records import DomainRecord, thaw
from ai_team_team.database.persistence.store import DatabaseStore
path, root, lib_id, decision = sys.argv[1:]
lease = WriterLease(path)
staging = Path(tempfile.mkdtemp(prefix='.att-restore-crash-', dir=root)) / lib_id
staging.mkdir()
(staging / 'note.txt').write_text('checkpoint', encoding='utf-8')
identifier = uuid.uuid4().hex
journal = PublicationJournal(root, identifier)
journal.database_path = path
libraries = {lib_id: SimpleNamespace(root_dir=str(staging))}
entries = journal.prepare(libraries, {})
store = DatabaseStore(path)
with sqlite3.connect(path) as connection:
    checkpoint = connection.execute("SELECT config_value FROM manager_config WHERE config_key='checkpoint_id'").fetchone()[0]
manifest = DomainRecord.capture('publication_manifests', {
    'publication_id': identifier, 'checkpoint_id': checkpoint, 'previous_generation': 1,
    'target_generation': 2, 'staged_files': list(entries), 'recovery_operation_id': identifier,
    'status': 'prepared', 'prepared_at': time.time(), 'resolved_at': None, 'state_version': 1})
store.write({'full': False, 'records': (manifest,)})
journal.publish(libraries)
if decision == 'published':
    values = thaw(manifest.values)
    values.update(status='published', resolved_at=time.time(), state_version=2)
    store.write({'full': False, 'records': (DomainRecord.capture('publication_manifests', values),)})
os._exit(0)
'''
                environment = dict(os.environ)
                environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[3] / "src") + os.pathsep + environment.get("PYTHONPATH", "")
                completed = await __import__("asyncio").to_thread(subprocess.run,
                    [sys.executable, "-c", script, path, str(Path(library.root_dir).parent), library.lib_id, decision],
                    capture_output=True, text=True, timeout=20, env=environment)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                successor = ATTManager(Agent("RestartRoot", "Architect", client),
                    ATTConfig(workspace_root=manager.config.workspace_root), db_path=path)
                self.addAsyncCleanup(successor.close)
                successor.register_llm_client("fixture", client)
                await successor._persistence.prepare_runtime(path)
                expected = "old live files" if decision == "prepared" else "checkpoint"
                self.assertEqual((Path(library.root_dir) / "note.txt").read_text(encoding="utf-8"), expected)
                self.assertFalse((Path(library.root_dir).parent / ".att-publication.json").exists())
                self.assertEqual(client.requests, [])
