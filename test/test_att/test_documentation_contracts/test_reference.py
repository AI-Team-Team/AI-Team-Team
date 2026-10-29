"""Documented schemas, defaults, fields, and model signatures match actual interfaces."""

import inspect
import re
import tempfile
import unittest

from pydantic import BaseModel

import ai_team_team
from ai_team_team import ATTConfig, ATTManager, Agent, ToolArgumentError
from ai_team_team.core.activity import contracts
from ai_team_team.core.config import ModelRequestPolicy, PersonalActivityConfig
from ai_team_team.core.manager.activity.values import Session
from ai_team_team.tool.chat import build_chat_tools
from ai_team_team.tool.executions import build_execution_tools

from ._support import API, documented_signature, section, table, uncode


class ConfigurationReferenceTests(unittest.TestCase):
    def assert_defaults(self, model, heading):
        rows = table(section(API.read_text(encoding="utf-8"), heading))[1:]
        documented = {uncode(row[0]): uncode(row[2] if model is ATTConfig else row[1]) for row in rows}
        self.assertEqual(len(rows), len(documented))
        self.assertEqual(set(documented), set(model.model_fields))
        for name, field in model.model_fields.items():
            with self.subTest(model=model.__name__, field=name):
                value = field.get_default(call_default_factory=True)
                expected = f"{type(value).__name__}()" if isinstance(value, BaseModel) else repr(value)
                # Markdown uses double quotes for string defaults.
                actual = documented[name]
                if isinstance(value, str):
                    self.assertEqual(actual.strip('"'), value)
                else:
                    self.assertEqual(actual, expected)

    def test_top_level_configuration_defaults_are_complete(self):
        self.assert_defaults(ATTConfig, "### Top-Level Parameters")

    def test_personal_capacity_and_countdown_defaults_are_complete(self):
        self.assert_defaults(PersonalActivityConfig, "#### PersonalActivityConfig Fields")

    def test_provider_policy_defaults_are_complete(self):
        self.assert_defaults(ModelRequestPolicy, "#### ModelRequestPolicy Fields")

    def test_result_model_fields_include_actual_inherited_fields(self):
        rows = table(section(API.read_text(encoding="utf-8"), "## Runtime Result Models"))[1:]
        documented = {uncode(row[0]): re.findall(r"`(\w+)`", row[1]) for row in rows}
        for name, fields in documented.items():
            with self.subTest(model=name):
                model = getattr(contracts, name, None) or getattr(ai_team_team, name)
                self.assertEqual(fields, list(model.model_fields))
        self.assertTrue({"ActivityAdmission", "SourceDeliveryReceipt", "TaskView", "ChatReadResult"} <= documented.keys())


class ToolReferenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.workspace = tempfile.TemporaryDirectory(prefix="att-doc-contracts-")
        self.addCleanup(self.workspace.cleanup)
        self.person = Agent("DocumentedPerson", "Researcher")
        self.manager = ATTManager(self.person, ATTConfig(workspace_root=self.workspace.name), persistence_mode="volatile")
        self.addAsyncCleanup(self.manager.close)

    def assert_signatures(self, heading, tools):
        rows = table(section(API.read_text(encoding="utf-8"), heading))[1:]
        documented = dict(documented_signature(row[0]) for row in rows)
        self.assertEqual(set(documented), set(tools))
        for name, tool in tools.items():
            with self.subTest(tool=name):
                actual = [(item.name, item.kind, item.default) for item in inspect.signature(tool.func).parameters.values()]
                self.assertEqual(documented[name], actual)

    async def test_personal_control_signatures_match_the_runtime_view(self):
        session = Session(self.person.agent_id, "documentation-admission", self.manager._resources.generation)
        self.assert_signatures("#### Personal Activity Tool Signatures", self.manager._activity.control_tools(session))

    async def test_conversation_signatures_include_runtime_only_tools(self):
        self.assert_signatures("### Conversation Model Tools", build_chat_tools(self.manager, team_scope=True))

    async def test_background_model_signatures_are_not_copied_from_host_methods(self):
        self.assert_signatures("### Background Task Model Tools", build_execution_tools(self.manager))

    async def test_documented_chat_inputs_validate_without_a_sender_override(self):
        tools = build_chat_tools(self.manager, team_scope=True)
        tools["send_team_message"].validate_arguments([], {"markdown": "# Findings\nExplicitly published."})
        tools["control_chat_message"].validate_arguments([], {"message_id": "message", "action": "mark_unread"})
        with self.assertRaises(ToolArgumentError):
            tools["send_team_message"].validate_arguments([], {"team_id": "another-team", "markdown": "Denied override"})
        self.assertNotIn("send_team_message", build_chat_tools(self.manager))

    async def test_documented_countdown_shape_omits_unused_units(self):
        session = Session(self.person.agent_id, "documentation-admission", self.manager._resources.generation)
        tool = self.manager._activity.control_tools(session)["set_activity_intent"]
        tool.validate_arguments([], {"intent": {"kind": "sleep", "countdown": {"hours": 1}}})
        with self.assertRaises(ToolArgumentError):
            tool.validate_arguments([], {"intent": {"kind": "sleep", "countdown": {"hours": 1, "minutes": 0}}})
