import os
import sys
import unittest
import asyncio
from unittest.mock import MagicMock, AsyncMock

# Setup paths
CURRENT_DIR = os.path.dirname(__file__)
ROOT_DIR = os.path.abspath(os.path.join(CURRENT_DIR, "..", ".."))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from ai_team_team import InteractionStatus, ATTManager, Agent, Tool, ATTConfig
from test.personal_activity import interact_and_idle

class TestValidationAndRetry(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        import tempfile, os, shutil
        self._test_old_cwd = os.getcwd()
        self._test_tmpdir = tempfile.mkdtemp(prefix="att_test_")
        os.chdir(self._test_tmpdir)
        self.addCleanup(shutil.rmtree, self._test_tmpdir, ignore_errors=True)
        self.addCleanup(os.chdir, self._test_old_cwd)

        self.mock_client = MagicMock()
        self.mock_client.generate = AsyncMock(return_value='{"is_healthy": true, "reason": "Dialogue approved."}')
        self.mock_client.supports_native_tool_calling = MagicMock(return_value=False)
        
        self.root_ai = Agent(name="Root_AI", role="Architect", llm_client=self.mock_client)
        self.config = ATTConfig(
            tool_calling_mode="react"
        )
        self.manager = ATTManager(root_ai=self.root_ai, config=self.config, persistence_mode="volatile")
        self.addAsyncCleanup(self.manager.close)

    async def test_create_agent_team_invalid_model(self):
        """Verify that create_agent_team raises a ValueError when passed an unregistered model."""
        preset = self.manager.get_preset("generic")
        with self.assertRaises(ValueError) as ctx:
            self.manager.create_agent_team(
                parent=self.root_ai, creator=self.root_ai,
                member_count=3,
                roles_and_presets=preset["roles"],
                roles_and_models={"Specialist_A": "invalid-model-name"}
            )
        self.assertIn("Model 'invalid-model-name' is not registered", str(ctx.exception))

    async def test_dispatch_subagent_tool_invalid_model(self):
        """Verify that dispatch_subagent returns an error Observation if model configs are unregistered."""
        # Add tool context and bind default tools
        self.manager.register_tools_context({"att_manager": self.manager})
        team = self.manager.create_agent_team(parent=self.root_ai, creator=self.root_ai, member_count=3)
        dispatch_tool = team.tools["dispatch_subagent"]

        member_configs = {
            "Specialist_A": {"model": "invalid-model-name", "role_description": "A", "system_instructions": "A"},
            "Specialist_B": {"model": "default", "role_description": "B", "system_instructions": "B"},
            "Specialist_C": {"model": "default", "role_description": "C", "system_instructions": "C"}
        }

        agent_token = self.manager._active_tool_agent.set(team.members[0])
        team_token = self.manager._active_team.set(team)
        try:
            observation = await dispatch_tool(
                task="Solve task",
                team_purpose="Sub task",
                member_configs=member_configs
            )
        finally:
            self.manager._active_team.reset(team_token)
            self.manager._active_tool_agent.reset(agent_token)
        self.assertIn("Error: Model 'invalid-model-name' is not registered", observation)

    async def test_add_team_member_tool_invalid_model(self):
        """Verify that add_team_member returns an error Observation if model is unregistered."""
        self.manager.register_tools_context({"att_manager": self.manager})
        parent_team = self.manager.create_agent_team(parent=self.root_ai, creator=self.root_ai, member_count=3)
        child_team = self.manager.create_agent_team(parent=parent_team, creator=parent_team, member_count=3)
        
        # Specialist agent inside parent team calls add_team_member
        add_tool = parent_team.tools["add_team_member"]
        observation = await add_tool(
            team_id=child_team.team_id,
            role_name="New_Specialist",
            model_name="invalid-model-name",
            role_description="Descr",
            system_instructions="Inst"
        )
        self.assertIn("Error: Model 'invalid-model-name' is not registered", observation)

    async def test_initiate_membership_vote_tool_invalid_model(self):
        """Verify that initiate_membership_vote returns an error Observation if model is unregistered."""
        self.manager.config.enable_membership_voting = True
        self.manager.register_tools_context({"att_manager": self.manager})
        team = self.manager.create_agent_team(parent=self.root_ai, creator=self.root_ai, member_count=3)
        
        vote_tool = team.tools["initiate_membership_vote"]
        observation = await vote_tool(
            action="add",
            target="New_Role",
            rationale="Need more help",
            proposed_details={"model": "invalid-model-name"}
        )
        self.assertIn("Error: Model 'invalid-model-name' is not registered", observation)

    async def test_text_argument_failures_remain_observations_until_explicit_idle(self):
        calls = []

        def typed_tool(value: int):
            calls.append(value)
            return value

        self.manager.register_tool("typed_tool", "Requires an integer", typed_tool)
        team = self.manager.create_agent_team(creator=self.root_ai)
        self.mock_client.generate.side_effect = [
            "Action: typed_tool(value='bad')",
            "Action: typed_tool(value='still bad')",
            "Action: typed_tool(value='bad again')",
            "Action: typed_tool(value=12)",
            "Final Answer: Corrected.",
            "Action: set_activity_intent(intent={'kind': 'idle'})",
        ]
        result = await interact_and_idle(self.manager, team.members[0], "Continue.", team=team)
        self.assertIs(result.status, InteractionStatus.COMPLETED)
        self.assertEqual(result.answer, "Corrected.")
        self.assertEqual(calls, [12])
        states = [row for row in self.manager._records.snapshot()
            if row.table_name == "health_detector_states" and row.values["tool_key"] == "typed_tool"]
        self.assertEqual(list(states[0].values["samples"]), [])
        self.assertFalse(any(row.table_name == "audit_runs" for row in self.manager._records.snapshot()))

    async def test_native_invalid_batch_does_not_terminate_continuing_activity(self):
        from ai_team_team import LLMResponse, ToolCall

        self.manager.config.tool_calling_mode = "native"
        calls = []

        def typed_tool(value: int):
            calls.append(value)
            return value

        self.manager.register_tool("typed_tool", "Requires an integer", typed_tool)
        team = self.manager.create_agent_team(creator=self.root_ai)
        self.mock_client.generate.side_effect = [
            LLMResponse(tool_calls=[ToolCall(f"invalid-{index}", "typed_tool", {"value": "bad"})
                for index in range(3)]),
            LLMResponse(tool_calls=[ToolCall("corrected", "typed_tool", {"value": 7})]),
            LLMResponse(text="Recovered."),
            LLMResponse(tool_calls=[ToolCall("idle", "set_activity_intent", {"intent": {"kind": "idle"}})]),
        ]
        result = await interact_and_idle(self.manager, team.members[0], "Continue.", team=team)
        self.assertIs(result.status, InteractionStatus.COMPLETED)
        self.assertEqual(calls, [7])
        observations = [row for row in self.manager._records.snapshot()
            if row.table_name == "health_observations" and row.values["tool_name"] == "typed_tool"]
        self.assertEqual(len([row for row in observations if row.values["valid"] == 0]), 3)

if __name__ == "__main__":
    unittest.main()
