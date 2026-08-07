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

    def test_numeric_config_validation_applies_to_mutation(self):
        positive_fields = {
            "subagent_discussion_rounds",
            "react_max_steps",
            "max_memory_turns",
            "inbox_summarize_threshold_chars",
            "emergency_discussion_rounds",
            "max_tool_rounds",
        }
        for field in positive_fields:
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    ATTConfig(**{field: 0})

        config = ATTConfig(
            max_migrations_per_team_discussion=0,
            llm_max_retries=0,
            max_tool_retries=0,
            llm_retry_backoff_factor=0,
            model_token_limits={"disabled": 0},
        )
        with self.assertRaises(ValueError):
            config.react_max_steps = 0
        with self.assertRaises(ValueError):
            config.model_token_limits["bad"] = -1
        with self.assertRaises(ValueError):
            config.model_max_output_tokens.update({"bad": 0})
        self.assertFalse(hasattr(config, "strict_state_persistence"))

    async def test_runtime_execution_scales_are_validated(self):
        manager = ATTManager(
            Agent("Root", "Architect", self.client),
            ATTConfig(workspace_root=self.tmpdir),
        )
        team = manager.create_agent_team(manager.root_ai)
        with self.assertRaisesRegex(ValueError, "max_steps"):
            await team.execute_reasoning_step(
                team.members[0], "prompt", "system", max_steps=0
            )
        with self.assertRaisesRegex(ValueError, "rounds"):
            await manager.execute_team_discussion(team, "prompt", rounds=0)
        await manager.close()

    async def test_save_lists_every_agent_without_stable_alias(self):
        root_client = EchoClient()
        manager = ATTManager(
            Agent("Root", "Architect", root_client),
            ATTConfig(workspace_root=self.tmpdir),
        )
        team = manager.create_agent_team(manager.root_ai)
        team.members[0].llm_client = EchoClient()
        path = os.path.join(self.tmpdir, "aliases.db")
        with self.assertRaisesRegex(ValueError, "Root") as raised:
            await manager.save_state(path)
        self.assertIn(team.members[0].name, str(raised.exception))
        await manager.close()

    async def test_model_name_is_not_alias_without_identity_binding(self):
        client = EchoClient()
        client.model_name = "claimed-name"
        manager = ATTManager(
            Agent("Root", "Architect", client),
            ATTConfig(workspace_root=self.tmpdir),
        )
        with self.assertRaises(ValueError):
            await manager.save_state(os.path.join(self.tmpdir, "model-name.db"))
        manager.register_llm_client("claimed-name", client)
        await manager.save_state(os.path.join(self.tmpdir, "model-name.db"))
        await manager.close()

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
                "INSERT INTO broker_agreements "
                "(sender_team_id, recipient_team_id) VALUES (?, ?)",
                (ids["parent"], "missing-team"),
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
            self.assertEqual(
                connection.exec_driver_sql("PRAGMA foreign_keys").scalar(), 1
            )
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

    async def test_shared_agent_context_memory_and_serial_calls(self):
        class SerialClient:
            def __init__(self):
                self.active = 0
                self.maximum = 0
                self.system_prompts = []

            async def generate(self, prompt, system_instruction=None, **kwargs):
                self.active += 1
                self.maximum = max(self.maximum, self.active)
                self.system_prompts.append(system_instruction or "")
                await asyncio.sleep(0.03)
                self.active -= 1
                return "Final Answer: shared"

        client = SerialClient()
        root = Agent("Root", "Architect", client)
        shared = Agent("Shared", "Analyst", client)
        manager = ATTManager(root, ATTConfig(workspace_root=self.tmpdir))
        manager.register_llm_client("shared-model", client)
        manager.agents[shared.name] = shared
        configs_a = {
            "Analyst": {"hire_agent": shared.name},
            "HelperA": {"model": "shared-model"},
            "HelperB": {"model": "shared-model"},
        }
        configs_b = {
            "Expert": {"hire_agent": shared.name},
            "HelperC": {"model": "shared-model"},
            "HelperD": {"model": "shared-model"},
        }
        team_a = manager.create_agent_team(root, member_configs=configs_a)
        team_b = manager.create_agent_team(root, member_configs=configs_b)

        with self.assertRaises(AmbiguousTeamContextError):
            manager.get_agent_team(shared)

        team_token = manager._active_team.set(team_a)
        try:
            child = shared.launch_att(manager)
        finally:
            manager._active_team.reset(team_token)
        self.assertIs(child.parent_team, team_a)

        await asyncio.gather(
            team_a.execute_reasoning_step(shared, "A", "system", manager=manager),
            team_b.execute_reasoning_step(shared, "B", "system", manager=manager),
        )
        self.assertEqual(client.maximum, 1)
        self.assertTrue(any(team_a.team_id in text for text in client.system_prompts))
        self.assertTrue(any(team_b.team_id in text for text in client.system_prompts))
        generated = [
            message
            for message in shared.message_history
            if message.get("team_id") in {team_a.team_id, team_b.team_id}
        ]
        self.assertEqual(
            {message["team_id"] for message in generated},
            {team_a.team_id, team_b.team_id},
        )
        self.assertTrue(all(message.get("discussion_id") for message in generated))

        tools = get_default_tools({"att_manager": manager}, shared)
        token = manager._active_team.set(team_b)
        try:
            await tools["update_team_purpose"]("Scoped to B")
        finally:
            manager._active_team.reset(token)
        self.assertEqual(team_b.team_purpose, "Scoped to B")
        self.assertNotEqual(team_a.team_purpose, "Scoped to B")
        with self.assertRaises(AmbiguousTeamContextError):
            await tools["update_team_purpose"]("Ambiguous")
        db_path = os.path.join(self.tmpdir, "shared-history.db")
        await manager.save_state(db_path)
        await manager.close()
        restored = ATTManager(
            Agent("Root", "Architect", client),
            ATTConfig(workspace_root=self.tmpdir),
        )
        restored.register_llm_client("shared-model", client)
        await restored.load_state(db_path)
        restored_history = restored.agents[shared.name].message_history
        self.assertEqual(len(restored_history), len(shared.message_history))
        self.assertTrue(
            all(message.get("team_id") for message in restored_history)
        )
        await restored.close()

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

        with patch.object(
            DatabaseStore, "write", side_effect=OSError("disk failed")
        ):
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
        discussion = asyncio.create_task(
            manager.execute_team_discussion(team, "cancel me")
        )
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

    async def test_unknown_alert_dedupe_survives_restore(self):
        db_path = os.path.join(self.tmpdir, "unknown.db")
        manager = ATTManager(
            Agent("Root", "Architect", self.client),
            ATTConfig(
                workspace_root=self.tmpdir,
                audit_unknown_escalation_mode="queue",
            ),
            db_path=db_path,
        )
        manager.register_llm_client("stable", self.client)
        parent = manager.create_agent_team(manager.root_ai)
        child = manager.create_agent_team(parent)
        result = AuditResult(AuditStatus.UNKNOWN, "offline", "timeout")
        await manager.supervisor.report_unknown(child, result, manager)
        await manager.supervisor.report_unknown(child, result, manager)
        await manager.save_state()
        await manager.close()

        restored = ATTManager(
            Agent("Root", "Architect", self.client),
            ATTConfig(workspace_root=self.tmpdir),
        )
        restored.register_llm_client("stable", self.client)
        await restored.load_state(db_path)
        restored_parent = restored.teams[parent.team_id]
        self.assertEqual(len(restored_parent.message_inbox), 1)
        self.assertEqual(
            restored_parent.message_inbox[0]["occurrence_count"], 2
        )
        await restored.close()

    async def test_unknown_alert_lifecycle_and_manual_clear(self):
        manager = ATTManager(
            Agent("Root", "Architect", self.client),
            ATTConfig(
                workspace_root=self.tmpdir,
                audit_unknown_escalation_mode="queue",
                audit_unknown_soft_threshold=2,
            ),
        )
        parent = manager.create_agent_team(manager.root_ai)
        child = manager.create_agent_team(parent)
        result = AuditResult(
            AuditStatus.UNKNOWN, "Audit unavailable.", "TimeoutError"
        )
        await manager.supervisor.report_unknown(child, result, manager)
        await manager.supervisor.report_unknown(child, result, manager)
        self.assertEqual(len(parent.message_inbox), 1)
        alert = parent.message_inbox[0]
        self.assertEqual(alert["occurrence_count"], 2)
        self.assertEqual(alert["state"], "pending")

        parent.execute_reasoning_step = AsyncMock(return_value="handled")
        await manager.execute_team_discussion(
            parent, "normal discussion", rounds=1, skip_audit=True
        )
        self.assertEqual(parent.message_inbox, [])

        await manager.supervisor.report_unknown(child, result, manager)
        repeated = False

        async def receive_repeat(*args, **kwargs):
            nonlocal repeated
            if not repeated:
                repeated = True
                await manager.supervisor.report_unknown(child, result, manager)
            return "handled"

        parent.execute_reasoning_step = AsyncMock(side_effect=receive_repeat)
        await manager.execute_team_discussion(
            parent, "discussion with a repeated alert", rounds=1,
            skip_audit=True,
        )
        self.assertEqual(len(parent.message_inbox), 1)
        self.assertEqual(parent.message_inbox[0]["state"], "pending")
        self.assertEqual(parent.message_inbox[0]["occurrence_count"], 2)
        self.assertNotIn("processing_count", parent.message_inbox[0])
        self.assertTrue(
            manager.acknowledge_unknown_alert(
                parent.team_id,
                parent.message_inbox[0]["fingerprint"],
            )
        )

        await manager.supervisor.report_unknown(child, result, manager)
        fingerprint = parent.message_inbox[0]["fingerprint"]
        parent.execute_reasoning_step = AsyncMock(
            side_effect=ATTException("discussion failed")
        )
        with self.assertRaises(ATTException):
            await manager.execute_team_discussion(
                parent, "failing discussion", rounds=1, skip_audit=True
            )
        self.assertEqual(parent.message_inbox[0]["state"], "pending")
        self.assertTrue(manager.acknowledge_unknown_alert(parent.team_id, fingerprint))

        await manager.supervisor.report_unknown(child, result, manager)
        fingerprint = parent.message_inbox[0]["fingerprint"]
        reasoning_started = asyncio.Event()

        async def cancelled_reasoning(*args, **kwargs):
            reasoning_started.set()
            await asyncio.Event().wait()

        parent.execute_reasoning_step = AsyncMock(
            side_effect=cancelled_reasoning
        )
        cancelled_discussion = asyncio.create_task(
            manager.execute_team_discussion(
                parent, "cancelled discussion", rounds=1, skip_audit=True
            )
        )
        await reasoning_started.wait()
        cancelled_discussion.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await cancelled_discussion
        self.assertEqual(parent.message_inbox[0]["state"], "pending")
        self.assertNotIn("processing_count", parent.message_inbox[0])
        self.assertTrue(
            manager.acknowledge_unknown_alert(parent.team_id, fingerprint)
        )

        for index in range(3):
            parent.receive_message(
                {
                    "type": "audit_unknown_escalation",
                    "from": "Supervisor",
                    "failed_team_id": child.team_id,
                    "reason": f"unique-{index}",
                    "cause": "outage",
                }
            )
        self.assertEqual(len(parent.message_inbox), 3)
        self.assertEqual(manager.clear_unknown_alerts(parent.team_id), 3)
        await manager.close()

    async def test_callbacks_are_ordered_nonblocking_and_isolated(self):
        manager = ATTManager(
            Agent("Root", "Architect", self.client),
            ATTConfig(workspace_root=self.tmpdir),
        )
        gate = threading.Event()
        started = threading.Event()
        observed = []

        def callback(event, details):
            observed.append(event)
            if event == "slow":
                started.set()
                gate.wait(5)
            if event == "broken":
                raise RuntimeError("observer failure")

        manager.on_system_event = callback
        before = time.monotonic()
        manager._emit_callback("on_system_event", "slow", {})
        self.assertLess(time.monotonic() - before, 0.05)
        await asyncio.to_thread(started.wait, 5)
        manager._emit_callback("on_system_event", "broken", {})
        manager._emit_callback("on_system_event", "last", {})
        gate.set()
        await manager.flush_callbacks()
        self.assertEqual(observed, ["slow", "broken", "last"])

        async_seen = []

        async def async_callback(event, details):
            async_seen.append(event)

        manager.on_system_event = async_callback
        manager._emit_callback("on_system_event", "async", {})
        await manager.flush_callbacks()
        self.assertEqual(async_seen, ["async"])
        await manager.close()

    async def test_retry_types_and_zero_retry_semantics(self):
        class Flaky:
            def __init__(self, error):
                self.calls = 0
                self.error = error

            async def generate(self, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    raise self.error
                return "ok"

        transient = Flaky(ConnectionError("offline"))
        self.assertEqual(
            await generate_with_retry(transient, "prompt", retries=1, backoff_factor=0),
            "ok",
        )
        permanent = Flaky(ValueError("invalid request"))
        with self.assertRaises(LLMGenerationError):
            await generate_with_retry(permanent, "prompt", retries=5)
        self.assertEqual(permanent.calls, 1)
        no_retry = Flaky(ConnectionError("offline"))
        with self.assertRaises(LLMGenerationError):
            await generate_with_retry(no_retry, "prompt", retries=0)
        self.assertEqual(no_retry.calls, 1)

    async def test_hard_token_budget_rejects_client_without_cap_api(self):
        class NoCapClient:
            async def generate(
                self,
                prompt,
                system_instruction=None,
                temperature=0.3,
                require_json=False,
            ):
                return {"text": "ok", "usage": {"total_tokens": 3}}

        client = NoCapClient()
        manager = ATTManager(
            Agent("Root", "Architect", client),
            ATTConfig(
                workspace_root=self.tmpdir,
                model_token_limits={"default": 10},
                model_max_output_tokens={"default": 6},
            ),
        )
        with self.assertRaisesRegex(
            LLMGenerationError, "max_output_tokens or max_tokens"
        ):
            await generate_with_retry(client, "12345678", manager=manager)
        self.assertEqual(manager.token_budget.available("default"), 10)
        self.assertNotIn("default", manager.model_token_usage)
        await manager.close()

    async def test_hanging_llm_does_not_block_close(self):
        started = asyncio.Event()

        class HangingClient:
            async def generate(self, **kwargs):
                started.set()
                await asyncio.Event().wait()

        client = HangingClient()
        manager = ATTManager(
            Agent("Root", "Architect", client),
            ATTConfig(workspace_root=self.tmpdir),
        )
        team = manager.create_agent_team(manager.root_ai)
        task = asyncio.create_task(
            manager.execute_team_discussion(
                team, "hang", rounds=1, skip_audit=True
            )
        )
        await started.wait()
        await asyncio.wait_for(manager.close(), timeout=0.5)
        with self.assertRaises(asyncio.CancelledError):
            await task


if __name__ == "__main__":
    unittest.main()
