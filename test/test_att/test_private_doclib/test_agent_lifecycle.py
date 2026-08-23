import asyncio
import os
import shutil
import sqlite3
import tempfile
import unittest

from ai_team_team import Agent, ATTConfig, ATTManager
from ai_team_team.core import StateRestoreError


class DummyClient:
    async def generate(self, prompt, **kwargs):
        return "ok"


class SequenceClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.prompt_snapshots = []

    async def generate(self, prompt, **kwargs):
        self.prompt_snapshots.append(repr(prompt))
        return self.responses.pop(0)


class TestPrivateAgentDocLib(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="att-private-")
        self.client = DummyClient()
        self.root = Agent("Root", "Architect", self.client)
        self.manager = ATTManager(
            self.root,
            ATTConfig(workspace_root=self.temp_dir),
        )
        self.manager.register_llm_client("default", self.client)

    async def asyncTearDown(self):
        await self.manager.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _activate(self, agent, team=None):
        agent_token = self.manager._active_tool_agent.set(agent)
        team_token = self.manager._active_team.set(team)
        return agent_token, team_token

    def _deactivate(self, tokens):
        agent_token, team_token = tokens
        self.manager._active_team.reset(team_token)
        self.manager._active_tool_agent.reset(agent_token)

    async def test_archive_retain_reactivate_and_delete(self):
        with self.assertRaises(ValueError):
            await self.manager.retire_agent(self.root.agent_id)

        member = Agent("StillMember", "Member", self.client)
        self.manager.create_agent_team(
            self.root,
            member_configs={
                "member": member,
                "peer-e": Agent("PeerE", "Peer", self.client),
                "peer-f": Agent("PeerF", "Peer", self.client),
            },
        )
        with self.assertRaises(ValueError):
            await self.manager.retire_agent(member.agent_id)

        creator = Agent("Creator", "Lead", self.client)
        self.manager.create_agent_team(creator)
        with self.assertRaises(ValueError):
            await self.manager.retire_agent(creator.agent_id)

        busy = Agent("Busy", "Worker", self.client)
        self.manager.register_agent(busy)
        async with busy.lock:
            with self.assertRaises(ValueError):
                await self.manager.retire_agent(busy.agent_id)

        archived = Agent("Archived", "Researcher", self.client)
        self.manager.register_agent(archived)
        archived_lib = self.manager.libraries[
            archived.private_doc_library_id
        ]
        tokens = self._activate(archived)
        try:
            await self.manager.write_private_file("memory.txt", "remember me")
        finally:
            self._deactivate(tokens)

        await self.manager.retire_agent(archived.agent_id, "archive")
        self.assertNotIn(archived.name, self.manager.agents)
        self.assertEqual(archived.lifecycle_state, "archived")
        with self.assertRaises(PermissionError):
            archived_lib.write_file("blocked.txt", "blocked")
        with self.assertRaises(PermissionError):
            archived_lib.write_file_atomic("blocked.txt", "blocked")
        with self.assertRaises(PermissionError):
            archived_lib.move_file("memory.txt", "moved.txt")
        with self.assertRaises(PermissionError):
            archived_lib.replace_all_files({"replacement.txt": "blocked"})
        await self.manager.reactivate_agent(archived.agent_id, "default")
        self.assertIs(self.manager.agents[archived.name], archived)
        self.assertIn("remember me", archived_lib.read_file("memory.txt"))

        retained = Agent("Retained", "Researcher", self.client)
        self.manager.register_agent(retained)
        await self.manager.retire_agent(retained.agent_id, "retain")
        self.assertEqual(retained.lifecycle_state, "retained")
        self.manager.libraries[retained.private_doc_library_id].write_file(
            "host-note.txt", "trusted host"
        )
        await self.manager.reactivate_agent(retained.agent_id, "default")

        doomed = Agent("Doomed", "Temporary", self.client)
        self.manager.register_agent(doomed)
        doomed_id = doomed.agent_id
        doomed_lib_id = doomed.private_doc_library_id
        doomed_root = self.manager.libraries[doomed_lib_id].root_dir
        with self.assertRaises(ValueError):
            await self.manager.retire_agent(doomed_id, "delete")
        await self.manager.retire_agent(
            doomed_id, "delete", confirm_delete=True
        )
        self.assertNotIn(doomed_id, self.manager._agents_by_id)
        self.assertNotIn(doomed_lib_id, self.manager.libraries)
        self.assertFalse(os.path.exists(doomed_root))

        unbound = Agent("Unbound", "Temporary", DummyClient())
        self.manager.register_agent(unbound)
        await self.manager.retire_agent(
            unbound.agent_id, "delete", confirm_delete=True
        )
        self.assertEqual(unbound.lifecycle_state, "deleted")

    async def test_lifecycle_operations_are_serialized_per_agent(self):
        agent = Agent("Lifecycle", "Researcher", self.client)
        self.manager.register_agent(agent)
        retire_results = await asyncio.gather(
            self.manager.retire_agent(agent.agent_id, "archive"),
            self.manager.retire_agent(agent.agent_id, "archive"),
            return_exceptions=True,
        )
        self.assertEqual(sum(result is None for result in retire_results), 1)
        self.assertEqual(
            sum(isinstance(result, ValueError) for result in retire_results),
            1,
        )

        reactivate_results = await asyncio.gather(
            self.manager.reactivate_agent(agent.agent_id, "default"),
            self.manager.reactivate_agent(agent.agent_id, "default"),
            return_exceptions=True,
        )
        self.assertEqual(sum(result is agent for result in reactivate_results), 1)
        self.assertEqual(
            sum(
                isinstance(result, ValueError)
                for result in reactivate_results
            ),
            1,
        )

    async def test_active_invocation_cannot_race_retirement(self):
        started = asyncio.Event()
        release = asyncio.Event()

        class BlockingClient:
            async def generate(self, prompt, **kwargs):
                started.set()
                await release.wait()
                return "Final Answer: complete"

        blocking_client = BlockingClient()
        self.manager.register_llm_client("blocking", blocking_client)
        worker = Agent("Blocking", "Worker", blocking_client)
        self.manager.register_agent(worker)
        team = self.manager.create_agent_team(self.root)
        state_path = os.path.join(self.temp_dir, "active-invocation.db")
        self.manager.db_path = state_path
        await self.manager.save_state()
        task = asyncio.create_task(
            team.execute_reasoning_step(
                worker,
                "Work.",
                "Complete the task.",
                manager=self.manager,
            )
        )
        await started.wait()
        with self.assertRaisesRegex(ValueError, "active model invocation"):
            await self.manager.retire_agent(worker.agent_id, "archive")
        with self.assertRaisesRegex(StateRestoreError, "invocation"):
            await self.manager.load_state(state_path)
        release.set()
        self.assertEqual(await task, "complete")
        await self.manager.retire_agent(worker.agent_id, "archive")

    async def test_delete_revalidates_membership_after_preflush(self):
        agent = Agent("DeleteRace", "Temporary", self.client)
        self.manager.register_agent(agent)
        started = asyncio.Event()
        release = asyncio.Event()
        original_flush = self.manager.flush_state

        async def delayed_flush():
            started.set()
            await release.wait()
            await original_flush()

        self.manager.flush_state = delayed_flush
        deletion = asyncio.create_task(
            self.manager.retire_agent(
                agent.agent_id, "delete", confirm_delete=True
            )
        )
        await started.wait()
        team = self.manager.create_agent_team(
            self.root,
            member_configs={
                "worker": agent,
                "peer-d1": Agent("PeerD1", "Peer", self.client),
                "peer-d2": Agent("PeerD2", "Peer", self.client),
            },
        )
        release.set()
        with self.assertRaisesRegex(ValueError, "still belongs"):
            await deletion
        self.assertIs(self.manager._agents_by_id[agent.agent_id], agent)
        self.assertIn(agent, team.members)
        self.assertIn(agent.private_doc_library_id, self.manager.libraries)

