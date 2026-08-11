import os
import sys
import unittest
import json
from unittest.mock import MagicMock, AsyncMock

# Setup paths
CURRENT_DIR = os.path.dirname(__file__)
ROOT_DIR = os.path.abspath(os.path.join(CURRENT_DIR, "..", ".."))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from ai_team_team import ATTManager, Agent, ATTConfig, TokenLimitExceededError

class TestATTFailover(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        import tempfile, os, shutil
        self._test_old_cwd = os.getcwd()
        self._test_tmpdir = tempfile.mkdtemp(prefix="att_test_")
        os.chdir(self._test_tmpdir)
        self.addCleanup(os.chdir, self._test_old_cwd)
        self.addCleanup(shutil.rmtree, self._test_tmpdir, ignore_errors=True)

        self.mock_client = MagicMock()
        # Default mock response for standard LLM calls
        self.mock_client.generate = AsyncMock(return_value="Final Answer: Done.")
        self.mock_client.supports_output_token_limit.return_value = (
            "max_output_tokens"
        )
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
        mock_gemini.supports_output_token_limit.return_value = (
            "max_output_tokens"
        )
        manager.llm_clients["gemini-3.5"] = mock_gemini
        
        # Setup system event tracker
        system_events = []
        def on_system_event(event_type, details):
            system_events.append((event_type, details))
        manager.on_system_event = on_system_event

        team = manager.create_agent_team(creator=self.root_ai, member_count=3)
        
        # Execute debate: first turn will trigger limit for default model, and hot-swap to gemini-3.5
        transcript = await manager.execute_team_discussion(
            team, "Debate prompt", rounds=1, skip_audit=True
        )
        await manager.flush_callbacks()
        
        # Verify it completed successfully using gemini-3.5
        self.assertIn("Resolved on Gemini.", transcript)
        
        # Verify event callback fired
        self.assertTrue(any(e[0] == "model_failover" for e in system_events))
        failover_event = next(e for e in system_events if e[0] == "model_failover")[1]
        self.assertEqual(failover_event["old_model"], "default")
        self.assertEqual(failover_event["new_model"], "gemini-3.5")

    async def test_parent_agent_team_majority_failover(self):
        """Verify that parent failover uses an AgentTeam-wide model ballot."""
        async def root_generate(require_json=False, **kwargs):
            if require_json:
                return '{"is_healthy": true, "reason": "healthy"}'
            return "Final Answer: Done."

        self.mock_client.generate = root_generate
        config = ATTConfig(
            model_token_limits={
                "default": 5000,
                "low-budget": 5,
                "opus-4.8": 5000,
            },
            failover_policy="parent"
        )
        manager = ATTManager(root_ai=self.root_ai, config=config)
        manager.llm_clients["low-budget"] = self.mock_client
        
        # Mock opus client
        mock_opus = MagicMock()
        mock_opus.generate = AsyncMock(return_value="Final Answer: Resolved on Claude Opus.")
        mock_opus.supports_output_token_limit.return_value = (
            "max_output_tokens"
        )
        manager.llm_clients["opus-4.8"] = mock_opus

        governor = MagicMock()

        async def govern(prompt=None, require_json=False, **kwargs):
            if "Allowed aliases" in str(prompt):
                return '{"model_alias": "opus-4.8", "reason": "majority"}'
            if require_json:
                return '{"is_healthy": true, "reason": "healthy"}'
            return "Final Answer: Parent discussion."

        governor.generate = govern
        governor.supports_output_token_limit.return_value = "max_output_tokens"
        manager.llm_clients["governor"] = governor

        parent_team = manager.create_agent_team(
            creator=self.root_ai,
            member_configs={
                "P1": {"model": "governor"},
                "P2": {"model": "governor"},
                "P3": {"model": "governor"},
            },
        )
        child_team = manager.create_agent_team(
            creator=parent_team,
            member_configs={
                "C1": {"model": "low-budget"},
                "C2": {"model": "low-budget"},
                "C3": {"model": "low-budget"},
            },
        )
        error = TokenLimitExceededError("budget exhausted")
        error.required_tokens = 1
        changed = await manager.handle_failover(
            child_team.members[0], child_team, error
        )

        self.assertTrue(changed)
        self.assertIs(child_team.members[0].llm_client, mock_opus)

    async def test_top_level_parent_failover_uses_root_agent(self):
        async def root_govern(prompt=None, require_json=False, **kwargs):
            if "Allowed model aliases" in str(prompt):
                return '{"model_alias": "high", "reason": "root choice"}'
            if require_json:
                return '{"is_healthy": true, "reason": "healthy"}'
            return "Final Answer: Done."

        self.mock_client.generate = root_govern
        config = ATTConfig(
            model_token_limits={
                "default": 5000,
                "low": 5,
                "high": 5000,
            },
            failover_policy="parent",
            parent_failover_timeout_seconds=1,
        )
        manager = ATTManager(root_ai=self.root_ai, config=config)
        low_client = MagicMock()
        low_client.generate = AsyncMock(return_value="Final Answer: low")
        low_client.supports_output_token_limit.return_value = (
            "max_output_tokens"
        )
        manager.register_llm_client("low", low_client)
        high_client = MagicMock()
        high_client.generate = AsyncMock(return_value="Final Answer: high")
        high_client.supports_output_token_limit.return_value = (
            "max_output_tokens"
        )
        manager.register_llm_client("high", high_client)
        team = manager.create_agent_team(
            creator=self.root_ai,
            member_configs={
                "A": {"model": "low"},
                "B": {"model": "low"},
                "C": {"model": "low"},
            },
        )
        error = TokenLimitExceededError("budget exhausted")
        error.required_tokens = 1

        changed = await manager.handle_failover(team.members[0], team, error)

        self.assertTrue(changed)
        self.assertIs(team.members[0].llm_client, high_client)
        await manager.close()

if __name__ == "__main__":
    unittest.main()
