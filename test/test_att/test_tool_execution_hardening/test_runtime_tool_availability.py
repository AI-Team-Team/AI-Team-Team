from test.personal_activity import interact_and_idle
from test.test_att.test_institutional_runtime.test_tool_entry_points import proposal
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
    InteractionStatus,
    ATTException,
    ATTConfig,
    ATTManager,
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
            persistence_mode="volatile",
        )
        self.team = self.manager.create_agent_team(self.manager.root_ai, parent=self.manager.root_ai)
        self.agent = self.team.members[0]

    async def asyncTearDown(self):
        await self.manager.close()

    async def test_runtime_tool_view_tracks_config_and_depth(self):
        self.manager.config.enable_dynamic_delegation = False
        self.assertNotIn("dispatch_subagent", self.manager.get_available_tools(self.team, self.agent))
        self.assertNotIn(
            "propose_team_formation",
            self.manager.get_available_tools(self.team, self.agent),
        )
        self.manager.config.enable_dynamic_delegation = True
        self.assertIn("dispatch_subagent", self.manager.get_available_tools(self.team, self.agent))
        self.assertIn(
            "propose_team_formation",
            self.manager.get_available_tools(self.team, self.agent),
        )
        self.manager.config.max_delegation_depth = self.team.depth
        self.assertNotIn("dispatch_subagent", self.manager.get_available_tools(self.team, self.agent))
        self.assertIn(
            "propose_team_formation",
            self.manager.get_available_tools(self.team, self.agent),
        )
        self.assertNotIn("delegate_escalation", self.manager.get_available_tools(self.team, self.agent))
        self.manager.config.enable_membership_voting = True
        self.assertIn("cast_vote", self.manager.get_available_tools(self.team, self.agent))

    async def test_raw_initial_draft_tool_cannot_bypass_disabled_delegation(self):
        executor = ToolExecutor(self.team, self.agent, self.manager)
        self.manager.config.enable_dynamic_delegation = False

        async with self.manager.agent_invocation(self.agent):
            result = await executor.execute(
                "propose_team_formation",
                kwargs={"proposal": proposal()},
                tools=dict(self.team.tools),
            )

        self.assertIs(result.status, ToolResultStatus.DENIED)
        self.assertFalse(self.manager._formations.drafts)

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
    async def test_direct_client_probe_failure_uses_the_common_text_runtime(self):
        class BrokenProbe:
            def supports_native_tool_calling(self):
                raise RuntimeError("probe failed")

            async def generate(self, **kwargs):
                return "Action: set_activity_intent(intent={'kind': 'idle'})"

        client = BrokenProbe()
        self.agent.llm_client = client
        self.manager.register_llm_client("broken-probe", client)
        self.manager.config.tool_calling_mode = "auto"
        result = await interact_and_idle(self.manager, self.agent, "Work.", team=self.team)
        self.assertIs(result.status, InteractionStatus.COMPLETED)
        self.assertFalse(hasattr(self.team, "execute_reasoning_step_detailed"))

    async def test_native_handler_receives_tool_objects(self):
        captured = None

        async def handler(tools=None, **kwargs):
            nonlocal captured
            captured = tools
            from test.test_att.test_agent_activity._support import idle
            return idle()

        self.manager.register_generator_handler(handler)
        self.manager.config.tool_calling_mode = "native"
        self.agent.llm_client = HandlerClientAdapter("default", handler)
        await interact_and_idle(self.manager, self.agent, "Work.", team=self.team)
        self.assertTrue(captured)
        self.assertTrue(all(isinstance(tool, Tool) for tool in captured))
