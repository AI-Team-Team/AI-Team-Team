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

    async def test_registration_private_boundary_and_shared_identity(self):
        shared = Agent("Shared", "Researcher", self.client)
        self.manager.register_agent(shared)
        private_id = self.manager.get_private_library_id(shared.agent_id)
        self.assertEqual(private_id, f"PDL-{shared.agent_id}")
        self.assertEqual(shared.private_doc_library_id, private_id)
        private = self.manager.libraries[private_id]
        self.assertEqual(private.library_kind, "agent_private")
        self.assertFalse(private.is_public_visible)

        first = self.manager.create_agent_team(
            self.root,
            member_configs={
                "shared": shared,
                "one": Agent("One", "One", self.client),
                "two": Agent("Two", "Two", self.client),
            },
        )
        second = self.manager.create_agent_team(
            self.root,
            member_configs={
                "shared": shared,
                "three": Agent("Three", "Three", self.client),
                "four": Agent("Four", "Four", self.client),
            },
        )
        self.assertIn(shared, first.members)
        self.assertIn(shared, second.members)
        self.assertEqual(
            sum(
                library.owner_agent_id == shared.agent_id
                for library in self.manager.libraries.values()
            ),
            1,
        )

        with self.assertRaises(PermissionError):
            await self.manager.read_private_file("notes.txt")
        self.assertFalse(
            self.manager.check_library_access(
                first.team_id, private_id, "/", "READ"
            )
        )

        tokens = self._activate(shared, first)
        try:
            await self.manager.write_private_file("notes.txt", "private secret")
            self.assertIn(
                "private secret",
                await self.manager.read_private_file("notes.txt"),
            )
            await self.manager.publish_private_file(
                "notes.txt", "published.txt"
            )
            self.assertIn(
                "Permission denied",
                await first.tools["read_library_file"](
                    private_id, "notes.txt"
                ),
            )
            self.assertIn(
                "Permission denied",
                await first.tools["update_library_metadata"](
                    private_id, is_public=True
                ),
            )
            self.assertIn(
                "Permission denied",
                await first.tools["grant_library_permission"](
                    private_id, "/", second.team_id, "READ"
                ),
            )
            self.assertIn(
                "Private DocLibs cannot participate",
                await first.tools["create_library_link"](
                    first.doc_library.lib_id,
                    "private-link.txt",
                    private_id,
                    "notes.txt",
                ),
            )
            self.assertNotIn(
                private_id,
                await first.tools["list_public_libraries"](),
            )
        finally:
            self._deactivate(tokens)
        self.assertTrue(first.doc_library.is_file("published.txt"))
        self.assertFalse(second.doc_library.path_exists("published.txt"))

        tokens = self._activate(shared, second)
        try:
            self.assertIn(
                "private secret",
                await self.manager.read_private_file("notes.txt"),
            )
        finally:
            self._deactivate(tokens)

    async def test_publish_collision_move_and_private_events_hide_content(self):
        agent = Agent("Publisher", "Writer", self.client)
        team = self.manager.create_agent_team(
            self.root,
            member_configs={
                "publisher": agent,
                "peer-a": Agent("PeerA", "Peer", self.client),
                "peer-b": Agent("PeerB", "Peer", self.client),
            },
        )
        events = []
        self.manager.on_system_event = lambda kind, payload: events.append(
            (kind, payload)
        )
        tokens = self._activate(agent, team)
        try:
            await self.manager.write_private_file("draft.txt", "TOP SECRET BODY")
            await self.manager.move_private_file("draft.txt", "final.txt")
            team.doc_library.write_file("result.txt", "existing")
            with self.assertRaises(FileExistsError):
                await self.manager.publish_private_file(
                    "final.txt", "result.txt"
                )
            await self.manager.publish_private_file(
                "final.txt", "result.txt", overwrite=True
            )
            await self.manager.move_library_file(
                team.team_id,
                team.doc_library.lib_id,
                "result.txt",
                "renamed.txt",
            )
        finally:
            self._deactivate(tokens)
        await self.manager.flush_callbacks()
        self.assertFalse(team.doc_library.path_exists("result.txt"))
        self.assertIn("TOP SECRET BODY", team.doc_library.read_file("renamed.txt"))
        self.assertTrue(events)
        self.assertNotIn("TOP SECRET BODY", repr(events))
        self.assertNotIn("TOP SECRET BODY", repr(agent.message_history))

