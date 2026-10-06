"""Background callbacks cannot read partially published teams or restored state."""

import asyncio
import os
import threading
import unittest
from unittest.mock import patch

from ai_team_team import StateRestoreError
from ai_team_team.core.tool_runtime import ToolExecutor

from ._fixture import DiscoveryFixture


class BackgroundPublicationTests(DiscoveryFixture, unittest.IsolatedAsyncioTestCase):
    async def _start_reader(self, query):
        started = threading.Event()
        ready = threading.Event()
        completed = threading.Event()
        results = []
        errors = []

        def observer(event, payload):
            if event != "directory_snapshot":
                return
            started.set()
            try:
                if not ready.wait(5):
                    raise TimeoutError("The test publication did not start.")
                results.append(query())
            except Exception as exc:
                errors.append(exc)
            finally:
                completed.set()

        self.manager.on_system_event = observer
        self.manager._emit_callback("on_system_event", "directory_snapshot", {})
        async with asyncio.timeout(5):
            while not started.is_set():
                await asyncio.sleep(0)
        return ready, completed, results, errors

    async def _finish_reader(self, ready):
        ready.set()
        await self.manager.flush_callbacks()
        self.manager.on_system_event = None

    async def _prepare_restore(self):
        self.manager.create_agent_team(self.root, team_purpose="Persisted organization")
        await asyncio.sleep(0)
        path = os.path.join(self.workspace.name, "directory.sqlite")
        expected = self.manager.list_entities(end_index=999).model_dump()
        await self.manager.save_state(path)
        self.person("UnsavedPerson")
        self.manager.create_agent_team(self.root, team_purpose="Unsaved organization")
        await asyncio.sleep(0)
        return path, expected

    async def test_callback_reads_one_complete_directory_during_restore(self):
        path, expected = await self._prepare_restore()
        ready, completed, results, errors = await self._start_reader(
            lambda: self.manager.list_entities(end_index=999).model_dump()
        )
        original = self.manager._agent_registry.replace_indexes

        def pause_between_agents_and_teams(*args, **kwargs):
            original(*args, **kwargs)
            ready.set()
            completed.wait(0.025)

        try:
            with patch.object(
                self.manager._agent_registry,
                "replace_indexes",
                side_effect=pause_between_agents_and_teams,
            ):
                await self.manager.load_state(path)
        finally:
            await self._finish_reader(ready)
        self.assertEqual(errors, [])
        self.assertEqual(results, [expected])

    async def test_callback_cannot_observe_state_that_restore_rolls_back(self):
        path, _expected = await self._prepare_restore()
        expected = self.manager.list_entities(end_index=999).model_dump()
        ready, completed, results, errors = await self._start_reader(
            lambda: self.manager.list_entities(end_index=999).model_dump()
        )

        def fail_publication(*args, **kwargs):
            ready.set()
            completed.wait(0.025)
            raise RuntimeError("Injected runtime publication failure.")

        try:
            with patch.object(self.manager.broker, "restore", side_effect=fail_publication):
                with self.assertRaisesRegex(StateRestoreError, "Injected runtime publication"):
                    await self.manager.load_state(path)
        finally:
            await self._finish_reader(ready)
        self.assertEqual(errors, [])
        self.assertEqual(results, [expected])
        self.assertEqual(self.manager.list_entities(end_index=999).model_dump(), expected)

    async def test_callback_never_reads_half_of_a_team_status_update(self):
        team = self.manager.create_agent_team(self.root)
        ready, completed, results, errors = await self._start_reader(
            lambda: self.manager.inspect_entity("agent_team", team.team_id)
        )
        original = type(team).__setattr__

        def pause_between_purpose_and_progress(instance, name, value):
            original(instance, name, value)
            if instance is team and name == "team_purpose":
                ready.set()
                completed.wait(0.025)

        try:
            with patch.object(type(team), "__setattr__", pause_between_purpose_and_progress):
                result = await ToolExecutor(team, team.members[0], self.manager).execute(
                    "update_team_status",
                    kwargs={"purpose": "Updated purpose", "progress": "Updated progress"},
                    tools=self.manager.get_available_tools(team),
                )
        finally:
            await self._finish_reader(ready)
        self.assertEqual(result.status.value, "success")
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].team_purpose, "Updated purpose")
        self.assertEqual(results[0].team_progress, "Updated progress")

    async def test_failed_audit_team_creation_does_not_expose_partial_auditors(self):
        expected = self.manager.list_entities(end_index=999).model_dump()
        ready, completed, results, errors = await self._start_reader(
            lambda: self.manager.list_entities(end_index=999).model_dump()
        )
        original_register = self.manager.register_agent
        original_rollback = self.manager._rollback_published_libraries

        def fail_after_one_registration(*args, **kwargs):
            original_register(*args, **kwargs)
            raise RuntimeError("Injected audit registration failure.")

        def pause_before_rollback(*args, **kwargs):
            ready.set()
            completed.wait(0.025)
            return original_rollback(*args, **kwargs)

        try:
            with (
                patch.object(
                    self.manager, "register_agent", side_effect=fail_after_one_registration
                ),
                patch.object(
                    self.manager, "_rollback_published_libraries", side_effect=pause_before_rollback
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "Injected audit registration"):
                    self.manager._team_creation.create_supervisory_team()
        finally:
            await self._finish_reader(ready)
        self.assertEqual(errors, [])
        self.assertEqual(results, [expected])
        self.assertEqual(self.manager.list_entities(end_index=999).model_dump(), expected)
