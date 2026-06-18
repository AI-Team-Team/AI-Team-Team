import os
import sys
import unittest
from unittest.mock import MagicMock, AsyncMock

# Setup paths
CURRENT_DIR = os.path.dirname(__file__)
ROOT_DIR = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from ai_team_team import ATTManager, Agent, AgentTeam, ATTConfig

class TestLevel1Communication(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mock_client = MagicMock()
        self.mock_client.generate = AsyncMock(
            return_value='{"approved": true, "reason": "Root AI Approval"}'
        )
        self.root_ai = Agent(name="Root_AI", role="Architect", llm_client=self.mock_client)
        self.config = ATTConfig(
            communication_policy="permissive",
            migration_policy="ancestor_approval",
            min_subagent_team_size=3
        )
        self.manager = ATTManager(
            root_ai=self.root_ai,
            config=self.config
        )
        self.manager.register_tools_context({"att_manager": self.manager})

    async def test_level_1_communication_permissive(self):
        """Verify that Level 1 sibling teams can communicate directly in permissive mode without prior negotiation."""
        self.config.communication_policy = "permissive"

        # Spawn two Level 1 teams directly spawned by Root AI
        team_a = self.manager.create_agent_team(
            creator=self.root_ai,
            team_purpose="Research Domain A",
            member_configs={
                "A1": {"model": "default"}, "A2": {"model": "default"}, "A3": {"model": "default"}
            }
        )
        team_b = self.manager.create_agent_team(
            creator=self.root_ai,
            team_purpose="Research Domain B",
            member_configs={
                "B1": {"model": "default"}, "B2": {"model": "default"}, "B3": {"model": "default"}
            }
        )

        # In permissive mode, they can negotiate communication instantly (returns True)
        can_talk = await self.manager.broker.negotiate_communication(team_a, team_b)
        self.assertTrue(can_talk)

        # Verify send_peer_message tool works directly
        send_tool = team_a.tools["send_peer_message"]
        res = await send_tool(team_id=team_b.team_id, message="Hello sibling B")
        self.assertEqual(res, f"Message successfully delivered to team '{team_b.team_id}'.")
        self.assertEqual(len(team_b.message_inbox), 1)
        self.assertEqual(team_b.message_inbox[0]["objective"], "Hello sibling B")

    async def test_level_1_communication_proxied_approval(self):
        """Verify that Level 1 teams can negotiate and establish agreement in proxied mode via Root AI."""
        self.config.communication_policy = "proxied"

        team_a = self.manager.create_agent_team(
            creator=self.root_ai,
            team_purpose="Research Domain A",
            member_configs={
                "A1": {"model": "default"}, "A2": {"model": "default"}, "A3": {"model": "default"}
            }
        )
        team_b = self.manager.create_agent_team(
            creator=self.root_ai,
            team_purpose="Research Domain B",
            member_configs={
                "B1": {"model": "default"}, "B2": {"model": "default"}, "B3": {"model": "default"}
            }
        )

        # Clear agreements
        self.manager.broker.peer_talk_agreements.clear()

        # 1. First establish_peer_agreement with approved response
        self.mock_client.generate = AsyncMock(
            return_value='{"approved": true, "reason": "Root AI says yes"}'
        )
        success = await self.manager.broker.establish_peer_agreement(team_a, team_b, rationale="Need specs")
        self.assertTrue(success)
        self.assertIn((team_a.team_id, team_b.team_id), self.manager.broker.peer_talk_agreements)

        # 2. Verify communication is now allowed
        can_talk = await self.manager.broker.negotiate_communication(team_a, team_b)
        self.assertTrue(can_talk)

    async def test_level_1_communication_proxied_rejection(self):
        """Verify that Level 1 teams fail negotiation in proxied mode when Root AI rejects it."""
        self.config.communication_policy = "proxied"

        team_a = self.manager.create_agent_team(
            creator=self.root_ai,
            team_purpose="Research Domain A",
            member_configs={
                "A1": {"model": "default"}, "A2": {"model": "default"}, "A3": {"model": "default"}
            }
        )
        team_b = self.manager.create_agent_team(
            creator=self.root_ai,
            team_purpose="Research Domain B",
            member_configs={
                "B1": {"model": "default"}, "B2": {"model": "default"}, "B3": {"model": "default"}
            }
        )

        self.manager.broker.peer_talk_agreements.clear()

        # Mock Root AI to reject
        self.mock_client.generate = AsyncMock(
            return_value='{"approved": false, "reason": "Root AI says no"}'
        )
        success = await self.manager.broker.establish_peer_agreement(team_a, team_b, rationale="Need specs")
        self.assertFalse(success)
        self.assertNotIn((team_a.team_id, team_b.team_id), self.manager.broker.peer_talk_agreements)

        # Communication should still be denied
        can_talk = await self.manager.broker.negotiate_communication(team_a, team_b)
        self.assertFalse(can_talk)

if __name__ == "__main__":
    unittest.main()
