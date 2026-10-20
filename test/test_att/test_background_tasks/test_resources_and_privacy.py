"""Resource exclusion is cross-owner; retained results are not renewed source access."""

import asyncio
import threading
from pathlib import Path
from unittest.mock import patch

from ai_team_team import ResourceClaim, StateRestoreError
from ai_team_team.core.activity.contracts import AgentTeamScope
from ai_team_team.database.persistence.records import thaw

from ._support import BackgroundTestCase, contract


class ResourceTests(BackgroundTestCase):
    async def test_conflicting_calls_serialize_while_independent_resources_progress(self):
        started, independent, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        events = []

        async def operation(key: str, index: int) -> str:
            events.append((key, index, "start"))
            if index == 1:
                started.set()
                await release.wait()
            if key == "independent":
                independent.set()
            events.append((key, index, "end"))
            return "done"

        def resources(scope, arguments):
            return (ResourceClaim(namespace="external", resource_id=arguments["key"]),)

        self.manager.register_tool("operation", func=operation, execution_contract=contract(
            effects=("artifact_write",), mutation_safety="managed_lease"), resource_resolver=resources)
        first = await self.start("operation", {"key": "shared", "index": 1})
        await asyncio.wait_for(started.wait(), 5)
        second = await self.start("operation", {"key": "shared", "index": 2})
        third = await self.start("operation", {"key": "independent", "index": 3})
        await asyncio.wait_for(independent.wait(), 5)
        self.assertNotIn(("shared", 2, "start"), events)
        release.set()
        for handle in (first, second, third):
            await self.finish(handle)
        self.assertLess(events.index(("shared", 1, "end")), events.index(("shared", 2, "start")))

    async def test_private_write_is_background_eligible_without_private_input_in_history(self):
        handle = await self.start("write_private_file", {"path": "notes.txt", "content": "PRIVATE_ARTIFACT_BODY"})
        await self.finish(handle)
        library = self.manager.libraries[self.root.private_doc_library_id]
        self.assertEqual(library.read_text("notes.txt"), "PRIVATE_ARTIFACT_BODY")
        inputs = next(row for row in self.records("execution_payloads") if row.values["content_kind"] == "input")
        self.assertNotIn("PRIVATE_ARTIFACT_BODY", str(thaw(inputs.values)))
        self.assertNotIn("PRIVATE_ARTIFACT_BODY", str(self.root.message_history))

    async def test_same_library_unrelated_physical_writes_can_stage_concurrently(self):
        library = self.manager.libraries[self.root.private_doc_library_id]
        first_entered, both_entered, release = threading.Event(), threading.Event(), threading.Event()
        count, guard = 0, threading.Lock()

        def fsync(_descriptor):
            nonlocal count
            with guard:
                count += 1
                first_entered.set()
                if count == 2:
                    both_entered.set()
            if not release.wait(10):
                raise TimeoutError("Physical writes did not release.")

        tasks = []
        with patch("ai_team_team.doc_library.os.fsync", fsync):
            try:
                tasks.append(asyncio.create_task(asyncio.to_thread(library.write_file, "first.txt", "first")))
                self.assertTrue(await asyncio.to_thread(first_entered.wait, 5))
                tasks.append(asyncio.create_task(asyncio.to_thread(library.write_file, "second.txt", "second")))
                self.assertTrue(await asyncio.to_thread(both_entered.wait, 5))
            finally:
                release.set()
                await asyncio.gather(*tasks)
        self.assertEqual(library.read_text("first.txt"), "first")
        self.assertEqual(library.read_text("second.txt"), "second")

    async def test_restore_rejects_a_live_executor_even_without_personal_activity(self):
        started, release = asyncio.Event(), asyncio.Event()

        async def operation() -> str:
            started.set()
            await release.wait()
            return "done"

        self.manager.register_tool("operation", func=operation, execution_contract=contract())
        handle = await self.start("operation")
        await asyncio.wait_for(started.wait(), 5)
        path = str(Path(self.workspace.name) / "export.sqlite")
        await self.manager.save_state(path)
        try:
            with self.assertRaisesRegex(StateRestoreError, "executors"):
                await self.manager.load_state(path)
        finally:
            release.set()
            await self.finish(handle)


class RetainedResultTests(BackgroundTestCase):
    async def test_restrictive_mode_rejects_unverifiable_external_source_provenance(self):
        async def external_read() -> str:
            return "EXTERNAL_PROTECTED_RESULT"

        self.manager.register_tool("external_read", func=external_read, execution_contract=contract())
        handle = await self.start("external_read")
        await self.finish(handle)
        self.assertIn("EXTERNAL_PROTECTED_RESULT", (await self.manager.read_background_task_result(handle.execution_id, actor=self.root)).content)
        self.manager.config.executions.retain_results_after_source_revocation = False
        with self.assertRaises(PermissionError):
            await self.manager.read_background_task_result(handle.execution_id, actor=self.root)
        self.assertFalse(self.manager.inspect_background_task(handle.execution_id, actor=self.root).result_available)

    def teams(self):
        first = self.manager.bootstrap_agent_team(self.root, member_configs={f"Source{i}": {"model": "fixture"} for i in range(3)})
        second = self.manager.bootstrap_agent_team(self.root, member_configs={f"Reader{i}": {"model": "fixture"} for i in range(3)})
        library = first.doc_library
        library.write_file("source.txt", "AUTHORIZED_SOURCE_RESULT")
        self.manager.library_permissions.setdefault(library.lib_id, {}).setdefault("/", {})[second.team_id] = "READ"
        return first, second, library

    async def test_default_retention_and_restrictive_mode_do_not_grant_new_source_access(self):
        _first, second, library = self.teams()
        owner = second.members[0]
        handle = await self.manager.start_background_task("read_library_file", {"lib_id": library.lib_id, "path": "/source.txt"},
            actor=owner, scope=AgentTeamScope(team_id=second.team_id))
        await self.finish(handle)
        self.manager.library_permissions[library.lib_id]["/"].pop(second.team_id)
        result = await self.manager.read_background_task_result(handle.execution_id, actor=owner)
        self.assertIn("AUTHORIZED_SOURCE_RESULT", result.content)
        with self.assertRaises(PermissionError):
            await self.manager.start_background_task("read_library_file", {"lib_id": library.lib_id, "path": "source.txt"},
                actor=owner, scope=AgentTeamScope(team_id=second.team_id))
        self.manager.config.executions.retain_results_after_source_revocation = False
        with self.assertRaises(PermissionError):
            await self.manager.read_background_task_result(handle.execution_id, actor=owner)
        view = self.manager.inspect_background_task(handle.execution_id, actor=owner)
        self.assertFalse(view.result_available)
        self.assertNotIn("AUTHORIZED_SOURCE_RESULT", view.model_dump_json())
        self.manager.config.executions.retain_results_after_source_revocation = True
        self.assertIn("AUTHORIZED_SOURCE_RESULT", (await self.manager.read_background_task_result(handle.execution_id, actor=owner)).content)

    async def test_restrictive_mode_cannot_borrow_new_membership_or_permissions(self):
        _first, second, library = self.teams()
        owner = second.members[0]
        original = (owner.agent_id, owner.system_instructions, owner.llm_client, owner.private_doc_library_id, list(owner.message_history))
        handle = await self.manager.start_background_task("read_library_file", {"lib_id": library.lib_id, "path": "source.txt"},
            actor=owner, scope=AgentTeamScope(team_id=second.team_id))
        await self.finish(handle)
        third = self.manager.bootstrap_agent_team(self.root, existing_members=[owner],
            member_configs={f"Later{i}": {"model": "fixture"} for i in range(2)})
        self.manager.library_permissions[library.lib_id]["/"] = {third.team_id: "READ"}
        self.manager.config.executions.retain_results_after_source_revocation = False
        with self.assertRaises(PermissionError):
            await self.manager.read_background_task_result(handle.execution_id, actor=owner)
        self.assertEqual(original, (owner.agent_id, owner.system_instructions, owner.llm_client, owner.private_doc_library_id, list(owner.message_history)))

    async def test_transient_private_read_never_persists_its_body_as_a_task_payload(self):
        self.manager.libraries[self.root.private_doc_library_id].write_file("private.txt", "TRANSIENT_PRIVATE_CONTENT")
        handle = await self.start("read_private_file", {"path": "private.txt"})
        await self.finish(handle)
        self.assertNotIn("TRANSIENT_PRIVATE_CONTENT", str([thaw(row.values) for row in self.records("execution_payloads")]))
        self.assertIn("TRANSIENT_PRIVATE_CONTENT", (await self.manager.read_background_task_result(handle.execution_id, actor=self.root)).content)
