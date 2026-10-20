"""History restores without executable bindings, replay, or silent reference repair."""

import asyncio
import json
import sqlite3
from pathlib import Path
from unittest.mock import Mock
from contextlib import closing

from ai_team_team import Agent, StateRestoreError, ToolBusinessError
from test.test_att.test_agent_activity._support import idle
from test.test_att.test_autonomous_activity_phase0._fixtures import ModelStep

from ._support import BackgroundTestCase, contract


class PersistenceTests(BackgroundTestCase):
    async def durable(self):
        await self.manager.close()
        self.manager = self.make_manager(self.root, durable=True)
        self.manager._activity.schedule_notice = Mock()
        self.manager.register_token_counter("fixture", lambda text: len(text))

    async def completed(self):
        async def operation() -> str:
            return "DURABLE_TASK_RESULT"
        self.manager.register_tool("operation", func=operation, execution_contract=contract(),
                                   resource_resolver=lambda scope, arguments: ())
        handle = await self.start("operation", description="Retained operation", labels=("one", "two"))
        await self.finish(handle)
        return handle

    async def test_result_attention_config_and_provenance_round_trip(self):
        await self.durable()
        handle = await self.completed()
        await self.manager.acknowledge_background_task(handle.execution_id, actor=self.root)
        self.manager.config.executions.retain_results_after_source_revocation = False
        await self.manager.save_state()
        await self.manager.load_state(self.manager.db_path)
        self.root = self.manager.root_ai
        view = self.manager.inspect_background_task(handle.execution_id, actor=self.root)
        self.assertEqual((view.execution_state, view.attention_state, view.labels), ("completed", "acknowledged", ("one", "two")))
        self.assertFalse(self.manager.config.executions.retain_results_after_source_revocation)
        self.assertIn("DURABLE_TASK_RESULT", (await self.manager.read_background_task_result(handle.execution_id, actor=self.root)).content)
        self.assertFalse(self.manager._executions.jobs)
        with closing(sqlite3.connect(self.manager.db_path)) as database:
            self.assertEqual(database.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertEqual(database.execute("SELECT count(*) FROM execution_payloads").fetchone(), (2,))

    async def test_unfinished_host_task_wakes_same_owner_without_replay_or_reconnect(self):
        await self.durable()
        started, release = asyncio.Event(), asyncio.Event()
        calls = []

        async def operation() -> str:
            calls.append(True)
            started.set()
            await release.wait()
            return "old execution"

        self.manager.register_tool("operation", func=operation, execution_contract=contract())
        handle = await self.start("operation")
        await asyncio.wait_for(started.wait(), 5)
        path = self.manager.db_path
        owner = self.root.agent_id
        await self.manager.close()
        restored = self.make_manager(Agent("StagingRoot", "Architect", self.client))
        restored.register_token_counter("fixture", lambda text: len(text))
        self.client.steps.append(ModelStep(idle()))
        self.manager = restored
        await restored.load_state(path)
        await self.settle()
        view = restored.inspect_background_task(handle.execution_id, actor=restored.root_ai)
        self.assertEqual(view.execution_state, "running")
        self.assertTrue(view.outcome_unconfirmed)
        self.assertEqual(calls, [True])
        self.assertNotIn("operation", restored.global_tools)
        self.assertEqual(restored.root_ai.agent_id, owner)
        self.assertIn("1 unconfirmed outcomes", restored._executions.summary(restored.root_ai))
        self.assertTrue(restored._activity.sessions[owner].intent == "idle")
        self.assertNotIn(handle.execution_id, restored._executions.jobs)
        self.assertTrue(all(job.tool.name == "set_activity_intent"
            and job.context.generation == restored._resources.generation for job in restored._executions.jobs.values()))
        self.assertTrue(any(row.values["execution_id"] == handle.execution_id for row in self.records("recovery_incidents")))

    async def test_transient_result_does_not_reappear_or_reread_after_restore(self):
        await self.durable()
        library = self.manager.libraries[self.root.private_doc_library_id]
        library.write_file("private.txt", "TRANSIENT_RESULT_BODY")
        handle = await self.start("read_private_file", {"path": "private.txt"})
        await self.finish(handle)
        await self.manager.save_state()
        await self.manager.load_state(self.manager.db_path)
        with self.assertRaisesRegex(ToolBusinessError, "not retained"):
            await self.manager.read_background_task_result(handle.execution_id, actor=self.manager.root_ai)

    async def test_schema_thirteen_is_rejected_before_any_database_mutation(self):
        await self.durable()
        await self.completed()
        target = str(Path(self.workspace.name) / "old-schema.sqlite")
        await self.manager.save_state(target)
        with closing(sqlite3.connect(target)) as database:
            database.execute("UPDATE manager_config SET config_value='13' WHERE config_key='schema_version'")
            database.commit()
        before = Path(target).read_bytes()
        with self.assertRaisesRegex(StateRestoreError, "Unsupported state schema"):
            await self.manager.load_state(target)
        self.assertEqual(Path(target).read_bytes(), before)

    async def test_corrupt_execution_matrix_preserves_original_manager_and_files(self):
        await self.durable()
        handle = await self.completed()
        original_root = self.manager.root_ai
        cases = (
            ("UPDATE executions SET metadata=? WHERE execution_id=?", (json.dumps({"description": "invalid", "labels": [], "origin": "model"}), handle.execution_id)),
            ("UPDATE executions SET source_references=? WHERE execution_id=?", (json.dumps([{"kind": "library", "lib_id": "missing", "path": "file.txt", "scope_team_id": None}]), handle.execution_id)),
            ("UPDATE executions SET contract_snapshot=? WHERE execution_id=?", (json.dumps({"effects": ["self_modification"], "background_allowed": True, "required_scope": "personal", "executor": "callable"}), handle.execution_id)),
            ("UPDATE executions SET started_at=-1 WHERE execution_id=?", (handle.execution_id,)),
            ("UPDATE execution_payloads SET digest='wrong' WHERE execution_id=?", (handle.execution_id,)),
        )
        for index, (statement, arguments) in enumerate(cases):
            with self.subTest(case=index):
                target = str(Path(self.workspace.name) / f"corrupt-{index}.sqlite")
                await self.manager.save_state(target)
                with closing(sqlite3.connect(target)) as database:
                    database.execute(statement, arguments)
                    database.commit()
                with self.assertRaises(StateRestoreError):
                    await self.manager.load_state(target)
                self.assertIs(self.manager.root_ai, original_root)
                self.assertEqual(self.manager.inspect_background_task(handle.execution_id, actor=original_root).execution_state, "completed")
