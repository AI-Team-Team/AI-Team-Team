"""Waiting identity publication cannot outlive its executor or resource lease."""

import asyncio
import threading
from pathlib import Path
from unittest.mock import patch

from ai_team_team import Agent, LLMResponse, Tool, ToolCall
from ai_team_team.core.tool_runtime import ToolExecutor

from ._support import ActivityTestCase


class RegistrationPublicationTests(ActivityTestCase):
    def topology_holder(self, held, release):
        with self.manager._topology_lock:
            held.set()
            if not release.wait(15):
                raise TimeoutError("The topology reader was not released.")

    def assert_unpublished(self, candidate):
        self.assertNotIn(candidate.agent_id, self.manager._agents_by_id)
        self.assertNotIn(candidate.name, self.manager.agents)
        self.assertNotIn(f"PDL-{candidate.agent_id}", self.manager.libraries)
        self.assertIsNone(candidate.private_doc_library_id)
        self.assertIsNone(candidate._manager)
        self.assertFalse(Path(self.workspace.name, ".att_doc_libs", f"PDL-{candidate.agent_id}").exists())

    async def test_native_sibling_revocation_cancels_registration_waiting_for_topology(self):
        held, release, checked, finished = (threading.Event() for _ in range(4))
        candidate = Agent("LateIdentity", "Researcher", self.client)
        registering_thread = None
        errors = []
        original = self.manager._resources.check_authority

        def check():
            original()
            if threading.get_ident() == registering_thread:
                checked.set()

        def register():
            nonlocal registering_thread
            registering_thread = threading.get_ident()
            try:
                self.manager.register_agent(candidate)
            except Exception as error:
                errors.append(error)
            finally:
                finished.set()

        async def register_person():
            await asyncio.to_thread(register)
            return "Registration ended"

        async def cancel_batch():
            if not await asyncio.to_thread(checked.wait, 5):
                raise TimeoutError("Registration did not reach its authority check.")
            raise asyncio.CancelledError("Cancel the waiting registration")

        self.manager.register_tool("register_person", func=register_person)
        self.manager.register_tool("cancel_batch", func=cancel_batch)
        self.steps(LLMResponse(tool_calls=[
            ToolCall("register", "register_person", {}),
            ToolCall("cancel", "cancel_batch", {}),
        ]))
        holder = asyncio.create_task(asyncio.to_thread(self.topology_holder, held, release))
        with patch.object(self.manager._resources, "check_authority", check):
            try:
                self.assertTrue(await asyncio.to_thread(held.wait, 5))
                admission = await self.manager.activate_agent(self.root.agent_id)
                with self.assertRaises(asyncio.CancelledError):
                    await self.wait(admission)
                # Revocation can acquire the resource lock without releasing
                # the unrelated topology reader or retaining this executor.
                self.assertTrue(await asyncio.to_thread(finished.wait, 5))
                self.assertFalse(release.is_set())
                self.assert_unpublished(candidate)
            finally:
                release.set()
                await asyncio.wait_for(holder, 5)
                await asyncio.gather(*tuple(self.manager._activity.workers), return_exceptions=True)
                await asyncio.gather(*tuple(self.manager._activity.tool_tasks), return_exceptions=True)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], PermissionError)
        self.assert_unpublished(candidate)

    async def host_registration_wait(self, fence):
        held, release, checked = (threading.Event() for _ in range(3))
        candidate = Agent("WaitingHostRegistration", "Researcher", self.client)
        registering_thread = None
        original = self.manager._resources.check_authority

        def check():
            original()
            if threading.get_ident() == registering_thread:
                checked.set()

        def register():
            nonlocal registering_thread
            registering_thread = threading.get_ident()
            return self.manager.register_agent(candidate)

        holder = asyncio.create_task(asyncio.to_thread(self.topology_holder, held, release))
        waiting = None
        with patch.object(self.manager._resources, "check_authority", check):
            try:
                self.assertTrue(await asyncio.to_thread(held.wait, 5))
                waiting = asyncio.create_task(asyncio.to_thread(register))
                await asyncio.wait_for(asyncio.to_thread(checked.wait, 5), 6)
                self.assertTrue(checked.is_set())
                await fence()
                with self.assertRaisesRegex(RuntimeError, "closed or being published"):
                    await asyncio.wait_for(waiting, 5)
                self.assert_unpublished(candidate)
            finally:
                release.set()
                await asyncio.wait_for(holder, 5)
                if waiting is not None:
                    await asyncio.gather(waiting, return_exceptions=True)
        self.assert_unpublished(candidate)

    async def test_shutdown_revokes_waiting_host_registration_without_lock_inversion(self):
        await self.host_registration_wait(self.manager.close)
        self.assertTrue(self.manager._closed)

    async def test_publication_fence_rejects_waiting_registration(self):
        async def fence():
            self.manager._resources.begin_publication()

        try:
            await self.host_registration_wait(fence)
        finally:
            if self.manager._resources.blocked:
                self.manager._resources.finish_publication(committed=False)

    async def test_cancelled_team_publication_discards_its_offregistry_stage(self):
        held, release, checked, finished = (threading.Event() for _ in range(4))
        original_stage = self.manager._create_agent_team
        original_check = self.manager._resources.check_authority
        stage = None
        creating_thread = None
        errors = []

        def check():
            original_check()
            if stage is not None and threading.get_ident() == creating_thread:
                checked.set()

        def prepare(**kwargs):
            nonlocal stage
            stage = original_stage(**kwargs)
            return stage

        def create():
            nonlocal creating_thread
            creating_thread = threading.get_ident()
            try:
                self.manager.create_agent_team(self.root, initial_docs={"note.txt": "staged"})
            except Exception as error:
                errors.append(error)
            finally:
                finished.set()
            return "Creation ended"

        tool = Tool("create", func=create)
        holder = asyncio.create_task(asyncio.to_thread(self.topology_holder, held, release))
        execution = None
        with (
            patch.object(self.manager, "_create_agent_team", prepare),
            patch.object(self.manager._resources, "check_authority", check),
        ):
            try:
                self.assertTrue(await asyncio.to_thread(held.wait, 5))
                execution = asyncio.create_task(ToolExecutor(None, self.root, self.manager).execute(
                    tool.name, tools={tool.name: tool}
                ))
                self.assertTrue(await asyncio.to_thread(checked.wait, 5))
                execution.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await execution
                self.assertTrue(await asyncio.to_thread(finished.wait, 5))
            finally:
                release.set()
                await asyncio.wait_for(holder, 5)
                if execution is not None:
                    await asyncio.gather(execution, return_exceptions=True)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], PermissionError)
        self.assertFalse(self.manager.teams)
        self.assertEqual(set(self.manager._agents_by_id), {self.root.agent_id})
        self.assertEqual(set(self.manager.libraries), {self.root.private_doc_library_id})
        self.assertFalse(tuple(Path(self.workspace.name, ".att_doc_libs").glob(".att-team-stage-*")))
        for candidate in stage["new_agents"]:
            self.assert_unpublished(candidate)

    async def test_successful_registration_and_staged_team_creation_remain_reentrant(self):
        person = self.manager.register_agent(Agent("Independent", "Researcher", self.client))
        library_id = person.private_doc_library_id
        team = self.manager.bootstrap_agent_team(
            self.root, existing_members=[person],
            roles_and_presets=[("NewA", "Researcher"), ("NewB", "Reviewer")],
        )
        self.assertIn(person, team.members)
        self.assertIs(self.manager._agents_by_id[person.agent_id], person)
        self.assertEqual(person.private_doc_library_id, library_id)
        self.assertEqual(len(self.manager._agents_by_id), 4)
