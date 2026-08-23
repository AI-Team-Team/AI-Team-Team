import asyncio
import multiprocessing
import os
import shutil
import sqlite3
import tempfile
import threading
import time
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import AsyncMock, patch

from ai_team_team import (
    AmbiguousTeamContextError,
    ATTConfig,
    ATTException,
    ATTManager,
    Agent,
    AuditResult,
    AuditStatus,
    DatabaseOwnershipError,
    LLMGenerationError,
    StateRestoreError,
)
from ai_team_team.core.utils import generate_with_retry
from ai_team_team.database.persistence import (
    DatabaseStore,
    PersistenceCoordinator,
)
from ai_team_team.tool import get_default_tools


class EchoClient:
    async def generate(self, prompt, system_instruction=None, **kwargs):
        return "Final Answer: complete"


def _write_and_hold(db_path, workspace, ready, release):
    import warnings

    warnings.filterwarnings("ignore", category=ResourceWarning)

    async def run():
        client = EchoClient()
        manager = ATTManager(
            Agent("ProcessRoot", "Architect", client),
            ATTConfig(workspace_root=workspace),
            db_path=db_path,
        )
        manager.register_llm_client("process-model", client)
        team = manager.create_agent_team(manager.root_ai)
        await manager.save_state()
        ready.put(team.team_id)
        release.wait(10)

    asyncio.run(run())

class TestHighHardening(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="att_high_")
        self.client = EchoClient()

    async def asyncTearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    async def test_unknown_alert_dedupe_survives_restore(self):
        db_path = os.path.join(self.tmpdir, "unknown.db")
        manager = ATTManager(
            Agent("Root", "Architect", self.client),
            ATTConfig(
                workspace_root=self.tmpdir,
                audit_unknown_escalation_mode="queue",
            ),
            db_path=db_path,
        )
        manager.register_llm_client("stable", self.client)
        parent = manager.create_agent_team(manager.root_ai)
        child = manager.create_agent_team(parent)
        result = AuditResult(AuditStatus.UNKNOWN, "offline", "timeout")
        await manager.supervisor.report_unknown(child, result, manager)
        await manager.supervisor.report_unknown(child, result, manager)
        await manager.save_state()
        await manager.close()

        restored = ATTManager(
            Agent("Root", "Architect", self.client),
            ATTConfig(workspace_root=self.tmpdir),
        )
        restored.register_llm_client("stable", self.client)
        await restored.load_state(db_path)
        restored_parent = restored.teams[parent.team_id]
        self.assertEqual(len(restored_parent.message_inbox), 1)
        self.assertEqual(
            restored_parent.message_inbox[0]["occurrence_count"], 2
        )
        await restored.close()
    async def test_unknown_alert_lifecycle_and_manual_clear(self):
        manager = ATTManager(
            Agent("Root", "Architect", self.client),
            ATTConfig(
                workspace_root=self.tmpdir,
                audit_unknown_escalation_mode="queue",
                audit_unknown_soft_threshold=2,
            ),
        )
        parent = manager.create_agent_team(manager.root_ai)
        child = manager.create_agent_team(parent)
        result = AuditResult(
            AuditStatus.UNKNOWN, "Audit unavailable.", "TimeoutError"
        )
        await manager.supervisor.report_unknown(child, result, manager)
        await manager.supervisor.report_unknown(child, result, manager)
        self.assertEqual(len(parent.message_inbox), 1)
        alert = parent.message_inbox[0]
        self.assertEqual(alert["occurrence_count"], 2)
        self.assertEqual(alert["state"], "pending")

        parent.execute_reasoning_step = AsyncMock(return_value="handled")
        await manager.execute_team_discussion(
            parent, "normal discussion", rounds=1, skip_audit=True
        )
        self.assertEqual(parent.message_inbox, [])

        await manager.supervisor.report_unknown(child, result, manager)
        repeated = False

        async def receive_repeat(*args, **kwargs):
            nonlocal repeated
            if not repeated:
                repeated = True
                await manager.supervisor.report_unknown(child, result, manager)
            return "handled"

        parent.execute_reasoning_step = AsyncMock(side_effect=receive_repeat)
        await manager.execute_team_discussion(
            parent, "discussion with a repeated alert", rounds=1,
            skip_audit=True,
        )
        self.assertEqual(len(parent.message_inbox), 1)
        self.assertEqual(parent.message_inbox[0]["state"], "pending")
        self.assertEqual(parent.message_inbox[0]["occurrence_count"], 2)
        self.assertNotIn("processing_count", parent.message_inbox[0])
        self.assertTrue(
            manager.acknowledge_unknown_alert(
                parent.team_id,
                parent.message_inbox[0]["fingerprint"],
            )
        )

        await manager.supervisor.report_unknown(child, result, manager)
        fingerprint = parent.message_inbox[0]["fingerprint"]
        parent.execute_reasoning_step = AsyncMock(
            side_effect=ATTException("discussion failed")
        )
        with self.assertRaises(ATTException):
            await manager.execute_team_discussion(
                parent, "failing discussion", rounds=1, skip_audit=True
            )
        self.assertEqual(parent.message_inbox[0]["state"], "pending")
        self.assertTrue(manager.acknowledge_unknown_alert(parent.team_id, fingerprint))

        await manager.supervisor.report_unknown(child, result, manager)
        fingerprint = parent.message_inbox[0]["fingerprint"]
        reasoning_started = asyncio.Event()

        async def cancelled_reasoning(*args, **kwargs):
            reasoning_started.set()
            await asyncio.Event().wait()

        parent.execute_reasoning_step = AsyncMock(
            side_effect=cancelled_reasoning
        )
        cancelled_discussion = asyncio.create_task(
            manager.execute_team_discussion(
                parent, "cancelled discussion", rounds=1, skip_audit=True
            )
        )
        await reasoning_started.wait()
        cancelled_discussion.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await cancelled_discussion
        self.assertEqual(parent.message_inbox[0]["state"], "pending")
        self.assertNotIn("processing_count", parent.message_inbox[0])
        self.assertTrue(
            manager.acknowledge_unknown_alert(parent.team_id, fingerprint)
        )

        for index in range(3):
            parent.receive_message(
                {
                    "type": "audit_unknown_escalation",
                    "from": "Supervisor",
                    "failed_team_id": child.team_id,
                    "reason": f"unique-{index}",
                    "cause": "outage",
                }
            )
        self.assertEqual(len(parent.message_inbox), 3)
        self.assertEqual(manager.clear_unknown_alerts(parent.team_id), 3)
        await manager.close()
