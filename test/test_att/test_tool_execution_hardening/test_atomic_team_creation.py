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

    async def test_team_creation_publication_failure_rolls_back_everything(self):
        before_agents = dict(self.manager.agents)
        before_teams = dict(self.manager.teams)
        before_libraries = dict(self.manager.libraries)
        before_dirs = set(os.listdir(os.path.join(self.tmpdir, ".att_doc_libs")))
        with patch.object(
            self.manager,
            "_publish_new_staged_libraries",
            side_effect=RuntimeError("publish failed"),
        ):
            with self.assertRaisesRegex(RuntimeError, "publish failed"):
                self.manager.create_agent_team(
                    self.manager.root_ai,
                    initial_docs={"brief.md": "content"},
                )
        self.assertEqual(self.manager.agents, before_agents)
        self.assertEqual(self.manager.teams, before_teams)
        self.assertEqual(self.manager.libraries, before_libraries)
        self.assertEqual(
            set(os.listdir(os.path.join(self.tmpdir, ".att_doc_libs"))),
            before_dirs,
        )
    def test_team_creation_failure_injection_never_publishes_partial_state(self):
        managed_root = os.path.join(self.tmpdir, ".att_doc_libs")

        def assert_unchanged(before):
            agents, teams, libraries, directories = before
            self.assertEqual(self.manager.agents, agents)
            self.assertEqual(self.manager.teams, teams)
            self.assertEqual(self.manager.libraries, libraries)
            self.assertEqual(set(os.listdir(managed_root)), directories)

        def snapshot():
            return (
                dict(self.manager.agents),
                dict(self.manager.teams),
                dict(self.manager.libraries),
                set(os.listdir(managed_root)),
            )

        original_build = self.manager._build_document_library
        build_calls = 0

        def fail_during_staging(**kwargs):
            nonlocal build_calls
            build_calls += 1
            if build_calls == 2:
                raise RuntimeError("staging failed")
            return original_build(**kwargs)

        before = snapshot()
        with patch.object(
            self.manager,
            "_build_document_library",
            side_effect=fail_during_staging,
        ), self.assertRaisesRegex(RuntimeError, "staging failed"):
            self.manager.create_agent_team(self.manager.root_ai)
        assert_unchanged(before)

        before = snapshot()
        with patch.object(
            self.manager,
            "_validate_team_creation_commit",
            side_effect=RuntimeError("commit validation failed"),
        ), self.assertRaisesRegex(RuntimeError, "commit validation failed"):
            self.manager.create_agent_team(self.manager.root_ai)
        assert_unchanged(before)

        original_register = self.manager.register_agent
        register_calls = 0

        def fail_mid_commit(agent, *, auto_save=True):
            nonlocal register_calls
            register_calls += 1
            if register_calls == 2:
                raise RuntimeError("registration failed")
            return original_register(agent, auto_save=auto_save)

        before = snapshot()
        with patch.object(
            self.manager,
            "register_agent",
            side_effect=fail_mid_commit,
        ), self.assertRaisesRegex(RuntimeError, "registration failed"):
            self.manager.create_agent_team(self.manager.root_ai)
        assert_unchanged(before)
    def test_external_agent_role_is_restored_after_late_commit_failure(self):
        external = Agent("External", "Original", self.client)
        parent = self.manager.create_agent_team(self.manager.root_ai)
        before = (
            dict(self.manager.agents),
            dict(self.manager.teams),
            dict(self.manager.libraries),
            list(parent.child_teams),
        )

        with patch.object(
            parent,
            "add_child_team",
            side_effect=RuntimeError("parent update failed"),
        ), self.assertRaisesRegex(RuntimeError, "parent update failed"):
            self.manager.create_agent_team(
                parent,
                member_configs={
                    "Reviewer": external,
                    "Tester": {"model": "default"},
                    "Arbitrator": {"model": "default"},
                },
            )

        self.assertEqual(external.role, "Original")
        self.assertIsNone(external.private_doc_library_id)
        self.assertEqual(self.manager.agents, before[0])
        self.assertEqual(self.manager.teams, before[1])
        self.assertEqual(self.manager.libraries, before[2])
        self.assertEqual(parent.child_teams, before[3])
    def test_roles_and_presets_validate_actual_team_size_before_staging(self):
        before = set(os.listdir(os.path.join(self.tmpdir, ".att_doc_libs")))
        with self.assertRaisesRegex(ValueError, "at least"):
            self.manager.create_agent_team(
                self.manager.root_ai,
                member_count=3,
                roles_and_presets=[("Only", "Specialist")],
            )
        self.assertEqual(
            set(os.listdir(os.path.join(self.tmpdir, ".att_doc_libs"))), before
        )
    async def test_created_team_survives_a_later_discussion_failure(self):
        team = self.manager.create_agent_team(self.manager.root_ai)
        self.manager.config.turn_failure_policy.llm = "abort"

        class DeadClient:
            def supports_native_tool_calling(self):
                return False

            async def generate(self, **kwargs):
                raise RuntimeError("permanent")

        team.members[0].llm_client = DeadClient()
        with self.assertRaises(Exception):
            await self.manager.execute_team_discussion(
                team, "work", rounds=1, skip_audit=True
            )
        self.assertIs(self.manager.teams[team.team_id], team)
        self.assertTrue(os.path.isdir(team.doc_library.root_dir))
