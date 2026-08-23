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

    async def test_writer_ownership_and_abrupt_restart_recovery(self):
        db_path = os.path.join(self.tmpdir, "owned.db")
        workspace = os.path.join(self.tmpdir, "process-workspace")
        context = multiprocessing.get_context("spawn")
        ready = context.Queue()
        release = context.Event()
        process = context.Process(
            target=_write_and_hold,
            args=(db_path, workspace, ready, release),
        )
        process.start()
        team_id = await asyncio.to_thread(ready.get, True, 10)
        with self.assertRaises(DatabaseOwnershipError):
            ATTManager(
                Agent("Other", "Architect", self.client),
                ATTConfig(workspace_root=self.tmpdir),
                db_path=db_path,
            )

        process.terminate()
        await asyncio.to_thread(process.join, 10)
        self.assertFalse(process.is_alive())

        restored = ATTManager(
            Agent("ProcessRoot", "Architect", self.client),
            ATTConfig(workspace_root=self.tmpdir),
            db_path=db_path,
        )
        restored.register_llm_client("process-model", self.client)
        await restored.load_state(db_path)
        self.assertIn(team_id, restored.teams)
        await restored.close()
    def test_unsupported_schema_is_not_modified(self):
        db_path = os.path.join(self.tmpdir, "unsupported.db")
        with closing(sqlite3.connect(db_path)) as connection:
            connection.execute("CREATE TABLE legacy (value TEXT)")
            connection.execute("INSERT INTO legacy VALUES ('unchanged')")
            connection.commit()
        with open(db_path, "rb") as stream:
            before = stream.read()
        with self.assertRaises(StateRestoreError):
            DatabaseStore(db_path)
        with open(db_path, "rb") as stream:
            after = stream.read()
        self.assertEqual(before, after)
    def test_schema_five_is_rejected_before_ddl(self):
        db_path = os.path.join(self.tmpdir, "schema-five.db")
        with closing(sqlite3.connect(db_path)) as connection:
            connection.execute(
                "CREATE TABLE manager_config "
                "(config_key TEXT PRIMARY KEY, config_value TEXT)"
            )
            connection.execute(
                "INSERT INTO manager_config VALUES "
                "('schema_version', '5')"
            )
            connection.execute("CREATE TABLE schema_five_only (value TEXT)")
            connection.execute(
                "INSERT INTO schema_five_only VALUES ('unchanged')"
            )
            connection.commit()
        with open(db_path, "rb") as stream:
            before = stream.read()

        with self.assertRaisesRegex(StateRestoreError, "version '5'"):
            DatabaseStore(db_path)

        with open(db_path, "rb") as stream:
            self.assertEqual(stream.read(), before)
    async def test_corrupt_database_reference_matrix_is_atomic(self):
        def missing_creator(connection, ids):
            connection.execute(
                "UPDATE teams SET creator_agent_id='missing-agent' "
                "WHERE team_id=?",
                (ids["parent"],),
            )

        def missing_parent(connection, ids):
            connection.execute(
                "UPDATE teams SET parent_team_id='missing-team' "
                "WHERE team_id=?",
                (ids["child"],),
            )

        def missing_owner(connection, ids):
            connection.execute(
                "UPDATE libraries SET owner_team_id='missing-team' "
                "WHERE lib_id=?",
                (ids["library"],),
            )

        def wrong_builtin_owner(connection, ids):
            connection.execute(
                "UPDATE libraries SET owner_team_id=? WHERE lib_id=?",
                (ids["child"], ids["library"]),
            )

        def missing_permission_team(connection, ids):
            connection.execute(
                "INSERT INTO library_permissions "
                "(lib_id, path, team_id, permission) VALUES (?, ?, ?, ?)",
                (ids["library"], "shared.txt", "missing-team", "READ"),
            )

        def missing_link_target(connection, ids):
            connection.execute(
                "INSERT INTO doc_lib_links "
                "(source_lib_id, source_path, target_lib_id, target_path) "
                "VALUES (?, ?, ?, ?)",
                (ids["library"], "link.txt", "missing-lib", "file.txt"),
            )

        def missing_agreement_team(connection, ids):
            connection.execute(
                "INSERT INTO communication_requests "
                "(request_id, sender_team_id, recipient_team_id, "
                "initiated_by_agent_id, rationale, direction, policy_snapshot, "
                "approval_principals, route_fingerprint, status, "
                "decision_reason, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "CR-corrupt",
                    ids["parent"],
                    "missing-team",
                    ids["root_agent"],
                    "corrupt",
                    "bidirectional",
                    '{"policy":"parent_approval","request_delivery":"queue","direction":"bidirectional"}',
                    "[]",
                    "invalid",
                    "PENDING",
                    "",
                    1.0,
                ),
            )

        def missing_proposal_initiator(connection, ids):
            connection.execute(
                "INSERT INTO team_proposals "
                "(proposal_id, team_id, initiator_type, initiator_name) "
                "VALUES (?, ?, ?, ?)",
                ("VP-corrupt", ids["parent"], "individual", "missing-agent"),
            )

        def invalid_proposal_initiator_type(connection, ids):
            connection.execute(
                "INSERT INTO team_proposals "
                "(proposal_id, team_id, initiator_type, initiator_name) "
                "VALUES (?, ?, ?, ?)",
                ("VP-invalid-type", ids["parent"], "service", "AT"),
            )

        def missing_model_binding(connection, ids):
            connection.execute(
                "UPDATE agents SET model_alias='missing-model' WHERE name='Root'"
            )

        corruptions = {
            "creator": missing_creator,
            "parent": missing_parent,
            "library_owner": missing_owner,
            "builtin_library_owner": wrong_builtin_owner,
            "permission_team": missing_permission_team,
            "link_target": missing_link_target,
            "agreement_team": missing_agreement_team,
            "proposal_initiator": missing_proposal_initiator,
            "proposal_initiator_type": invalid_proposal_initiator_type,
            "model_binding": missing_model_binding,
        }
        for name, corrupt in corruptions.items():
            with self.subTest(corruption=name):
                db_path = os.path.join(self.tmpdir, f"corrupt-{name}.db")
                source = ATTManager(
                    Agent("Root", "Architect", self.client),
                    ATTConfig(
                        workspace_root=os.path.join(
                            self.tmpdir, f"source-{name}"
                        )
                    ),
                    db_path=db_path,
                )
                source.register_llm_client("stable", self.client)
                parent = source.create_agent_team(source.root_ai)
                child = source.create_agent_team(parent)
                parent.doc_library.write_file("source.txt", "persisted")
                await source.save_state()
                ids = {
                    "parent": parent.team_id,
                    "child": child.team_id,
                    "library": parent.doc_library.lib_id,
                    "root_agent": source.root_ai.agent_id,
                }
                await source.close()
                with closing(sqlite3.connect(db_path)) as connection:
                    corrupt(connection, ids)
                    connection.commit()

                live = ATTManager(
                    Agent("LiveRoot", "Architect", self.client),
                    ATTConfig(
                        workspace_root=os.path.join(
                            self.tmpdir, f"live-{name}"
                        )
                    ),
                )
                live.register_llm_client("stable", self.client)
                live_team = live.create_agent_team(live.root_ai)
                live_team.doc_library.write_file("live.txt", "unchanged")
                old_agents = live.agents
                old_teams = live.teams
                old_libraries = live.libraries
                with self.assertRaises(StateRestoreError):
                    await live.load_state(db_path)
                self.assertIs(live.agents, old_agents)
                self.assertIs(live.teams, old_teams)
                self.assertIs(live.libraries, old_libraries)
                self.assertIn(
                    "unchanged",
                    live_team.doc_library.read_file("live.txt"),
                )
                await live.close()
