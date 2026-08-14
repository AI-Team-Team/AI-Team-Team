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

from ai_team_team import AgentTurnStatus, ATTManager, Agent, Tool, ATTConfig
from ai_team_team.core.strategies import TextReactReasoningStrategy, NativeReasoningStrategy

class TestValidationAndRetry(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        import tempfile, os, shutil
        self._test_old_cwd = os.getcwd()
        self._test_tmpdir = tempfile.mkdtemp(prefix="att_test_")
        os.chdir(self._test_tmpdir)
        self.addCleanup(os.chdir, self._test_old_cwd)
        self.addCleanup(shutil.rmtree, self._test_tmpdir, ignore_errors=True)

        self.mock_client = MagicMock()
        self.mock_client.generate = AsyncMock(return_value='{"is_healthy": true, "reason": "Dialogue approved."}')
        self.mock_client.supports_native_tool_calling = MagicMock(return_value=False)
        
        self.root_ai = Agent(name="Root_AI", role="Architect", llm_client=self.mock_client)
        self.config = ATTConfig(
            tool_calling_mode="react", max_tool_argument_retries=2
        )
        self.manager = ATTManager(root_ai=self.root_ai, config=self.config)

    async def test_create_agent_team_invalid_model(self):
        """Verify that create_agent_team raises a ValueError when passed an unregistered model."""
        preset = self.manager.get_preset("generic")
        with self.assertRaises(ValueError) as ctx:
            self.manager.create_agent_team(
                creator=self.root_ai,
                member_count=3,
                roles_and_presets=preset["roles"],
                roles_and_models={"Specialist_A": "invalid-model-name"}
            )
        self.assertIn("Model 'invalid-model-name' is not registered", str(ctx.exception))

    async def test_dispatch_subagent_tool_invalid_model(self):
        """Verify that dispatch_subagent returns an error Observation if model configs are unregistered."""
        # Add tool context and bind default tools
        self.manager.register_tools_context({"att_manager": self.manager})
        team = self.manager.create_agent_team(creator=self.root_ai, member_count=3)
        dispatch_tool = team.tools["dispatch_subagent"]

        member_configs = {
            "Specialist_A": {"model": "invalid-model-name", "role_description": "A", "system_instructions": "A"},
            "Specialist_B": {"model": "default", "role_description": "B", "system_instructions": "B"},
            "Specialist_C": {"model": "default", "role_description": "C", "system_instructions": "C"}
        }

        observation = await dispatch_tool(
            task="Solve task",
            team_purpose="Sub task",
            member_configs=member_configs
        )
        self.assertIn("Error: Model 'invalid-model-name' is not registered", observation)

    async def test_add_team_member_tool_invalid_model(self):
        """Verify that add_team_member returns an error Observation if model is unregistered."""
        self.manager.register_tools_context({"att_manager": self.manager})
        parent_team = self.manager.create_agent_team(creator=self.root_ai, member_count=3)
        child_team = self.manager.create_agent_team(creator=parent_team, member_count=3)
        
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
        team = self.manager.create_agent_team(creator=self.root_ai, member_count=3)
        
        vote_tool = team.tools["initiate_membership_vote"]
        observation = await vote_tool(
            action="add",
            target="New_Role",
            rationale="Need more help",
            proposed_details={"model": "invalid-model-name"}
        )
        self.assertIn("Error: Model 'invalid-model-name' is not registered", observation)

    async def test_react_argument_correction_limit_isolates_turn(self):
        """Verify that repeated invalid Text arguments produce an incomplete turn."""
        self.manager.register_tools_context({"att_manager": self.manager})
        team = self.manager.create_agent_team(creator=self.root_ai, member_count=3)
        
        call_count = 0

        def typed_tool(value: int):
            nonlocal call_count
            call_count += 1
            return value

        self.manager.register_tool("typed_tool", "Requires an integer", typed_tool)
        
        # Inject side effect where the LLM repeatedly calls the failing tool
        self.mock_client.generate.side_effect = [
            "Thought: Try.\nAction: typed_tool(value='bad')",
            "Thought: Correct.\nAction: typed_tool(value='still bad')",
            "Thought: Correct again.\nAction: typed_tool(value='bad again')",
            "Final Answer: Unreachable"
        ]
        
        agent = team.members[0]
        result = await team.execute_reasoning_step_detailed(
            agent=agent,
            prompt="Start task",
            system_instruction="Do it",
            max_steps=5,
            manager=self.manager,
        )
        self.assertIs(result.status, AgentTurnStatus.INCOMPLETE)
        self.assertEqual(result.error_kind, "tool_argument_retries_exhausted")
        self.assertEqual(call_count, 0)

    async def test_native_argument_correction_counts_once_per_batch(self):
        """Verify that a parallel invalid Native batch consumes one correction opportunity."""
        self.manager.register_tools_context({"att_manager": self.manager})
        self.mock_client.supports_native_tool_calling = MagicMock(return_value=True)
        self.manager.config.tool_calling_mode = "native"
        
        team = self.manager.create_agent_team(creator=self.root_ai, member_count=3)
        
        call_count = 0

        def typed_tool(value: int):
            nonlocal call_count
            call_count += 1
            return value

        self.manager.register_tool("typed_tool", "Requires an integer", typed_tool)
        
        # Mock structured LLM Response with tool calls
        from ai_team_team.core.response import ToolCall, LLMResponse
        def invalid_batch(index):
            return LLMResponse(
                text="Executing tools",
                tool_calls=[
                    ToolCall(
                        call_id=f"call_{index}_{item}",
                        name="typed_tool",
                        arguments={"value": "bad"},
                    )
                    for item in range(3)
                ],
            )
        
        self.mock_client.generate.side_effect = [
            invalid_batch(1),
            invalid_batch(2),
            invalid_batch(3),
            LLMResponse(text="Final Answer: Unreachable"),
        ]
        
        agent = team.members[0]
        result = await team.execute_reasoning_step_detailed(
            agent=agent,
            prompt="Start task",
            system_instruction="Do it",
            max_steps=5,
            manager=self.manager,
        )
        self.assertIs(result.status, AgentTurnStatus.INCOMPLETE)
        self.assertEqual(result.error_kind, "tool_argument_retries_exhausted")
        self.assertEqual(call_count, 0)

if __name__ == "__main__":
    unittest.main()
