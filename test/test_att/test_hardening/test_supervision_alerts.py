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

    async def test_unknown_wake_queue_and_deduplication(self):
        parent = self.manager.create_agent_team(self.root)
        child = self.manager.create_agent_team(parent)
        self.manager.execute_emergency_discussion = AsyncMock(
            return_value="handled"
        )
        result = AuditResult(
            AuditStatus.UNKNOWN,
            "Audit unavailable.",
            "TimeoutError: timeout",
        )

        await asyncio.gather(
            self.manager.supervisor.report_unknown(
                child, result, self.manager
            ),
            self.manager.supervisor.report_unknown(
                child, result, self.manager
            ),
        )
        await asyncio.sleep(0)
        self.manager.execute_emergency_discussion.assert_awaited_once()
        self.assertTrue(
            self.manager.execute_emergency_discussion.await_args.kwargs[
                "skip_audit"
            ]
        )

        self.manager.execute_emergency_discussion.reset_mock()
        self.manager.config.audit_unknown_escalation_mode = "queue"
        await self.manager.supervisor.report_unknown(
            child, result, self.manager
        )
        await asyncio.sleep(0)
        self.manager.execute_emergency_discussion.assert_not_awaited()
        self.assertTrue(
            any(
                message.get("type") == "audit_unknown_escalation"
                for message in parent.message_inbox
            )
        )
    async def test_unhealthy_keeps_emergency_escalation(self):
        parent = self.manager.create_agent_team(self.root)
        child = self.manager.create_agent_team(parent)
        self.manager.execute_emergency_discussion = AsyncMock(
            return_value="handled"
        )

        await self.manager.supervisor.report_anomaly(
            child, "Confirmed deadlock.", self.manager
        )
        await asyncio.sleep(0)

        self.manager.execute_emergency_discussion.assert_awaited_once()
        alert = (
            self.manager.execute_emergency_discussion
            .await_args.args[1]
        )
        self.assertEqual(alert["type"], "child_failure_escalation")
        self.assertFalse(
            self.manager.execute_emergency_discussion.await_args.kwargs[
                "skip_audit"
            ]
        )
