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

from ai_team_team import ATTManager, Agent, Tool, ATTConfig, ATTException
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
        self.config = ATTConfig(tool_calling_mode="react", max_tool_retries=2)
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

    async def test_react_max_tool_retries_limit(self):
        """Verify that TextReactReasoningStrategy raises an exception when max_tool_retries limit is exceeded."""
        self.manager.register_tools_context({"att_manager": self.manager})
        team = self.manager.create_agent_team(creator=self.root_ai, member_count=3)
        
        # We register a tool that fails/returns an error
        def failing_tool():
            return "Error: Database connection lost."
        self.manager.register_tool("fail_tool", "Fails always", failing_tool)
        
        # Inject side effect where the LLM repeatedly calls the failing tool
        self.mock_client.generate.side_effect = [
            "Thought: Try fail_tool.\nAction: fail_tool()",
            "Thought: Try fail_tool again.\nAction: fail_tool()",
            "Thought: Try one more time.\nAction: fail_tool()",
            "Final Answer: Unreachable"
        ]
        
        agent = team.members[0]
        # max_tool_retries is 2 in setUp. We expect it to raise ATTException on the 2nd failing call.
        with self.assertRaises(ATTException) as ctx:
            await team.execute_react_step(
                agent=agent,
                prompt="Start task",
                system_instruction="Do it",
                max_steps=5,
                manager=self.manager
            )
        self.assertIn("Maximum tool retries (2) exceeded", str(ctx.exception))
        self.assertIn("Database connection lost", str(ctx.exception))

    async def test_native_max_tool_retries_limit(self):
        """Verify that NativeReasoningStrategy raises an exception when max_tool_retries limit is exceeded."""
        self.manager.register_tools_context({"att_manager": self.manager})
        self.mock_client.supports_native_tool_calling = MagicMock(return_value=True)
        self.manager.config.tool_calling_mode = "native"
        
        team = self.manager.create_agent_team(creator=self.root_ai, member_count=3)
        
        def failing_tool():
            return "Error: API Timeout."
        self.manager.register_tool("fail_tool", "Fails always", failing_tool)
        
        # Mock structured LLM Response with tool calls
        from ai_team_team.core.response import ToolCall, LLMResponse
        tool_call_1 = ToolCall(call_id="call_1", name="fail_tool", arguments={})
        tool_call_2 = ToolCall(call_id="call_2", name="fail_tool", arguments={})
        
        self.mock_client.generate.side_effect = [
            LLMResponse(text="Executing tools", tool_calls=[tool_call_1, tool_call_2]),
            LLMResponse(text="Final Answer: Done")
        ]
        
        agent = team.members[0]
        # max_tool_retries is 2. Both tools will return errors in the first round.
        # This will increment the retry counter to 2, hitting the limit of 2 immediately.
        with self.assertRaises(ATTException) as ctx:
            await team.execute_react_step(
                agent=agent,
                prompt="Start task",
                system_instruction="Do it",
                max_steps=5,
                manager=self.manager
            )
        self.assertIn("Maximum tool retries (2) exceeded", str(ctx.exception))

if __name__ == "__main__":
    unittest.main()
