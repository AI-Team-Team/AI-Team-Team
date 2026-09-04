import asyncio
import multiprocessing
import os
import shutil
import sqlite3
import tempfile
import threading
import time
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import AsyncMock, patch

from ai_team_team import (
    AmbiguousTeamContextError,
    ATTConfig,
    ATTException,
    ATTManager,
    Agent,
    AuditResult,
    AuditStatus,
    DatabaseOwnershipError,
    LLMGenerationError,
    StateRestoreError,
)
from ai_team_team.core.utils import generate_with_retry
from ai_team_team.database.persistence import (
    DatabaseStore,
    PersistenceCoordinator,
)
from ai_team_team.tool import get_default_tools


class EchoClient:
    async def generate(self, prompt, system_instruction=None, **kwargs):
        return "Final Answer: complete"


def _write_and_hold(db_path, workspace, ready, release):
    import warnings

    warnings.filterwarnings("ignore", category=ResourceWarning)

    async def run():
        client = EchoClient()
        manager = ATTManager(
            Agent("ProcessRoot", "Architect", client),
            ATTConfig(workspace_root=workspace),
            db_path=db_path,
        )
        manager.register_llm_client("process-model", client)
        team = manager.create_agent_team(manager.root_ai)
        await manager.save_state()
        ready.put(team.team_id)
        release.wait(10)

    asyncio.run(run())


class TestHighHardening(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="att_high_")
        self.client = EchoClient()

    async def asyncTearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    async def test_sqlite_pragmas_and_coalesced_pending_delta(self):
        db_path = os.path.join(self.tmpdir, "coalesced.db")
        manager = ATTManager(
            Agent("Root", "Architect", self.client),
            ATTConfig(workspace_root=self.tmpdir),
            db_path=db_path,
        )
        manager.register_llm_client("stable", self.client)
        manager.create_agent_team(manager.root_ai)
        await manager.save_state()

        started = threading.Event()
        release = threading.Event()
        calls = 0
        original = DatabaseStore.write

        def slow_write(store, snapshot):
            nonlocal calls
            calls += 1
            if calls == 1:
                started.set()
                release.wait(5)
            return original(store, snapshot)

        with patch.object(DatabaseStore, "write", slow_write):
            manager._auto_save(configs=True)
            await asyncio.to_thread(started.wait, 5)
            manager._auto_save(configs=True)
            pending = manager._persistence._pending_completion
            manager._auto_save(configs=True)
            self.assertIs(pending, manager._persistence._pending_completion)
            release.set()
            await manager.flush_state()
        self.assertEqual(calls, 2)

        store = manager._persistence._stores[str(Path(db_path).resolve())]
        with store.engine.connect() as connection:
            self.assertEqual(connection.exec_driver_sql("PRAGMA foreign_keys").scalar(), 1)
            self.assertEqual(
                connection.exec_driver_sql("PRAGMA journal_mode").scalar().lower(),
                "wal",
            )
            self.assertEqual(
                connection.exec_driver_sql("PRAGMA busy_timeout").scalar(),
                5000,
            )
        await manager.close()

    def test_tombstones_dominate_coalesced_entity_updates(self):
        agent_id = "00000000-0000-0000-0000-000000000001"
        lib_id = f"PDL-{agent_id}"
        earlier = {
            "full": False,
            "state_version": 1,
            "agents": [{"agent_id": agent_id, "name": "Deleted"}],
            "teams": [],
            "libraries": [{"lib_id": lib_id, "name": "Deleted"}],
            "inboxes": {},
            "proposals": {},
            "permissions": {lib_id: {"/": {}}},
            "links": {lib_id: {}},
            "file_changes": {lib_id: {"note.txt": "stale"}},
            "deleted_agents": [],
            "deleted_libraries": [],
        }
        deletion = {
            "full": False,
            "state_version": 2,
            "agents": [],
            "teams": [],
            "libraries": [],
            "inboxes": {},
            "proposals": {},
            "permissions": {},
            "links": {},
            "file_changes": {},
            "deleted_agents": [agent_id],
            "deleted_libraries": [lib_id],
        }

        merged = PersistenceCoordinator._merge_snapshots(earlier, deletion)

        self.assertEqual(merged["agents"], [])
        self.assertEqual(merged["libraries"], [])
        self.assertNotIn(lib_id, merged["permissions"])
        self.assertNotIn(lib_id, merged["links"])
        self.assertNotIn(lib_id, merged["file_changes"])

    def test_authoritative_deltas_dominate_insert_only_dependencies(self):
        agent_id = "00000000-0000-0000-0000-000000000001"
        lib_id = f"PDL-{agent_id}"
        dependencies = {
            "full": False,
            "state_version": 1,
            "agents": [],
            "agent_dependencies": [{"agent_id": agent_id, "role": "old"}],
            "teams": [],
            "libraries": [],
            "library_dependencies": [{"lib_id": lib_id, "description": "old"}],
            "inboxes": {},
            "proposals": {},
            "permissions": {},
            "links": {},
            "file_changes": {},
            "deleted_agents": [],
            "deleted_libraries": [],
        }
        authoritative = {
            **dependencies,
            "state_version": 2,
            "agents": [{"agent_id": agent_id, "role": "current"}],
            "agent_dependencies": [],
            "libraries": [{"lib_id": lib_id, "description": "current"}],
            "library_dependencies": [],
        }

        for earlier, later in (
            (dependencies, authoritative),
            (authoritative, dependencies),
        ):
            with self.subTest(order=(earlier["state_version"], later["state_version"])):
                merged = PersistenceCoordinator._merge_snapshots(earlier, later)
                self.assertEqual(merged["agents"][0]["role"], "current")
                self.assertEqual(merged["libraries"][0]["description"], "current")
                self.assertEqual(merged["agent_dependencies"], [])
                self.assertEqual(merged["library_dependencies"], [])

    def test_coalesced_approval_delta_replaces_request_ballots(self):
        principal = {"kind": "agent_team", "principal_id": "AT-parent"}
        base = {
            "full": False,
            "state_version": 1,
            "agents": [],
            "teams": [],
            "libraries": [],
            "communication_requests": [],
            "communication_agreements": [],
            "peer_messages": [],
            "communication_approvals": [
                {
                    "request_id": "CR-one",
                    "principal": principal,
                    "status": "PROCESSING",
                }
            ],
            "communication_ballots": [
                {
                    "request_id": "CR-one",
                    "principal": principal,
                    "voter_agent_id": "agent-old",
                }
            ],
            "inboxes": {},
            "proposals": {},
            "permissions": {},
            "links": {},
            "file_changes": {},
            "deleted_agents": [],
            "deleted_libraries": [],
        }
        retry = dict(base)
        retry.update(
            {
                "state_version": 2,
                "communication_approvals": [
                    {
                        "request_id": "CR-one",
                        "principal": principal,
                        "status": "PENDING",
                    }
                ],
                "communication_ballots": [],
            }
        )

        merged = PersistenceCoordinator._merge_snapshots(base, retry)

        self.assertEqual(merged["communication_approvals"][0]["status"], "PENDING")
        self.assertEqual(merged["communication_ballots"], [])

    async def test_persistence_errors_reach_every_explicit_boundary(self):
        db_path = os.path.join(self.tmpdir, "errors.db")
        manager = ATTManager(
            Agent("Root", "Architect", self.client),
            ATTConfig(workspace_root=self.tmpdir),
            db_path=db_path,
        )
        manager.register_llm_client("stable", self.client)
        manager.create_agent_team(manager.root_ai)
        await manager.save_state()

        with patch.object(DatabaseStore, "write", side_effect=OSError("disk failed")):
            manager._auto_save(configs=True)
            with self.assertRaisesRegex(OSError, "disk failed"):
                await manager.flush_state()
            with self.assertRaisesRegex(OSError, "disk failed"):
                await manager.save_state()
            with self.assertRaisesRegex(OSError, "disk failed"):
                await manager.close()

    async def test_cancellation_does_not_drop_an_accepted_write_or_team_lock(self):
        db_path = os.path.join(self.tmpdir, "cancel-boundaries.db")
        manager = ATTManager(
            Agent("Root", "Architect", self.client),
            ATTConfig(workspace_root=self.tmpdir),
            db_path=db_path,
        )
        manager.register_llm_client("stable", self.client)
        team = manager.create_agent_team(manager.root_ai)
        await manager.save_state()

        write_started = threading.Event()
        write_release = threading.Event()
        original_write = DatabaseStore.write

        def slow_write(store, snapshot):
            write_started.set()
            write_release.wait(5)
            return original_write(store, snapshot)

        with patch.object(DatabaseStore, "write", slow_write):
            save_task = asyncio.create_task(manager.save_state())
            await asyncio.to_thread(write_started.wait, 5)
            save_task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await save_task
            write_release.set()
            await manager.flush_state()

        session_started = asyncio.Event()

        async def hanging_session(*args, **kwargs):
            session_started.set()
            await asyncio.Event().wait()

        manager._execute_team_discussion_session = hanging_session
        discussion = asyncio.create_task(manager.execute_team_discussion(team, "cancel me"))
        await session_started.wait()
        discussion.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await discussion

        async def successful_session(*args, **kwargs):
            return "next session"

        manager._execute_team_discussion_session = successful_session
        self.assertEqual(
            await manager.execute_team_discussion(team, "next"),
            "next session",
        )
        await manager.close()
