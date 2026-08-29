import asyncio
import concurrent.futures
import os
import shutil
import tempfile
import unittest
from enum import Enum
from typing import Annotated, Literal
from unittest.mock import patch

from pydantic import BaseModel, ConfigDict
from typing_extensions import NotRequired, TypedDict

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

    async def test_runtime_tool_view_tracks_config_and_depth(self):
        self.manager.config.enable_dynamic_delegation = False
        self.assertNotIn("dispatch_subagent", self.manager.get_available_tools(self.team, self.agent))
        self.manager.config.enable_dynamic_delegation = True
        self.assertIn("dispatch_subagent", self.manager.get_available_tools(self.team, self.agent))
        self.manager.config.max_delegation_depth = self.team.depth
        self.assertNotIn("dispatch_subagent", self.manager.get_available_tools(self.team, self.agent))
        self.assertNotIn("delegate_escalation", self.manager.get_available_tools(self.team, self.agent))
        self.manager.config.enable_membership_voting = True
        self.assertIn("cast_vote", self.manager.get_available_tools(self.team, self.agent))
    async def test_capability_probe_failure_falls_back_and_emits_event(self):
        class BrokenProbe:
            def supports_native_tool_calling(self):
                raise RuntimeError("probe failed")

        events = []
        self.manager.on_system_event = lambda event, payload: events.append((event, payload))
        self.assertFalse(
            self.manager.probe_native_tool_capability(
                BrokenProbe(), agent=self.agent, team=self.team
            )
        )
        await self.manager.flush_callbacks()
        self.assertEqual(events[0][0], "tool_capability_probe_failed")
        self.assertNotIn("probe failed", repr(events[0][1]))
    async def test_direct_client_probe_failure_without_manager_falls_back(self):
        from ai_team_team import AgentTeam

        class BrokenProbe:
            def supports_native_tool_calling(self):
                raise RuntimeError("probe failed")

            async def generate(self, **kwargs):
                return "Final Answer: text fallback"

        agent = Agent("Standalone", "Tester", BrokenProbe())
        team = AgentTeam(agent, preset_name="standalone")
        team.members = [agent]
        result = await team.execute_reasoning_step_detailed(
            agent, "work", "system", manager=None
        )
        self.assertIs(result.status, AgentTurnStatus.COMPLETED)
        self.assertEqual(result.answer, "text fallback")
    async def test_native_handler_receives_tool_objects(self):
        captured = None

        async def handler(tools=None, **kwargs):
            nonlocal captured
            captured = tools
            return LLMResponse(text="done")

        self.manager.register_generator_handler(handler)
        self.manager.config.tool_calling_mode = "native"
        self.agent.llm_client = HandlerClientAdapter("default", handler)
        await self.team.execute_reasoning_step_detailed(
            self.agent, "work", "system", manager=self.manager
        )
        self.assertTrue(captured)
        self.assertTrue(all(isinstance(tool, Tool) for tool in captured))
