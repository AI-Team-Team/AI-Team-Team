"""Shared fixtures for critical hardening tests."""

import asyncio
from contextlib import closing
import os
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from ai_team_team import ATTConfig, ATTManager, Agent, StateRestoreError
from ai_team_team.core.adapters import HandlerClientAdapter
from ai_team_team.core.exceptions import TokenLimitExceededError
from ai_team_team.core.policies import parse_governance_decision
from ai_team_team.core.response import LLMResponse
from ai_team_team.core.utils import generate_with_retry
from ai_team_team.tool import get_default_tools


class SimpleClient:
    """Minimal client used by critical hardening tests."""

    async def generate(
        self,
        prompt,
        system_instruction=None,
        temperature=0.3,
        require_json=False,
        **kwargs,
    ):
        return "Final Answer: complete"


class CriticalHardeningTestCase(unittest.IsolatedAsyncioTestCase):
    """Creates one isolated manager for critical hardening tests."""

    async def asyncSetUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="att_critical_")
        self.client = SimpleClient()
        self.root = Agent("Root", "Architect", self.client)
        self.manager = ATTManager(
            self.root,
            ATTConfig(
                workspace_root=self.tmpdir,
                migration_policy="permissive",
            ),
        )
        self.manager.register_llm_client("test", self.client)

    async def asyncTearDown(self) -> None:
        await self.manager.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

