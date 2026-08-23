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

    async def test_react_private_payload_is_not_durable_or_callback_visible(self):
        secret = "PRIVATE-CALLBACK-SENTINEL"
        client = SequenceClient(
            [
                "Thought: save a deliberate note\n"
                f"Action: write_private_file(path='note.txt', content='{secret}')",
                "Final Answer: note saved",
            ]
        )
        writer = Agent("ReActWriter", "Writer", client)
        team = self.manager.create_agent_team(
            self.root,
            member_configs={
                "writer": writer,
                "peer-c": Agent("PeerC", "Peer", self.client),
                "peer-d": Agent("PeerD", "Peer", self.client),
            },
        )
        callbacks = []
        self.manager.on_activity_added = lambda *args: callbacks.append(args)
        self.manager.on_log_append = lambda *args: callbacks.append(args)
        result = await team.execute_reasoning_step(
            writer,
            "Save the note.",
            "Use the private workspace.",
            max_steps=2,
            manager=self.manager,
        )
        await self.manager.flush_callbacks()
        self.assertEqual(result, "note saved")
        self.assertNotIn(secret, repr(callbacks))
        self.assertNotIn(secret, repr(writer.message_history))
        private = self.manager.libraries[writer.private_doc_library_id]
        self.assertEqual(private.read_text("note.txt"), secret)

    async def test_private_read_can_inform_result_without_persisting_body(self):
        secret = "PRIVATE-READ-SENTINEL"
        client = SequenceClient(
            [
                "Thought: consult my note\n"
                "Action: read_private_file(path='note.txt')",
                f"Final Answer: {secret}",
            ]
        )
        reader = Agent("ReActReader", "Reader", client)
        team = self.manager.create_agent_team(
            self.root,
            member_configs={
                "reader": reader,
                "peer-r1": Agent("PeerR1", "Peer", self.client),
                "peer-r2": Agent("PeerR2", "Peer", self.client),
            },
        )
        self.manager.libraries[reader.private_doc_library_id].write_file(
            "note.txt", secret
        )
        callbacks = []
        self.manager.on_activity_added = lambda *args: callbacks.append(args)
        self.manager.on_log_append = lambda *args: callbacks.append(args)

        result = await team.execute_reasoning_step(
            reader,
            "Consult your private note.",
            "Use the private workspace only when needed.",
            max_steps=2,
            manager=self.manager,
        )
        await self.manager.flush_callbacks()

        self.assertEqual(result, secret)
        self.assertIn(secret, client.prompt_snapshots[1])
        self.assertNotIn(secret, repr(callbacks))
        self.assertNotIn(secret, repr(reader.message_history))
        self.assertNotIn(secret, repr(reader.messages))

