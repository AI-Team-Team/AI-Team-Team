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

class TestATTSpawning(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mock_client = MagicMock()
        self.mock_client.generate = AsyncMock(return_value='{"is_healthy": true, "reason": "Dialogue approved."}')
        self.root_ai = Agent(name="Root_AI", role="Architect", llm_client=self.mock_client)
        self.manager = ATTManager(root_ai=self.root_ai)

    def test_agent_team_assertion_size(self):
        """Verify that an Agent Team (AT) must contain at least 3 members."""
        with self.assertRaises(AssertionError):
            self.manager.create_agent_team(creator=self.root_ai, member_count=2)

    def test_agent_team_spawning(self):
        """Verify that an Agent Team (AT) is spawned successfully with 3 members."""
        preset = self.manager.get_preset("generic")
        team = self.manager.create_agent_team(
            creator=self.root_ai,
            member_count=3,
            roles_and_presets=preset["roles"],
            preset_name="generic",
            system_instructions=preset["system_instructions"]
        )
        self.assertEqual(len(team.members), 3)
        self.assertEqual(team.preset_name, "generic")
        self.assertEqual(team.creator, self.root_ai)

    def test_recursive_att_spawning(self):
        """Verify that any team member can recursively spawn their own child AT."""
        preset = self.manager.get_preset("generic")
        parent_team = self.manager.create_agent_team(
            creator=self.root_ai,
            member_count=3,
            roles_and_presets=preset["roles"]
        )
        
        # Sibling Member 1 launches recursive child team
        member1 = parent_team.members[0]
        child_team = member1.launch_att(self.manager, member_count=3, roles_and_presets=preset["roles"])
        
        self.assertEqual(child_team.creator, member1)
        self.assertEqual(len(child_team.members), 3)

    def test_agent_spawned_subteam_depth(self):
        """Verify that sub-teams spawned by agents correctly track lineage depth and parent team."""
        preset = self.manager.get_preset("generic")
        parent_team = self.manager.create_agent_team(
            creator=self.root_ai,
            member_count=3,
            roles_and_presets=preset["roles"]
        )
        self.assertEqual(parent_team.depth, 1)
        self.assertIsNone(parent_team.parent_team)
        
        # Level 2 team spawned by agent of Level 1 team
        member1 = parent_team.members[0]
        c1 = member1.launch_att(self.manager, member_count=3, roles_and_presets=preset["roles"])
        self.assertEqual(c1.depth, 2)
        self.assertEqual(c1.parent_team, parent_team)
        
        # Level 3 team spawned by agent of Level 2 team
        member2 = c1.members[0]
        c2 = member2.launch_att(self.manager, member_count=3, roles_and_presets=preset["roles"])
        self.assertEqual(c2.depth, 3)
        self.assertEqual(c2.parent_team, c1)

    async def test_arbitrary_depth_limit(self):
        """Verify that configuring a larger depth limit works and triggers rejection only at that limit."""
        config = ATTConfig(max_delegation_depth=4)
        manager = ATTManager(root_ai=self.root_ai, config=config)
        # Register tools context on manager to bind dispatch_subagent
        manager.register_tools_context({"att_manager": manager})
        
        preset = manager.get_preset("generic")
        team1 = manager.create_agent_team(creator=self.root_ai, member_count=3, roles_and_presets=preset["roles"])
        self.assertEqual(team1.depth, 1)
        
        team2 = team1.members[0].launch_att(manager, member_count=3, roles_and_presets=preset["roles"])
        self.assertEqual(team2.depth, 2)
        
        team3 = team2.members[0].launch_att(manager, member_count=3, roles_and_presets=preset["roles"])
        self.assertEqual(team3.depth, 3)
        
        team4 = team3.members[0].launch_att(manager, member_count=3, roles_and_presets=preset["roles"])
        self.assertEqual(team4.depth, 4)
        
        # Call dispatch_subagent tool on team4, which has depth 4 (>= max_delegation_depth 4), should be blocked
        dispatch_tool = team4.tools["dispatch_subagent"]
        res = await dispatch_tool(task="Verify logic", team_purpose="Review")
        self.assertIn("Max delegation depth (4) reached", res)

    def test_topology_tree_rendering(self):
        """Verify the topology indented tree representation prints correctly."""
        preset = self.manager.get_preset("generic")
        t1 = self.manager.create_agent_team(creator=self.root_ai, member_count=3, roles_and_presets=preset["roles"], team_purpose="Spec Review")
        t2 = t1.members[0].launch_att(self.manager, member_count=3, roles_and_presets=preset["roles"], team_purpose="Logic Verification")
        t3 = self.manager.create_agent_team(creator=self.root_ai, member_count=3, roles_and_presets=preset["roles"], team_purpose="Docs Generation")
        
        tree = self.manager.render_topology_tree()
        self.assertIn(t1.team_id, tree)
        self.assertIn(t2.team_id, tree)
        self.assertIn(t3.team_id, tree)
        self.assertIn("Spec Review", tree)
        self.assertIn("Level 1", tree)
        self.assertIn("Level 2", tree)
        self.assertIn("└── ", tree)
        self.assertIn("├── ", tree)

    async def test_real_time_status_and_topology_tree(self):
        """Verify update_team_status progress propagation to topology tree output."""
        self.manager.register_tools_context({"att_manager": self.manager})

        team = self.manager.create_agent_team(creator=self.root_ai, member_count=3)
        update_status_tool = team.tools["update_team_status"]

        # Initial checks
        self.assertEqual(team.team_purpose, "Unspecified team purpose")
        self.assertEqual(team.team_progress, "Not started")

        # Update status
        res = await update_status_tool(purpose="Refactor test suite", progress="80% done")
        self.assertIn("Successfully updated team purpose", res)
        self.assertEqual(team.team_purpose, "Refactor test suite")
        self.assertEqual(team.team_progress, "80% done")

        # Check topology representation
        tree = self.manager.render_topology_tree()
        self.assertIn("Purpose: Refactor test suite", tree)
        self.assertIn("Progress: 80% done", tree)

if __name__ == "__main__":
    unittest.main()
