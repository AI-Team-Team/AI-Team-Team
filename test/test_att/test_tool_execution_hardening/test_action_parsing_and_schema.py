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

    def test_balanced_text_action_parser_handles_complex_literals(self):
        samples = [
            'Action: tool(text="a ) value", data={"x": [1, {"y": "z"}]})',
            "Action: tool(text='escaped \\' quote', value='含有括号（测试）')",
            'Action: tool(text="""line one\nline two (still text)""")',
            '```python\nAction: tool(text="fenced (value)")\n```',
            'Action: ```python\ntool(text="inner fence", data={"code": "```x```"})\n```',
            'Action: tool(text="Action: remains inside the literal")',
        ]
        for sample in samples:
            with self.subTest(sample=sample):
                action = parse_text_action(sample)
                self.assertEqual(action.name, "tool")
                args, kwargs = parse_tool_arguments(action.arguments)
                self.assertFalse(args)
                self.assertIn("text", kwargs)
    def test_text_action_parser_rejects_ambiguous_or_unsafe_calls(self):
        invalid = [
            "Action: tool(value=(1, 2)",
            "Action: one()\nAction: two()",
            "Action: tool(value=name)",
            "Action: tool(value=1, value=2)",
            "Action: tool(**{'value': 1})",
            "Action: tool(*[1, 2])",
        ]
        for sample in invalid:
            with self.subTest(sample=sample), self.assertRaises(ToolArgumentError):
                action = parse_text_action(sample)
                parse_tool_arguments(action.arguments)
    async def test_strict_schema_validation_prevents_execution(self):
        calls = 0

        def complex_tool(
            mapping: dict[str, str],
            nested: NestedInput,
            options: TypedOptions,
            choice: Literal["a", "b"],
            count: Annotated[int, "strict count"] = 1,
        ):
            nonlocal calls
            calls += 1
            return "ok"

        tool = Tool("complex", "Complex input", complex_tool)
        mapping_schema = tool.json_schema["properties"]["mapping"]
        self.assertEqual(mapping_schema["additionalProperties"], {"type": "string"})
        self.assertFalse(tool.json_schema["additionalProperties"])
        executor = ToolExecutor(self.team, self.agent, self.manager)
        result = await executor.execute(
            "complex",
            kwargs={
                "mapping": {"x": 1},
                "nested": {"mode": "fast", "labels": ["a"]},
                "options": {"threshold": 1, "tags": ["x"]},
                "choice": "a",
            },
            tools={"complex": tool},
        )
        self.assertIs(result.status, ToolResultStatus.INVALID_ARGUMENTS)
        self.assertEqual(calls, 0)

        valid = await executor.execute(
            "complex",
            kwargs={
                "mapping": {"x": "one"},
                "nested": {"mode": "fast", "labels": ["a"]},
                "options": {"threshold": 1, "tags": ["x"]},
                "choice": "a",
            },
            tools={"complex": tool},
        )
        self.assertIs(valid.status, ToolResultStatus.SUCCESS)
        self.assertEqual(calls, 1)
    async def test_non_json_serializable_arguments_fail_before_execution(self):
        calls = 0

        def inspect_mapping(mapping: dict[str, str]):
            nonlocal calls
            calls += 1
            return "ok"

        circular = {}
        circular["self"] = circular
        result = await ToolExecutor(self.team, self.agent, self.manager).execute(
            "inspect_mapping",
            kwargs={"mapping": circular},
            tools={
                "inspect_mapping": Tool(
                    "inspect_mapping", "Inspect mapping", inspect_mapping
                )
            },
        )
        self.assertIs(result.status, ToolResultStatus.INVALID_ARGUMENTS)
        self.assertEqual(calls, 0)
    async def test_explicit_typed_dict_schema_honors_optional_and_extra_keys(self):
        calls = 0

        def configured(threshold: int, note: str = ""):
            nonlocal calls
            calls += 1
            return "ok"

        tool = Tool(
            "configured",
            "Configured tool",
            configured,
            schema=OptionalTypedOptions,
        )
        self.assertEqual(tool.json_schema["required"], ["threshold"])
        self.assertFalse(tool.json_schema["additionalProperties"])
        executor = ToolExecutor(self.team, self.agent, self.manager)
        valid = await executor.execute(
            "configured",
            kwargs={"threshold": 1},
            tools={"configured": tool},
        )
        invalid = await executor.execute(
            "configured",
            kwargs={"threshold": 1, "extra": "no"},
            tools={"configured": tool},
        )
        self.assertIs(valid.status, ToolResultStatus.SUCCESS)
        self.assertIs(invalid.status, ToolResultStatus.INVALID_ARGUMENTS)
        self.assertEqual(calls, 1)
    async def test_complete_dispatch_arguments_parse_and_validate(self):
        action = parse_text_action(
            "Action: dispatch_subagent("
            "task='Review Unicode 文档 (draft)', "
            "team_purpose='Independent review', "
            "member_configs={"
            "'Reviewer': {'model': 'default', 'role_description': 'Review'}, "
            "'Tester': {'model': 'default'}, "
            "'Arbitrator': {'model': 'default'}}, "
            "system_instructions='Use evidence\\nReport gaps', "
            "is_public_visible=False, "
            "initial_documents={'brief.md': 'Call f(x) and inspect {nested}.'})"
        )
        args, kwargs = parse_tool_arguments(action.arguments)
        result = await ToolExecutor(
            self.team, self.agent, self.manager
        ).execute(
            "dispatch_subagent",
            args,
            kwargs,
            tools=self.manager.get_available_tools(self.team, self.agent),
        )
        self.assertIs(result.status, ToolResultStatus.SUCCESS)
        child_ids = [
            child.team_id
            for child in self.team.child_teams
            if child.team_purpose == "Independent review"
        ]
        self.assertEqual(len(child_ids), 1)
    async def test_final_answer_text_inside_action_does_not_skip_tool(self):
        calls = 0

        async def remember(content: str):
            nonlocal calls
            calls += 1
            return "stored"

        self.team.tools = {
            "remember": Tool("remember", "Remember text", remember)
        }

        class SequenceClient:
            def __init__(self):
                self.responses = [
                    'Action: remember(content="Final Answer: still payload")',
                    "Thought: stored successfully\nFinal Answer: complete",
                ]

            def supports_native_tool_calling(self):
                return False

            async def generate(self, **kwargs):
                return self.responses.pop(0)

        self.agent.llm_client = SequenceClient()
        result = await self.team.execute_reasoning_step_detailed(
            self.agent,
            "work",
            "system",
            manager=self.manager,
        )
        self.assertIs(result.status, AgentTurnStatus.COMPLETED)
        self.assertEqual(result.answer, "complete")
        self.assertEqual(calls, 1)

