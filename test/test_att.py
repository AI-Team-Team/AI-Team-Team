import os
import sys
import unittest
from unittest.mock import MagicMock

# Setup paths
CURRENT_DIR = os.path.dirname(__file__)
ROOT_DIR = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from ai_team_team import ATTManager, Agent, AgentTeam, Tool, ATTConfig

class TestATT(unittest.TestCase):
    def setUp(self):
        self.mock_client = MagicMock()
        # Mock generate to return a JSON payload for audit and basic responses for debate
        self.mock_client.generate.return_value = '{"is_healthy": true, "reason": "Dialogue approved."}'
        
        self.root_ai = Agent(name="Root_AI", role="Architect", llm_client=self.mock_client)
        self.manager = ATTManager(root_ai=self.root_ai, critic_client=self.mock_client)

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

    def test_sibling_communication_negotiation(self):
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
        allowed = self.manager.broker.negotiate_communication(c1, c2)
        self.assertFalse(allowed)
        
        # Enable sibling talk
        parent_team.communication_rules["allow_sibling_talk"] = True
        allowed = self.manager.broker.negotiate_communication(c1, c2)
        self.assertTrue(allowed)

    def test_tool_auditor_approval(self):
        """Verify the Tool Auditor registration and interception hook."""
        # Setup a custom tool and auditor
        dummy_tool_called = False
        def dummy_tool(arg1):
            nonlocal dummy_tool_called
            dummy_tool_called = True
            return f"Processed: {arg1}"

        self.manager.register_tool("query_db", "Query Database", dummy_tool)

        # 1. Register auditor that rejects
        def reject_auditor(arg1):
            return False, "Unsafe SQL pattern"
        self.manager.register_tool_auditor("query_db", reject_auditor)

        team = self.manager.create_agent_team(creator=self.root_ai, member_count=3)
        # Configure LLM Client side-effects
        self.mock_client.generate.side_effect = [
            "Thought: Let's run query.\nAction: query_db(SELECT * FROM secrets)",
            "Thought: Got output.\nFinal Answer: Done!"
        ]

        agent = team.members[0]
        final_answer = team.execute_react_step(agent, "Query secrets", "System instructions", max_steps=2, manager=self.manager)

        self.assertFalse(dummy_tool_called)
        self.assertEqual(final_answer, "Done!")

        # 2. Register auditor that approves
        dummy_tool_called = False
        def approve_auditor(arg1):
            return True, "Safe query"
        self.manager.register_tool_auditor("query_db", approve_auditor)

        self.mock_client.generate.side_effect = [
            "Thought: Let's run query.\nAction: query_db(SELECT * FROM characters)",
            "Thought: Got output.\nFinal Answer: Done!"
        ]

        final_answer = team.execute_react_step(agent, "Query characters", "System instructions", max_steps=2, manager=self.manager)
        self.assertTrue(dummy_tool_called)
        self.assertEqual(final_answer, "Done!")

    def test_supervisory_team_escalation_protocol(self):
        """Verify that the 3-AI Supervisory Team scales up the lineage when a parent is also broken."""
        # Setup failed child team
        parent_team = self.manager.create_agent_team(creator=self.root_ai, member_count=3)
        child_team = self.manager.create_agent_team(creator=parent_team, member_count=3)
        
        # Configure critic mock to return unhealthy audit response
        self.mock_client.generate.return_value = '{"is_healthy": false, "reason": "Anomaly found."}'
        
        # Trigger audit and escalation check
        self.manager.supervisor.report_anomaly(child_team, "Deadlock", self.manager)
        
        # We verify that both child_team and parent_team are registered as having failure logs
        self.assertTrue(len(self.manager.supervisor.auditors) == 3)

    def test_react_loop_and_tools(self):
        """Verify the ReAct execution loop parsing and tool execution."""
        dummy_tool_called = False
        def dummy_tool(arg1):
            nonlocal dummy_tool_called
            dummy_tool_called = True
            return f"Processed: {arg1}"
            
        team = self.manager.create_agent_team(creator=self.root_ai, member_count=3)
        team.tools = {
            "dummy_tool": Tool("dummy_tool", "A dummy testing tool.", dummy_tool)
        }
        
        # Configure LLM Client side-effects for successive ReAct steps
        # Step 1: LLM decides to call Action
        # Step 2: LLM produces Final Answer
        self.mock_client.generate.side_effect = [
            "Thought: Let's run the dummy tool first.\nAction: dummy_tool(hello_world)",
            "Thought: I got the observation. We are done.\nFinal Answer: Success!"
        ]
        
        agent = team.members[0]
        final_answer = team.execute_react_step(agent, "Run the task", "System instructions", max_steps=2)
        
        self.assertTrue(dummy_tool_called)
        self.assertEqual(final_answer, "Success!")

    def test_sibling_talk_permission_tool(self):
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
        res = set_sibling_tool(child_team.team_id, True)
        self.assertTrue("Error" in res)
        self.assertFalse(child_team.communication_rules["allow_sibling_talk"])
        
        # 2. Parent team grants child_team sibling talk -> succeeds
        set_sibling_tool = parent_team.tools["set_sibling_talk"]
        res = set_sibling_tool(child_team.team_id, True)
        self.assertTrue("Successfully" in res)
        self.assertTrue(child_team.communication_rules["allow_sibling_talk"])

    def test_discussion_inbox_alerts_injection(self):
        """Verify that inbox messages are prepended to discussion prompts."""
        team = self.manager.create_agent_team(creator=self.root_ai, member_count=3)
        team.receive_message({"from": "Supervisor", "reason": "Anomaly in chapter 1"})
        
        # We mock execute_react_step to verify that prompt contains the inbox signal
        observed_prompt = ""
        def mock_execute_react_step(agent, prompt, system_instruction, max_steps=5, manager=None):
            nonlocal observed_prompt
            observed_prompt = prompt
            return "Mocked Answer"
            
        team.execute_react_step = mock_execute_react_step
        self.manager.execute_team_discussion(team, "Start debate", rounds=1)
        
        self.assertIn("UNRESOLVED INBOX ALERTS & ESCALATIONS", observed_prompt)
        self.assertIn("Anomaly in chapter 1", observed_prompt)
        # Message inbox should be cleared after discussion
        self.assertEqual(len(team.message_inbox), 0)

    def test_callbacks_and_logging_propagation(self):
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
        self.manager.execute_team_discussion(team, "Task description", rounds=1)

        # Status changes should be logged
        self.assertTrue(len(status_changes) > 0)
        # Activities should contain Final Answer
        self.assertTrue(any(a[1] == "Final Answer" for a in activities))
        # Logs should have been appended with team ID and chapter num
        self.assertTrue(any(l[0] == team.team_id and l[3] == 100 for l in logs))

if __name__ == "__main__":
    unittest.main()
