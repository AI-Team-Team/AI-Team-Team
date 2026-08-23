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

    async def test_custom_error_prefixed_string_is_success(self):
        tool = Tool("custom", "Custom string", lambda: "Error: domain text")
        result = await ToolExecutor(self.team, self.agent, self.manager).execute(
            "custom", tools={"custom": tool}
        )
        self.assertIs(result.status, ToolResultStatus.SUCCESS)
        self.assertEqual(result.content, "Error: domain text")
    async def test_typed_transient_retry_policies(self):
        for policy, retry_safe, expected_attempts in [
            ("never", True, 1),
            ("retry_safe", False, 1),
            ("retry_safe", True, 3),
            ("typed_transient", False, 3),
        ]:
            with self.subTest(policy=policy, retry_safe=retry_safe):
                attempts = 0

                async def transient():
                    nonlocal attempts
                    attempts += 1
                    raise RetryableToolError("temporary")

                self.manager.config.tool_execution_retry_policy = policy
                self.manager.config.max_tool_execution_retries = 2
                self.manager.config.tool_execution_retry_backoff_factor = 0
                tool = Tool("transient", "Transient", transient, retry_safe=retry_safe)
                result = await ToolExecutor(self.team, self.agent, self.manager).execute(
                    "transient", tools={"transient": tool}
                )
                self.assertIs(result.status, ToolResultStatus.TRANSIENT_ERROR)
                self.assertEqual(result.attempts, expected_attempts)
                self.assertEqual(attempts, expected_attempts)
    async def test_tool_cancellation_propagates(self):
        started = asyncio.Event()

        async def blocked():
            started.set()
            await asyncio.Event().wait()

        task = asyncio.create_task(
            ToolExecutor(self.team, self.agent, self.manager).execute(
                "blocked", tools={"blocked": Tool("blocked", "Blocked", blocked)}
            )
        )
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
    async def test_authoritative_persistence_failure_is_a_framework_error(self):
        failed = concurrent.futures.Future()
        failed.set_exception(OSError("disk unavailable"))
        self.manager.db_path = os.path.join(self.tmpdir, "state.db")
        dirty = self.manager._new_dirty_state()
        dirty["configs"] = True
        with patch.object(self.manager._persistence, "submit", return_value=failed):
            with self.assertRaises(StatePersistenceError) as caught:
                await self.manager._commit_dirty_state(dirty)
        self.assertIsInstance(caught.exception.__cause__, OSError)
        self.assertNotIn("disk unavailable", str(caught.exception))
    async def test_tool_auditor_framework_failure_propagates(self):
        async def auditor():
            raise ATTException("framework failed")

        self.manager.tool_auditors["guarded"] = auditor
        with self.assertRaisesRegex(ATTException, "framework failed"):
            await ToolExecutor(self.team, self.agent, self.manager).execute(
                "guarded",
                tools={"guarded": Tool("guarded", "Guarded", lambda: "ok")},
            )
    async def test_sync_auditor_returning_awaitable_is_supported(self):
        async def decision():
            return True, "approved"

        def auditor():
            return decision()

        self.manager.tool_auditors["guarded"] = auditor
        result = await ToolExecutor(
            self.team, self.agent, self.manager
        ).execute(
            "guarded",
            tools={"guarded": Tool("guarded", "Guarded", lambda: "ok")},
        )
        self.assertIs(result.status, ToolResultStatus.SUCCESS)
    async def test_argument_validation_runs_before_tool_auditor(self):
        audits = 0
        calls = 0

        def guarded(count: int):
            nonlocal calls
            calls += 1
            return "ok"

        def auditor(count: int):
            nonlocal audits
            audits += 1
            return True, "approved"

        self.manager.tool_auditors["guarded"] = auditor
        result = await ToolExecutor(
            self.team, self.agent, self.manager
        ).execute(
            "guarded",
            kwargs={"count": "1"},
            tools={"guarded": Tool("guarded", "Guarded", guarded)},
        )
        self.assertIs(result.status, ToolResultStatus.INVALID_ARGUMENTS)
        self.assertEqual(audits, 0)
        self.assertEqual(calls, 0)

