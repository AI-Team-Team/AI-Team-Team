"""A real process exit after recovery updates preserves their rollback images."""

import asyncio
import os
import sqlite3
import subprocess
import sys
import unittest
from contextlib import closing
from pathlib import Path

from test.test_att.test_autonomous_activity_phase1._support import invocation_graph, make_manager, model_request


class RecoveryCrashTests(unittest.IsolatedAsyncioTestCase):
    async def test_crash_after_rollback_intent_restores_existing_request_and_claim_rows(self):
        manager, path, client = make_manager(self)
        owner = manager.root_ai.agent_id
        await manager._records.commit(invocation_graph(owner))
        await manager.token_budget.reserve_request(model_request(owner), 10, 20)
        await manager.save_state()
        def facts():
            with closing(sqlite3.connect(path)) as database:
                return {table: database.execute(f'SELECT * FROM "{table}" ORDER BY 1').fetchall()
                        for table in ("model_requests", "model_token_claims", "activity_admissions", "activity_invocations")}
        before = facts()
        await manager.close()
        script = '''
import asyncio, os, sys
from ai_team_team import Agent, ATTConfig, ATTManager
from ai_team_team.core.manager.restore import transaction
from test.test_att.test_autonomous_activity_phase0._fixtures import ScriptedModelClient

async def main():
    client = ScriptedModelClient()
    manager = ATTManager(Agent("CrashHost", "Architect", client), ATTConfig(workspace_root=sys.argv[2]), persistence_mode="volatile")
    manager.register_llm_client("fixture", client)
    original = transaction.resolve_manifest
    async def crash(owner, manifest, status):
        resolved = await original(owner, manifest, status)
        if status == "published":
            owner._publication_journal.mark_rollback()
            os._exit(23)
        return resolved
    transaction.resolve_manifest = crash
    await manager.load_state(sys.argv[1])

asyncio.run(main())
'''
        completed = await asyncio.to_thread(subprocess.run,
            [sys.executable, "-c", script, path, manager.config.workspace_root],
            cwd=str(Path(__file__).resolve().parents[3]), env=dict(os.environ),
            capture_output=True, text=True, timeout=30)
        self.assertEqual(completed.returncode, 23, completed.stderr)
        # Reading the checkpoint performs durable publication reconciliation
        # before any model admission, replay, or external-status query.
        from ai_team_team import ATTConfig, ATTManager, Agent
        successor = ATTManager(Agent("Successor", "Architect", client),
            ATTConfig(workspace_root=manager.config.workspace_root), persistence_mode="volatile")
        self.addAsyncCleanup(successor.close)
        successor.register_llm_client("fixture", client)
        await successor._persistence.read(path)
        self.assertEqual(facts(), before)
        self.assertFalse(client.requests)
        with closing(sqlite3.connect(path)) as database:
            self.assertEqual(database.execute("SELECT status FROM publication_manifests").fetchone(), ("rolled_back",))
