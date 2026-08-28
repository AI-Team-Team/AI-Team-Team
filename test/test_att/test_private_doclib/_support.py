"""Shared clients and fixtures for Private Agent DocLib tests."""

import asyncio
import os
import shutil
import sqlite3
import tempfile
import unittest

from ai_team_team import Agent, ATTConfig, ATTManager
from ai_team_team.core import StateRestoreError


class DummyClient:
    """Minimal client for Private Agent DocLib tests."""

    async def generate(self, prompt, **kwargs):
        return "ok"


class SequenceClient:
    """Returns deterministic responses and captures prompt snapshots."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.prompt_snapshots = []

    async def generate(self, prompt, **kwargs):
        self.prompt_snapshots.append(repr(prompt))
        return self.responses.pop(0)


class PrivateAgentDocLibTestCase(unittest.IsolatedAsyncioTestCase):
    """Creates one isolated manager and private library workspace."""

    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="att-private-")
        self.client = DummyClient()
        self.root = Agent("Root", "Architect", self.client)
        self.manager = ATTManager(
            self.root,
            ATTConfig(workspace_root=self.temp_dir),
        )
        self.manager.register_llm_client("default", self.client)

    async def asyncTearDown(self) -> None:
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
