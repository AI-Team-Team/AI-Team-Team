"""Library provisioning publishes only under its live captured authority."""

import asyncio
import threading
from pathlib import Path
from unittest.mock import patch

from ai_team_team.core.activity.contracts import AgentTeamScope
from ai_team_team.core.manager.libraries import factory

from ._support import BackgroundTestCase


class LibraryPublicationTests(BackgroundTestCase):
    def team(self):
        return self.manager.bootstrap_agent_team(self.root,
            member_configs={f"Member{i}": {"model": "fixture"} for i in range(3)})

    async def create(self, team):
        return await self.manager.start_background_task("create_doc_library",
            {"name": "Independent library", "description": "Background provisioning"},
            actor=team.members[0], scope=AgentTeamScope(team_id=team.team_id))

    async def test_successful_creation_registers_one_owned_library(self):
        team = self.team()
        before = set(self.manager.libraries)
        handle = await self.create(team)
        await self.finish(handle)
        added = set(self.manager.libraries) - before
        self.assertEqual(len(added), 1)
        library = self.manager.libraries[added.pop()]
        self.assertEqual(library.owner_team_id, team.team_id)
        self.assertTrue(Path(library.root_dir).is_dir())
        self.assertIs(library._resource_gate, self.manager._resources)

    async def test_failed_staging_leaves_no_library_or_directory(self):
        team = self.team()
        managed = Path(self.workspace.name) / ".att_doc_libs"
        before = set(self.manager.libraries), set(managed.iterdir())
        with patch.object(self.manager, "_build_document_library", side_effect=RuntimeError("Provisioning failed.")):
            handle = await self.create(team)
            await self.finish(handle)
        self.assertEqual(before, (set(self.manager.libraries), set(managed.iterdir())))
        self.assertEqual(self.manager.inspect_background_task(handle.execution_id, actor=team.members[0]).execution_state, "failed")

    async def test_cancelled_staging_cannot_publish_a_late_library(self):
        team = self.team()
        entered, release, cleaned = threading.Event(), threading.Event(), threading.Event()
        build = self.manager._build_document_library
        cleanup = factory.shutil.rmtree
        managed = Path(self.workspace.name) / ".att_doc_libs"
        before = set(self.manager.libraries), set(managed.iterdir())

        def delayed(**kwargs):
            library = build(**kwargs)
            entered.set()
            if not release.wait(10):
                raise TimeoutError("Library staging was not released.")
            return library

        def record_cleanup(path, **kwargs):
            cleanup(path, **kwargs)
            if ".att-library-stage-" in str(path):
                cleaned.set()

        with patch.object(self.manager, "_build_document_library", delayed), patch.object(factory.shutil, "rmtree", record_cleanup):
            handle = await self.create(team)
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 5))
                await self.manager.cancel_background_task(handle.execution_id, actor=team.members[0])
                await asyncio.wait_for(self.manager._executions.jobs[handle.execution_id].finished.wait(), 5)
            finally:
                release.set()
                self.assertTrue(await asyncio.to_thread(cleaned.wait, 5))
        self.assertEqual(before, (set(self.manager.libraries), set(managed.iterdir())))
