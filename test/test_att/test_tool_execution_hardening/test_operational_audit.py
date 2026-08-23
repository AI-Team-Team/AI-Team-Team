import asyncio
import concurrent.futures
import os
import shutil
import tempfile
import unittest
from enum import Enum
from typing import Annotated, Literal, NotRequired, TypedDict
from unittest.mock import patch

from pydantic import BaseModel, ConfigDict

from ai_team_team import (
    Agent,
    AgentTurnStatus,
    ATTException,
    ATTConfig,
    ATTManager,
    DiscussionStatus,
    OperationalStatus,
    RetryableToolError,
    StatePersistenceError,
    Tool,
    ToolArgumentError,
    ToolResultStatus,
)
from ai_team_team.core.response import AuditStatus, LLMResponse
from ai_team_team.core.adapters import HandlerClientAdapter
from ai_team_team.core.text_action import parse_text_action, parse_tool_arguments
from ai_team_team.core.tool_runtime import ToolExecutor


class NestedMode(str, Enum):
    FAST = "fast"
    SAFE = "safe"


class NestedInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    mode: NestedMode
    labels: list[str]


class TypedOptions(TypedDict):
    threshold: int
    tags: list[str]


class OptionalTypedOptions(TypedDict):
    threshold: int
    note: NotRequired[str]

class TestOperationalAuditModes(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="att-operational-")

        class Client:
            def __init__(self):
                self.consensus = {}

            def supports_native_tool_calling(self):
                return False

            async def generate(self, require_json=False, **kwargs):
                if require_json:
                    import json

                    return json.dumps(self.consensus)
                return "Final Answer: audit member complete"

        self.client = Client()
        self.manager = ATTManager(
            Agent("Root", "Architect", self.client),
            ATTConfig(workspace_root=self.tmpdir),
        )
        self.team = self.manager.create_agent_team(self.manager.root_ai)

    async def asyncTearDown(self):
        await self.manager.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    async def test_framework_and_supervisor_operational_modes(self):
        self.manager.config.operational_status_decision_mode = "framework"
        self.client.consensus = {"is_healthy": False, "reason": "content issue"}
        framework = await self.manager.supervisor.audit_team_dialog(
            self.team,
            "transcript",
            operational_status=OperationalStatus.DEGRADED,
            operational_reason="one turn failed",
        )
        self.assertIs(framework.status, AuditStatus.UNHEALTHY)
        self.assertIs(framework.operational_status, OperationalStatus.DEGRADED)

        self.manager.config.operational_status_decision_mode = "supervisor"
        self.client.consensus = {
            "is_healthy": True,
            "reason": "content healthy",
            "operational_status": "healthy",
            "operational_reason": "runtime healthy",
        }
        supervisor = await self.manager.supervisor.audit_team_dialog(
            self.team,
            "transcript",
            operational_status=OperationalStatus.DEGRADED,
            operational_reason="framework degraded",
        )
        self.assertIs(supervisor.operational_status, OperationalStatus.HEALTHY)
    async def test_hybrid_retains_framework_operational_result_on_audit_failure(self):
        self.manager.config.operational_status_decision_mode = "framework_then_supervisor"
        self.client.consensus = {"invalid": True}
        result = await self.manager.supervisor.audit_team_dialog(
            self.team,
            "transcript",
            operational_status=OperationalStatus.DEGRADED,
            operational_reason="framework degraded",
        )
        self.assertIs(result.status, AuditStatus.UNKNOWN)
        self.assertIs(result.operational_status, OperationalStatus.DEGRADED)
        self.assertEqual(result.operational_reason, "framework degraded")
    async def test_operational_queue_deduplicates_by_stable_fingerprint(self):
        parent = self.team
        child = self.manager.create_agent_team(parent)
        self.manager.config.operational_degraded_escalation_mode = "queue"
        from ai_team_team import AuditResult

        result = AuditResult(
            status=AuditStatus.HEALTHY,
            reason="content healthy",
            operational_status=OperationalStatus.DEGRADED,
            operational_reason="tool unavailable",
        )
        await self.manager._report_operational_degraded(child, result)
        await self.manager._report_operational_degraded(child, result)
        alerts = [
            item
            for item in parent.message_inbox
            if item.get("type") == "operational_degraded_escalation"
        ]
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["occurrence_count"], 2)
        self.assertEqual(alerts[0]["state"], "pending")

        fingerprint = alerts[0]["fingerprint"]
        alerts[0]["state"] = "processing"
        alerts[0]["processing_count"] = 2
        self.manager._finish_durable_alert_processing(
            parent,
            "operational_degraded_escalation",
            {fingerprint},
            False,
        )
        self.assertEqual(alerts[0]["state"], "pending")
        self.manager._finish_durable_alert_processing(
            parent,
            "operational_degraded_escalation",
            {fingerprint},
            True,
        )
        self.assertFalse(
            any(
                item.get("fingerprint") == fingerprint
                for item in parent.message_inbox
            )
        )
    async def test_operational_wake_deduplicates_active_alert(self):
        parent = self.team
        child = self.manager.create_agent_team(parent)
        self.manager.config.operational_degraded_escalation_mode = "wake"
        started = asyncio.Event()
        release = asyncio.Event()
        calls = 0

        async def emergency(*args, **kwargs):
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()
            return "handled"

        self.manager.execute_emergency_discussion = emergency
        from ai_team_team import AuditResult

        result = AuditResult(
            status=AuditStatus.HEALTHY,
            reason="content healthy",
            operational_status=OperationalStatus.DEGRADED,
            operational_reason="same outage",
        )
        await self.manager._report_operational_degraded(child, result)
        await started.wait()
        await self.manager._report_operational_degraded(child, result)
        await asyncio.sleep(0)
        self.assertEqual(calls, 1)
        release.set()
        await asyncio.gather(*tuple(self.manager._emergency_tasks))


if __name__ == "__main__":
    unittest.main()

