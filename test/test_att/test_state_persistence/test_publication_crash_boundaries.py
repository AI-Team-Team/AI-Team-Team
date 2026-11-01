"""Actual process exits preserve multi-library rollback and pending recovery mail."""

import asyncio
import json
import os
import sqlite3
import subprocess
import sys
import unittest
from contextlib import closing
from pathlib import Path

from ai_team_team import ATTConfig, ATTManager, Agent
from test.test_att.test_agent_activity._support import idle
from test.test_att.test_autonomous_activity_phase0._fixtures import ModelStep
from test.test_att.test_autonomous_activity_phase1._support import make_manager


class PublicationCrashBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def child(self, module, *arguments):
        root = Path(__file__).resolve().parents[3]
        environment = {**os.environ, "PYTHONPATH": str(root / "src") + os.pathsep + str(root), "PYTHONIOENCODING": "utf-8"}
        result = await asyncio.to_thread(subprocess.run,
            [sys.executable, "-m", module, *map(str, arguments)], cwd=root, env=environment,
            capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(result.returncode, 73, result.stderr)

    async def test_process_exit_between_library_swaps_rolls_back_every_original_directory(self):
        manager, path, client = make_manager(self)
        team = manager.create_agent_team(manager.root_ai)
        libraries = [manager.libraries[manager.root_ai.private_doc_library_id], team.doc_library]
        for library in libraries:
            library.write_file("note.txt", "checkpoint")
        await manager.save_state()
        for library in libraries:
            library._restore_all_files({"note.txt": "live-before"})
        await manager.close()
        managed_root = Path(libraries[0].root_dir).parent
        await self.child("test.reliability._publication_crash", "files", path, managed_root,
            json.dumps([library.lib_id for library in libraries]))
        contents = [Path(library.root_dir, "note.txt").read_text(encoding="utf-8") for library in libraries]
        self.assertEqual(sorted(contents), ["checkpoint", "live-before"])
        successor = ATTManager(Agent("Successor", "Architect", client),
            ATTConfig(workspace_root=manager.config.workspace_root), persistence_mode="volatile")
        self.addAsyncCleanup(successor.close)
        successor.register_llm_client("fixture", client)
        await successor._persistence.prepare_runtime(path)
        self.assertEqual([Path(library.root_dir, "note.txt").read_text(encoding="utf-8") for library in libraries],
                         ["live-before", "live-before"])
        self.assertFalse((managed_root / ".att-publication.json").exists())
        self.assertFalse(tuple(managed_root.glob(".*-publication-*")))
        self.assertFalse(client.requests)

    async def test_exit_after_recovery_receipt_before_activation_keeps_one_notice_and_no_replay(self):
        manager, _, client = make_manager(self)
        workspace = Path(manager.config.workspace_root) / "interrupted"
        await self.child("test.reliability._execution_crash", workspace, "after_dispatch")
        path = workspace / "state.sqlite"
        await self.child("test.reliability._publication_crash", "notice", path, workspace)
        with closing(sqlite3.connect(path)) as database:
            before = database.execute("SELECT incident_id FROM recovery_incidents").fetchall()
            notices = database.execute("SELECT notification_id FROM agent_notifications WHERE classification='recovery'").fetchall()
        self.assertEqual(len(before), 1)
        self.assertEqual(len(notices), 1)
        client.steps.append(ModelStep(idle()))
        await manager.load_state(str(path))
        owner = manager.root_ai
        # Recovery resumes a person rather than repeating its old operation.
        from test.async_waits import wait_for_runtime
        async def settled():
            while manager._activity.workers or manager._activity.dispatch_tasks or not manager._activity.ready.empty():
                await asyncio.sleep(0)
        await wait_for_runtime(manager, settled(), label="Persisted interruption notification resumes its owner")
        self.assertEqual(len(client.requests), 1)
        await manager.save_state()
        await manager.load_state(str(path))
        await wait_for_runtime(manager, settled(), label="Repeated recovery does not reissue a handled notice")
        with closing(sqlite3.connect(path)) as database:
            self.assertEqual(database.execute("SELECT incident_id FROM recovery_incidents").fetchall(), before)
            self.assertEqual(database.execute("SELECT notification_id FROM agent_notifications WHERE classification='recovery'").fetchall(), notices)
        self.assertEqual((workspace / "effects.log").read_text(encoding="utf-8").splitlines(), ["dispatched"])
        self.assertEqual(len(client.requests), 1)
        self.assertEqual(client.unexpected_requests, 0)
        self.assertEqual(manager.root_ai.agent_id, owner.agent_id)
