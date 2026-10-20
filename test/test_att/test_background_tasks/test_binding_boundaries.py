"""Physical targets and failure bodies retain the authority accepted at admission."""

import asyncio
import threading
from unittest.mock import patch

from ai_team_team import ResourceClaim, ToolBusinessError
from ai_team_team.core.activity.contracts import AgentTeamScope
from ai_team_team.doc_library import DocumentLibrary

from . import test_resources_and_privacy as fixtures
from ._support import BackgroundTestCase, contract


class BindingBoundaryTests(BackgroundTestCase):
    async def linked_libraries(self):
        source, reader, old = fixtures.RetainedResultTests.teams(self)
        alias = await self.manager._library_service.create_team_library(source, "Alias", "Link fixture")
        replacement = await self.manager._library_service.create_team_library(source, "Replacement", "Link fixture")
        replacement.write_file("source.txt", "REPLACEMENT_SOURCE_BODY")
        for library in (alias, replacement):
            self.manager.library_permissions.setdefault(library.lib_id, {}).setdefault("/", {})[reader.team_id] = "WRITE"
        self.manager.library_permissions[old.lib_id]["/"][reader.team_id] = "WRITE"
        await self.manager.create_library_link(source.team_id, alias.lib_id, "link.txt", old.lib_id, "source.txt")
        return source, reader, alias, old, replacement

    async def retarget(self, source, alias, target):
        await self.manager.delete_library_path(source.team_id, alias.lib_id, "link.txt")
        await self.manager.create_library_link(source.team_id, alias.lib_id, "link.txt", target.lib_id, "source.txt")

    async def test_retarget_while_attempt_receipt_settles_does_not_read_new_source(self):
        source, reader, alias, _old, replacement = await self.linked_libraries()
        entered, release = asyncio.Event(), asyncio.Event()
        commit = self.manager._records.commit

        async def pause(records, **kwargs):
            records = tuple(records)
            receipt = await commit(records, **kwargs)
            if any(row.table_name == "execution_attempts" for row in records):
                entered.set()
                await release.wait()
            return receipt

        with patch.object(self.manager._records, "commit", pause):
            handle = await self.manager.start_background_task("read_library_file",
                {"lib_id": alias.lib_id, "path": "link.txt"}, actor=reader.members[0],
                scope=AgentTeamScope(team_id=reader.team_id))
            try:
                await asyncio.wait_for(entered.wait(), 5)
                await self.retarget(source, alias, replacement)
            finally:
                release.set()
            job = await self.finish(handle)
        self.assertEqual(job.result.status.value, "denied")
        self.assertNotIn("REPLACEMENT_SOURCE_BODY", str(self.records("execution_payloads")))

    async def test_retarget_between_resolution_and_physical_write_is_rejected(self):
        source, reader, alias, old, replacement = await self.linked_libraries()
        entered, release = threading.Event(), threading.Event()
        write = DocumentLibrary.write_file

        def delayed(library, path, content):
            if library is old and content == "MUST_NOT_BE_WRITTEN":
                entered.set()
                if not release.wait(10):
                    raise TimeoutError("Physical write was not released.")
            return write(library, path, content)

        with patch.object(DocumentLibrary, "write_file", delayed):
            handle = await self.manager.start_background_task("write_library_file",
                {"lib_id": alias.lib_id, "path": "link.txt", "content": "MUST_NOT_BE_WRITTEN"},
                actor=reader.members[0], scope=AgentTeamScope(team_id=reader.team_id))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 5))
                await self.retarget(source, alias, replacement)
            finally:
                release.set()
            job = await self.finish(handle)
        self.assertEqual(job.result.status.value, "denied")
        self.assertEqual(old.read_text("source.txt"), "AUTHORIZED_SOURCE_RESULT")
        self.assertEqual(replacement.read_text("source.txt"), "REPLACEMENT_SOURCE_BODY")

    async def test_actual_target_must_be_claimed_even_if_alias_has_returned_to_original(self):
        source, reader, alias, old, replacement = await self.linked_libraries()
        entered, release = threading.Event(), threading.Event()
        read = DocumentLibrary.read_file_slice

        def substitute(library, path, **kwargs):
            if library is old:
                entered.set()
                if not release.wait(10):
                    raise TimeoutError("Physical read was not released.")
                # Simulate a target selected during a transient A -> B -> A
                # remapping. Current aliases alone cannot authorize this IO.
                return read(replacement, path, **kwargs)
            return read(library, path, **kwargs)

        with patch.object(DocumentLibrary, "read_file_slice", substitute):
            handle = await self.manager.start_background_task("read_library_file",
                {"lib_id": alias.lib_id, "path": "link.txt"}, actor=reader.members[0],
                scope=AgentTeamScope(team_id=reader.team_id))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 5))
                await self.retarget(source, alias, replacement)
                await self.retarget(source, alias, old)
            finally:
                release.set()
            job = await self.finish(handle)
        self.assertEqual(job.result.status.value, "denied")
        self.assertNotIn("REPLACEMENT_SOURCE_BODY", str(self.records("execution_payloads")))

    async def test_failure_body_is_not_an_authorization_bypass(self):
        _source, reader, library = fixtures.RetainedResultTests.teams(self)
        entered, release = asyncio.Event(), asyncio.Event()

        async def operation() -> str:
            body = library.read_text("source.txt")
            entered.set()
            await release.wait()
            raise ToolBusinessError("Validation failed: " + body)

        self.manager.register_tool("operation", func=operation, execution_contract=contract(required_scope="agent_team"),
            resource_resolver=lambda scope, args: (ResourceClaim(namespace="library", resource_id=library.lib_id,
                path="source.txt", access="read"),))
        owner = reader.members[0]
        handle = await self.manager.start_background_task("operation", {}, actor=owner,
            scope=AgentTeamScope(team_id=reader.team_id))
        try:
            await asyncio.wait_for(entered.wait(), 5)
            with self.manager._resources.mutation():
                self.manager.library_permissions[library.lib_id]["/"].pop(reader.team_id)
        finally:
            release.set()
        job = await self.finish(handle)
        self.assertEqual(job.result.status.value, "denied")
        self.assertNotIn("AUTHORIZED_SOURCE_RESULT", job.result.content)
        self.assertNotIn("AUTHORIZED_SOURCE_RESULT", str(self.records("execution_payloads")))
        self.assertNotIn("AUTHORIZED_SOURCE_RESULT",
            (await self.manager.read_background_task_result(handle.execution_id, actor=owner)).content)

    async def test_listing_and_link_creation_capture_all_accessed_targets(self):
        source, reader, alias, old, _replacement = await self.linked_libraries()
        owner = reader.members[0]
        handle = await self.manager.start_background_task("list_library_files", {"lib_id": alias.lib_id}, actor=owner,
            scope=AgentTeamScope(team_id=reader.team_id))
        job = await self.finish(handle)
        self.assertFalse(job.result.failed)
        self.assertIn("link.txt", job.result.content)
        created = await self.manager.start_background_task("create_library_link", {
            "source_lib_id": reader.doc_library.lib_id, "source_path": "chain.txt",
            "target_lib_id": alias.lib_id, "target_path": "link.txt"}, actor=owner,
            scope=AgentTeamScope(team_id=reader.team_id))
        self.assertFalse((await self.finish(created)).result.failed)
        for execution in (handle, created):
            row = self.manager._records.index[("executions", (execution.execution_id,))]
            self.assertIn(old.lib_id, {item["lib_id"] for item in row.values["source_references"]})
        self.manager.config.executions.retain_results_after_source_revocation = False
        self.manager.library_permissions[old.lib_id]["/"].pop(reader.team_id)
        with self.assertRaises(PermissionError):
            await self.manager.read_background_task_result(handle.execution_id, actor=owner)
