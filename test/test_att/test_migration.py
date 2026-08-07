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

class TestATTMigration(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        import tempfile, os, shutil
        self._test_old_cwd = os.getcwd()
        self._test_tmpdir = tempfile.mkdtemp(prefix="att_test_")
        os.chdir(self._test_tmpdir)
        self.addCleanup(os.chdir, self._test_old_cwd)
        self.addCleanup(shutil.rmtree, self._test_tmpdir, ignore_errors=True)

        self.mock_client = MagicMock()
        self.mock_client.generate = AsyncMock(return_value='{"approved": true, "reason": "Approved by Arbiter"}')
        self.root_ai = Agent(name="Root_AI", role="Architect", llm_client=self.mock_client)
        self.manager = ATTManager(root_ai=self.root_ai)

    async def test_negotiate_and_execute_migration(self):
        """Verify that team migration updates parent-child relationships, dispatches alerts, and enforces count limits."""
        # Setup tools context
        self.manager.register_tools_context({"att_manager": self.manager})
        
        preset = self.manager.get_preset("generic")
        t1 = self.manager.create_agent_team(creator=self.root_ai, member_count=3, roles_and_presets=preset["roles"], team_purpose="P1")
        c1 = t1.members[0].launch_att(self.manager, member_count=3, roles_and_presets=preset["roles"], team_purpose="Child")
        t2 = self.manager.create_agent_team(creator=self.root_ai, member_count=3, roles_and_presets=preset["roles"], team_purpose="P2")
        
        self.assertEqual(c1.parent_team, t1)
        self.assertEqual(c1.depth, 2)
        
        # Setup callback tracking
        migration_callback_args = []
        def my_migration_callback(tid, old_pid, new_pid):
            migration_callback_args.append((tid, old_pid, new_pid))
        self.manager.on_team_migration = my_migration_callback
        
        # Call migration tool
        res = await c1.tools["request_migration"](t2.team_id, "Need to align with P2 objectives")
        await self.manager.flush_callbacks()
        
        self.assertIn("Success", res)
        self.assertEqual(c1.parent_team, t2)
        self.assertEqual(c1.depth, 2)
        self.assertIn(c1, t2.child_teams)
        self.assertNotIn(c1, t1.child_teams)
        
        # Check callback
        self.assertEqual(len(migration_callback_args), 1)
        self.assertEqual(migration_callback_args[0], (c1.team_id, t1.team_id, t2.team_id))
        
        # Check inbox alerts
        t1_migration_alerts = [m for m in t1.message_inbox if m.get("type") == "migration_alert"]
        t2_migration_alerts = [m for m in t2.message_inbox if m.get("type") == "migration_alert"]
        c1_migration_alerts = [m for m in c1.message_inbox if m.get("type") == "migration_alert"]
        
        self.assertEqual(len(t1_migration_alerts), 1)
        self.assertEqual(len(t2_migration_alerts), 1)
        self.assertEqual(len(c1_migration_alerts), 1)
        
        # Verify migration limit enforcement (max limit is 1)
        res_limit = await c1.tools["request_migration"](t1.team_id, "Migrate back")
        self.assertIn("Error", res_limit)
        self.assertIn("Maximum migrations", res_limit)
        
    async def test_migration_circular_check(self):
        """Verify that circular migrations (migrating under own descendant) are blocked."""
        self.manager.register_tools_context({"att_manager": self.manager})
        
        preset = self.manager.get_preset("generic")
        t1 = self.manager.create_agent_team(creator=self.root_ai, member_count=3, roles_and_presets=preset["roles"], team_purpose="P1")
        c1 = t1.members[0].launch_att(self.manager, member_count=3, roles_and_presets=preset["roles"], team_purpose="Child")
        
        res = await t1.tools["request_migration"](c1.team_id, "Migrate parent under child")
        self.assertIn("Error", res)
        self.assertIn("would create a cycle", res)

if __name__ == "__main__":
    unittest.main()
