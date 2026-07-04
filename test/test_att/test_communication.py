import os
import sys
import unittest
from unittest.mock import MagicMock, AsyncMock

# Setup paths
CURRENT_DIR = os.path.dirname(__file__)
ROOT_DIR = os.path.abspath(os.path.join(CURRENT_DIR, "..", ".."))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from ai_team_team import ATTManager, Agent, ATTConfig

class TestATTCommunication(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        import tempfile, os, shutil
        self._test_old_cwd = os.getcwd()
        self._test_tmpdir = tempfile.mkdtemp(prefix="att_test_")
        os.chdir(self._test_tmpdir)
        self.addCleanup(os.chdir, self._test_old_cwd)
        self.addCleanup(shutil.rmtree, self._test_tmpdir, ignore_errors=True)

        self.mock_client = MagicMock()
        async def mock_generate(prompt, system_instruction=None, temperature=0.3, require_json=False):
            if require_json:
                if "cross-lineage" in str(prompt) or "approved" in str(prompt):
                    return '{"approved": true, "reason": "Proxied approved"}'
                return '{"is_healthy": true, "reason": "Dialogue approved."}'
            return 'Final Answer: Done'
        self.mock_client.generate = mock_generate
        self.root_ai = Agent(name="Root_AI", role="Architect", llm_client=self.mock_client)
        config = ATTConfig(communication_policy="proxied")
        self.manager = ATTManager(root_ai=self.root_ai, config=config)

    async def test_sibling_communication_negotiation(self):
        """Verify that sibling communication negotiation is managed by the parent team."""
        preset = self.manager.get_preset("generic")
        parent_team = self.manager.create_agent_team(
            creator=self.root_ai,
            member_count=3,
            roles_and_presets=preset["roles"]
        )
        
        # Spawn child 1
        c1 = parent_team.members[0].launch_att(self.manager, member_count=3)
        # Spawn child 2
        c2 = parent_team.members[1].launch_att(self.manager, member_count=3)
        
        # Default sibling talk is False
        parent_team.communication_rules["allow_sibling_talk"] = False
        allowed = await self.manager.broker.negotiate_communication(c1, c2)
        self.assertFalse(allowed)
        
        # Enable sibling talk
        parent_team.communication_rules["allow_sibling_talk"] = True
        allowed = await self.manager.broker.negotiate_communication(c1, c2)
        self.assertTrue(allowed)

    async def test_sibling_talk_permission_tool(self):
        """Verify that sibling talk permissions can be dynamically set by parents only."""
        from ai_team_team.tool import get_default_tools
        
        parent_team = self.manager.create_agent_team(creator=self.root_ai, member_count=3)
        child_team = self.manager.create_agent_team(creator=parent_team, member_count=3)
        unrelated_team = self.manager.create_agent_team(creator=self.root_ai, member_count=3)
        
        # Setup context and register tools on parent
        context = {"att_manager": self.manager}
        parent_team.tools = get_default_tools(context, parent_team)
        unrelated_team.tools = get_default_tools(context, unrelated_team)
        
        # 1. Unrelated team attempts to grant child_team sibling talk -> fails
        set_sibling_tool = unrelated_team.tools["set_sibling_talk"]
        res = await set_sibling_tool(child_team.team_id, True)
        self.assertTrue("Error" in res)
        self.assertFalse(child_team.communication_rules["allow_sibling_talk"])
        
        # 2. Parent team grants child_team sibling talk -> succeeds
        set_sibling_tool = parent_team.tools["set_sibling_talk"]
        res = await set_sibling_tool(child_team.team_id, True)
        self.assertTrue("Successfully" in res)
        self.assertTrue(child_team.communication_rules["allow_sibling_talk"])

    async def test_peer_talk_broker_negotiation(self):
        """Verify cross-lineage message blocking and negotiation channel validation."""
        self.manager.register_tools_context({"att_manager": self.manager})

        # Spawn two level-1 teams
        team_a = self.manager.create_agent_team(creator=self.root_ai, member_count=3)
        team_b = self.manager.create_agent_team(creator=self.root_ai, member_count=3)

        # Spawn level-2 child teams
        team_a1 = self.manager.create_agent_team(creator=team_a, member_count=3)
        team_b1 = self.manager.create_agent_team(creator=team_b, member_count=3)

        send_tool_a1 = team_a1.tools["send_peer_message"]
        negotiate_tool_a1 = team_a1.tools["negotiate_peer_talk"]

        # Default: no agreement exists, communication should be denied
        res_denied = await send_tool_a1(team_id=team_b1.team_id, message="Hello from A1")
        self.assertIn("Permission Denied", res_denied)

        # Establish peer agreement
        res_negotiated = await negotiate_tool_a1(target_team_id=team_b1.team_id, rationale="Align on cross-team dependencies")
        self.assertIn("Success", res_negotiated)

        # Now communication should succeed
        res_success = await send_tool_a1(team_id=team_b1.team_id, message="Hello from A1")
        self.assertIn("Message successfully delivered", res_success)
        self.assertEqual(len(team_b1.message_inbox), 1)
        self.assertEqual(team_b1.message_inbox[0]["objective"], "Hello from A1")

if __name__ == "__main__":
    unittest.main()
