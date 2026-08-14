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
