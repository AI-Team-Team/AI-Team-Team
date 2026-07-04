import os
import sys
import unittest
import json
from unittest.mock import MagicMock, AsyncMock

# Setup paths
CURRENT_DIR = os.path.dirname(__file__)
ROOT_DIR = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from ai_team_team import ATTManager, Agent, ATTConfig, TokenLimitExceededError

class TestATTFailover(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mock_client = MagicMock()
        # Default mock response for standard LLM calls
        self.mock_client.generate = AsyncMock(return_value="Final Answer: Done.")
        self.root_ai = Agent(name="Root_AI", role="Architect", llm_client=self.mock_client)

    async def test_token_limit_exceeded_error(self):
        """Verify that TokenLimitExceededError is raised when session token budget is exceeded."""
        config = ATTConfig(
            model_token_limits={"default": 2}  # Set very small limit to guarantee immediate circuit breaker
        )
        manager = ATTManager(root_ai=self.root_ai, config=config)
        team = manager.create_agent_team(creator=self.root_ai, member_count=3)
        
        # Disable failover to let exception propagate directly
        manager.config.failover_policy = "none"

        with self.assertRaises(TokenLimitExceededError):
            await manager.execute_team_discussion(team, "Let's debate", rounds=1)

    async def test_auto_fallback_failover(self):
        """Verify that agent automatically falls back to another model under budget when auto failover is set."""
        config = ATTConfig(
            model_token_limits={"default": 5, "gemini-3.5": 5000},
            failover_policy="auto"
        )
        manager = ATTManager(root_ai=self.root_ai, config=config)
        
        # Register a gemini-3.5 mock client
        mock_gemini = MagicMock()
        mock_gemini.generate = AsyncMock(return_value="Final Answer: Resolved on Gemini.")
        manager.llm_clients["gemini-3.5"] = mock_gemini
        
        # Setup system event tracker
        system_events = []
        def on_system_event(event_type, details):
            system_events.append((event_type, details))
        manager.on_system_event = on_system_event

        team = manager.create_agent_team(creator=self.root_ai, member_count=3)
        
        # Execute debate: first turn will trigger limit for default model, and hot-swap to gemini-3.5
        transcript = await manager.execute_team_discussion(team, "Debate prompt", rounds=1)
        
        # Verify it completed successfully using gemini-3.5
        self.assertIn("Resolved on Gemini.", transcript)
        
        # Verify event callback fired
        self.assertTrue(any(e[0] == "model_failover" for e in system_events))
        failover_event = next(e for e in system_events if e[0] == "model_failover")[1]
        self.assertEqual(failover_event["old_model"], "default")
        self.assertEqual(failover_event["new_model"], "gemini-3.5")

    async def test_parent_representative_delegation_failover(self):
        """Verify that child team synchronously delegates failover model choice to parent representative LLM."""
        config = ATTConfig(
            model_token_limits={"default": 5, "opus-4.8": 5000},
            failover_policy="parent"
        )
        manager = ATTManager(root_ai=self.root_ai, config=config)
        
        # Setup parent team and child team
        parent_team = manager.create_agent_team(creator=self.root_ai, member_count=3, preset_name="generic")
        child_team = manager.create_agent_team(creator=parent_team, member_count=3, preset_name="generic")
        
        # Mock opus client
        mock_opus = MagicMock()
        mock_opus.generate = AsyncMock(return_value="Final Answer: Resolved on Claude Opus.")
        manager.llm_clients["opus-4.8"] = mock_opus

        # We configure generator handler to respond to parent rep decision query with json,
        # and standard queries with text
        async def mock_handler(model_name, prompt, system_instruction=None, temperature=0.3, require_json=False):
            if require_json and "selected_model" in prompt:
                return '{"selected_model": "opus-4.8"}'
            return "Final Answer: Parent logic."

        manager.register_generator_handler(mock_handler)
        
        # Parent representative (first member) uses the handler
        parent_team.members[0].llm_client = manager.supervisor.llm_client # uses default wrapper

        # Execute debate on child team
        transcript = await manager.execute_team_discussion(child_team, "Run child debate", rounds=1)
        
        # Verify it hot-swapped to opus-4.8 selected by parent
        self.assertIn("Resolved on Claude Opus.", transcript)

if __name__ == "__main__":
    unittest.main()
