import asyncio
from contextlib import closing
import os
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from ai_team_team import (
    ATTConfig,
    ATTManager,
    Agent,
    AuditResult,
    AuditStatus,
    StateRestoreError,
)
from ai_team_team.database.persistence import DatabaseStore
from ai_team_team.tool import get_default_tools

class TestATTHardening(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="att_hardening_")
        self.client = MagicMock()
        self.client.generate = AsyncMock(return_value="Final Answer: Done")
        self.root = Agent("Root", "Architect", llm_client=self.client)
        self.manager = ATTManager(
            self.root,
            ATTConfig(
                max_delegation_depth=6,
                migration_policy="permissive",
                enable_membership_voting=True,
                workspace_root=self.tmpdir,
            ),
        )

    async def asyncTearDown(self):
        await self.manager.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_config_rejects_unknown_policies(self):
        cases = {
            "migration_policy": "silent",
            "failover_policy": "random",
            "tool_calling_mode": "maybe",
            "audit_unknown_escalation_mode": "ignore",
            "agent_private_data_policy": "expose",
        }
        for name, value in cases.items():
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    ATTConfig(**{name: value})
        with self.assertRaises(ValueError):
            ATTConfig(communication={"policy": "open"})
        for invalid in (False, 0, ""):
            with self.subTest(communication=invalid):
                with self.assertRaises(ValueError):
                    ATTConfig(communication=invalid)
        with self.assertRaises(ValueError):
            ATTConfig(
                communication={
                    "policy": "parent_approval",
                    "request_delivery": "queue",
                    "direction": "bidirectional",
                    "unexpected": True,
                }
            )
        config = ATTConfig(
            communication={"policy": "parent_approval"}
        )
        with self.assertRaises(ValueError):
            config.communication.direction = "both"
    def test_builtin_tools_have_manager_context_immediately(self):
        team = self.manager.create_agent_team(self.root)
        self.assertIs(
            self.manager.tools_context["att_manager"], self.manager
        )
        self.assertIn("dispatch_subagent", team.tools)
        self.manager.register_tools_context(
            {"att_manager": object(), "service": "value"}
        )
        self.assertIs(
            self.manager.tools_context["att_manager"], self.manager
        )
