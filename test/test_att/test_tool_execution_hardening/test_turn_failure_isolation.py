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

class TestToolExecutionHardening(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="att-tool-hardening-")
        self.addCleanup(shutil.rmtree, self.tmpdir, ignore_errors=True)

        class Client:
            def supports_native_tool_calling(self):
                return False

            async def generate(self, require_json=False, **kwargs):
                if require_json:
                    return '{"is_healthy": true, "reason": "healthy"}'
                return "Final Answer: done"

        self.client = Client()
        self.manager = ATTManager(
            Agent("Root", "Architect", self.client),
            ATTConfig(workspace_root=self.tmpdir, tool_calling_mode="react"),
        )
        self.team = self.manager.create_agent_team(self.manager.root_ai)
        self.agent = self.team.members[0]

    async def asyncTearDown(self):
        await self.manager.close()

    async def test_member_recovers_on_next_round(self):
        self.manager.config.max_tool_argument_retries = 0

        class SequenceClient:
            def __init__(self, responses):
                self.responses = list(responses)

            def supports_native_tool_calling(self):
                return False

            async def generate(self, **kwargs):
                return self.responses.pop(0)

        self.team.members[0].llm_client = SequenceClient(
            ["Action: missing(", "Final Answer: recovered"]
        )
        for member in self.team.members[1:]:
            member.llm_client = SequenceClient(
                ["Final Answer: round one", "Final Answer: round two"]
            )
        result = await self.manager.execute_team_discussion_detailed(
            self.team, "work", rounds=2, skip_audit=True
        )
        self.assertIs(result.status, DiscussionStatus.PARTIAL)
        self.assertIs(result.rounds[0].turns[0].status, AgentTurnStatus.INCOMPLETE)
        self.assertTrue(
            all(
                turn.status is AgentTurnStatus.COMPLETED
                for turn in result.rounds[0].turns[1:]
            )
        )
        self.assertIs(result.rounds[1].turns[0].status, AgentTurnStatus.COMPLETED)
        self.assertIn("[Turn incomplete:", result.transcript)
        self.assertIn("recovered", result.transcript)
    async def test_llm_abort_policy_still_aborts_the_discussion(self):
        from ai_team_team import AgentTurnIncompleteError

        class DeadClient:
            def supports_native_tool_calling(self):
                return False

            async def generate(self, **kwargs):
                raise RuntimeError("permanent")

        self.manager.config.turn_failure_policy.llm = "abort"
        self.team.members[0].llm_client = DeadClient()
        with self.assertRaises(AgentTurnIncompleteError):
            await self.manager.execute_team_discussion_detailed(
                self.team, "work", rounds=1, skip_audit=True
            )
    async def test_abort_policy_still_emits_operational_degradation(self):
        from ai_team_team import AgentTurnIncompleteError

        class DeadClient:
            def supports_native_tool_calling(self):
                return False

            async def generate(self, **kwargs):
                raise RuntimeError("sensitive provider detail")

        events = []
        self.manager.on_system_event = lambda event, payload: events.append(
            (event, payload)
        )
        self.manager.config.turn_failure_policy.llm = "abort"
        self.team.members[0].llm_client = DeadClient()
        with self.assertLogs("ATT.CoreUtils", level="ERROR") as logs:
            with self.assertRaises(AgentTurnIncompleteError) as caught:
                await self.manager.execute_team_discussion_detailed(
                    self.team, "work", rounds=1, skip_audit=True
                )
        await self.manager.flush_callbacks()
        degraded = [item for item in events if item[0] == "operational_degraded"]
        self.assertEqual(len(degraded), 1)
        self.assertNotIn("sensitive provider detail", repr(degraded))
        self.assertNotIn("sensitive provider detail", str(caught.exception))
        self.assertNotIn("sensitive provider detail", "\n".join(logs.output))
    async def test_failed_observation_callback_contains_only_metadata(self):
        events = []
        self.manager.on_activity_added = lambda *args: events.append(args)

        class ActionClient:
            def supports_native_tool_calling(self):
                return False

            async def generate(self, **kwargs):
                return 'Action: secret_tool(value="secret-value")'

        async def secret_tool(value: str):
            raise RuntimeError(f"failed with {value}")

        self.agent.llm_client = ActionClient()
        self.team.tools["secret_tool"] = Tool(
            "secret_tool", "Secret", secret_tool
        )
        result = await self.team.execute_reasoning_step_detailed(
            self.agent, "work", "system", manager=self.manager
        )
        self.assertIs(result.status, AgentTurnStatus.INCOMPLETE)
        await self.manager.flush_callbacks()
        self.assertNotIn("secret-value", repr(events))
        self.assertNotIn("failed with", repr(events))

