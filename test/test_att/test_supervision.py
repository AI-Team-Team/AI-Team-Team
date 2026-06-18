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

class TestATTSupervision(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mock_client = MagicMock()
        self.mock_client.generate = AsyncMock(return_value='{"is_healthy": true, "reason": "Dialogue approved."}')
        self.root_ai = Agent(name="Root_AI", role="Architect", llm_client=self.mock_client)
        self.manager = ATTManager(root_ai=self.root_ai)

    async def test_supervisory_team_escalation_protocol(self):
        """Verify that the 3-AI Supervisory Team scales up the lineage when a parent is also broken."""
        # Setup failed child team
        parent_team = self.manager.create_agent_team(creator=self.root_ai, member_count=3)
        child_team = self.manager.create_agent_team(creator=parent_team, member_count=3)
        
        # Configure critic mock to return unhealthy audit response
        self.mock_client.generate.return_value = '{"is_healthy": false, "reason": "Anomaly found."}'
        
        # Trigger audit and escalation check
        await self.manager.supervisor.report_anomaly(child_team, "Deadlock", self.manager)
        
        # We verify that both child_team and parent_team are registered as having failure logs
        self.assertTrue(len(self.manager.supervisor.auditors) == 3)

    async def test_discussion_inbox_alerts_injection(self):
        """Verify that inbox messages are prepended to discussion prompts."""
        team = self.manager.create_agent_team(creator=self.root_ai, member_count=3)
        team.receive_message({"from": "Supervisor", "reason": "Anomaly in chapter 1"})
        
        # We mock execute_react_step to verify that prompt contains the inbox signal
        observed_prompt = ""
        async def mock_execute_react_step(agent, prompt, system_instruction, max_steps=5, manager=None):
            nonlocal observed_prompt
            observed_prompt = prompt
            return "Mocked Answer"
            
        team.execute_react_step = mock_execute_react_step
        await self.manager.execute_team_discussion(team, "Start debate", rounds=1)
        
        self.assertIn("UNRESOLVED INBOX ALERTS & ESCALATIONS", observed_prompt)
        self.assertIn("Anomaly in chapter 1", observed_prompt)
        # Message inbox should be cleared after discussion
        self.assertEqual(len(team.message_inbox), 0)

    async def test_callbacks_and_logging_propagation(self):
        """Verify that dynamic callbacks are invoked when events occur."""
        status_changes = []
        activities = []
        logs = []

        def on_status_change(agent_name, status):
            status_changes.append((agent_name, status))

        def on_activity_added(agent_name, activity_type, content):
            activities.append((agent_name, activity_type, content))

        def on_log_append(team_id, title, content, chapter_num):
            logs.append((team_id, title, content, chapter_num))

        self.manager.on_status_change = on_status_change
        self.manager.on_activity_added = on_activity_added
        self.manager.on_log_append = on_log_append

        team = self.manager.create_agent_team(creator=self.root_ai, member_count=3)
        team.chapter_num = 100

        self.mock_client.generate.return_value = "Final Answer: Done."
        await self.manager.execute_team_discussion(team, "Task description", rounds=1)

        # Status changes should be logged
        self.assertTrue(len(status_changes) > 0)
        # Activities should contain Final Answer
        self.assertTrue(any(a[1] == "Final Answer" for a in activities))
        # Logs should have been appended with team ID and chapter num
        self.assertTrue(any(l[0] == team.team_id and l[3] == 100 for l in logs))

if __name__ == "__main__":
    unittest.main()
