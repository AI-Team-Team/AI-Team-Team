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

    async def test_schema_five_round_trip_and_corruption_is_atomic(self):
        db_path = os.path.join(self.temp_dir, "state.db")
        self.manager.db_path = db_path
        active = Agent("Active", "Researcher", self.client)
        inactive = Agent("Inactive", "Researcher", self.client)
        self.manager.register_agent(active)
        self.manager.register_agent(inactive)
        tokens = self._activate(active)
        try:
            await self.manager.write_private_file("active.txt", "active-data")
        finally:
            self._deactivate(tokens)
        await self.manager.retire_agent(inactive.agent_id, "archive")
        await self.manager.save_state()
        await self.manager.close()

        restored_root = Agent("Replacement", "Architect", self.client)
        restored = ATTManager(
            restored_root,
            ATTConfig(workspace_root=self.temp_dir),
        )
        restored.register_llm_client("default", self.client)
        await restored.load_state(db_path)
        try:
            self.assertEqual(restored.root_ai.agent_id, self.root.agent_id)
            self.assertEqual(
                restored._agents_by_id[inactive.agent_id].lifecycle_state,
                "archived",
            )
            private = restored.libraries[f"PDL-{active.agent_id}"]
            self.assertIn("active-data", private.read_file("active.txt"))
            self.assertEqual(
                sum(lib.library_kind == "agent_private" for lib in restored.libraries.values()),
                len(restored._agents_by_id),
            )
            corrupt_path = os.path.join(self.temp_dir, "corrupt.db")
            shutil.copy2(db_path, corrupt_path)
            connection = sqlite3.connect(corrupt_path)
            try:
                connection.execute(
                    "UPDATE libraries SET is_public_visible = 1 WHERE lib_id = ?",
                    (f"PDL-{active.agent_id}",),
                )
                connection.commit()
            finally:
                connection.close()
            original_root_id = restored.root_ai.agent_id
            original_private_content = restored.libraries[
                f"PDL-{active.agent_id}"
            ].read_file("active.txt")
            with self.assertRaises(StateRestoreError):
                await restored.load_state(corrupt_path)
            self.assertEqual(restored.root_ai.agent_id, original_root_id)
            self.assertEqual(
                restored.libraries[f"PDL-{active.agent_id}"].read_file(
                    "active.txt"
                ),
                original_private_content,
            )
        finally:
            await restored.close()


if __name__ == "__main__":
    unittest.main()

