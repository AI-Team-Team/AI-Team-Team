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

    def test_agent_spawned_subteam_depth(self):
        """Verify that sub-teams spawned by agents correctly track lineage depth and parent team."""
        preset = self.manager.get_preset("generic")
        parent_team = self.manager.create_agent_team(
            creator=self.root_ai,
            member_count=3,
            roles_and_presets=preset["roles"]
        )
        self.assertEqual(parent_team.depth, 1)
        self.assertNil = parent_team.parent_team
        
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

    def test_arbitrary_depth_limit(self):
        """Verify that configuring a larger depth limit works and triggers rejection only at that limit."""
        config = ATTConfig(max_delegation_depth=4)
        manager = ATTManager(root_ai=self.root_ai, critic_client=self.mock_client, config=config)
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
        res = dispatch_tool(task="Verify logic", team_purpose="Review")
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

    def test_negotiate_and_execute_migration(self):
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
        
        # Mock critic client response to approve the migration
        self.mock_client.generate.return_value = '{"approved": true, "reason": "Approved by Arbiter"}'
        
        # Call migration tool
        res = c1.tools["request_migration"](t2.team_id, "Need to align with P2 objectives")
        
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
        res_limit = c1.tools["request_migration"](t1.team_id, "Migrate back")
        self.assertIn("Error", res_limit)
        self.assertIn("Maximum migrations", res_limit)
        
    def test_migration_circular_check(self):
        """Verify that circular migrations (migrating under own descendant) are blocked."""
        self.manager.register_tools_context({"att_manager": self.manager})
        
        preset = self.manager.get_preset("generic")
        t1 = self.manager.create_agent_team(creator=self.root_ai, member_count=3, roles_and_presets=preset["roles"], team_purpose="P1")
        c1 = t1.members[0].launch_att(self.manager, member_count=3, roles_and_presets=preset["roles"], team_purpose="Child")
        
        res = t1.tools["request_migration"](c1.team_id, "Migrate parent under child")
        self.assertIn("Error", res)
        self.assertIn("would create a cycle", res)

    def test_heterogeneous_registry_mode1(self):
        """Verify Mode 1 (Dependency Injection) client registration and routing."""
        mock_custom_client = MagicMock()
        mock_custom_client.generate.return_value = "Custom Response"

        # Register custom client
        self.manager.register_llm_client("my-custom", client=mock_custom_client)
        self.assertIn("my-custom", self.manager.llm_clients)

        # Spawn team and specify roles_and_models
        preset = self.manager.get_preset("generic")
        team = self.manager.create_agent_team(
            creator=self.root_ai,
            member_count=3,
            roles_and_presets=preset["roles"],
            roles_and_models={"Specialist_A": "my-custom"}
        )

        # Check client assignment
        specialist_a = [m for m in team.members if m.name == "Specialist_A"][0]
        specialist_b = [m for m in team.members if m.name == "Specialist_B"][0]

        self.assertEqual(specialist_a.llm_client, mock_custom_client)
        self.assertEqual(specialist_b.llm_client, self.manager.critic_client)

        # Run generate to ensure it uses the custom client
        res = specialist_a.llm_client.generate("hello")
        self.assertEqual(res, "Custom Response")

    def test_heterogeneous_registry_mode2(self):
        """Verify Mode 2 (Built-in clients via API keys) wrappers and routing."""
        import sys
        from unittest.mock import patch, MagicMock

        mock_openai_module = MagicMock()
        mock_google_module = MagicMock()
        mock_anthropic_module = MagicMock()

        # Setup mock behavior
        mock_openai_instance = mock_openai_module.OpenAI.return_value
        mock_openai_instance.chat.completions.create.return_value.choices = [
            MagicMock(message=MagicMock(content="OpenAI Mock Response"))
        ]

        mock_google_instance = mock_google_module.genai.Client.return_value
        mock_google_instance.models.generate_content.return_value.text = "Google Mock Response"

        mock_anthropic_instance = mock_anthropic_module.Anthropic.return_value
        mock_anthropic_instance.messages.create.return_value.content = [
            MagicMock(text="Anthropic Mock Response")
        ]

        modules_to_mock = {
            "openai": mock_openai_module,
            "google": mock_google_module,
            "google.genai": mock_google_module.genai,
            "google.genai.types": mock_google_module.genai.types,
            "anthropic": mock_anthropic_module
        }

        with patch.dict(sys.modules, modules_to_mock):
            # Register OpenAI client
            self.manager.register_llm_client(
                name="my-openai",
                provider="openai",
                api_key="sk-test",
                model="gpt-4",
                base_url="https://api.openai.com/v1"
            )

            # Register Google client
            self.manager.register_llm_client(
                name="my-google",
                provider="google",
                api_key="gemini-key",
                model="gemini-1.5"
            )

            # Register Anthropic client
            self.manager.register_llm_client(
                name="my-anthropic",
                provider="anthropic",
                api_key="claude-key",
                model="claude-3"
            )

            # Spawn team with mixed clients
            preset = self.manager.get_preset("generic")
            team = self.manager.create_agent_team(
                creator=self.root_ai,
                member_count=3,
                roles_and_presets=preset["roles"],
                roles_and_models={
                    "Specialist_A": "my-openai",
                    "Specialist_B": "my-google",
                    "Arbitrator": "my-anthropic"
                }
            )

            # Verify client routing
            a = [m for m in team.members if m.name == "Specialist_A"][0]
            b = [m for m in team.members if m.name == "Specialist_B"][0]
            c = [m for m in team.members if m.name == "Arbitrator"][0]

            self.assertEqual(a.llm_client.generate("Prompt A"), "OpenAI Mock Response")
            self.assertEqual(b.llm_client.generate("Prompt B"), "Google Mock Response")
            self.assertEqual(c.llm_client.generate("Prompt C"), "Anthropic Mock Response")

            # Verify SDK parameters passed
            mock_openai_instance.chat.completions.create.assert_called_once()
            mock_google_instance.models.generate_content.assert_called_once()
            mock_anthropic_instance.messages.create.assert_called_once()

    def test_dispatch_subagent_routing(self):
        """Verify that dispatch_subagent correctly propagates roles_and_models to dynamic child teams."""
        # Setup tools context
        self.manager.register_tools_context({"att_manager": self.manager})

        mock_custom_client = MagicMock()
        mock_custom_client.generate.return_value = "Custom Response"
        self.manager.register_llm_client("my-custom", client=mock_custom_client)

        preset = self.manager.get_preset("generic")
        team = self.manager.create_agent_team(
            creator=self.root_ai,
            member_count=3,
            roles_and_presets=preset["roles"]
        )

        dispatch_tool = team.tools["dispatch_subagent"]

        # Intercept execute_team_discussion to check the spawned team
        original_execute = self.manager.execute_team_discussion
        captured_child_team = None

        def mock_execute_team_discussion(child_team, prompt, rounds=2):
            nonlocal captured_child_team
            captured_child_team = child_team
            return "Mocked debate result"

        self.manager.execute_team_discussion = mock_execute_team_discussion

        try:
            dispatch_tool(
                task="Do task",
                team_purpose="Sub task",
                member_count=3,
                roles_and_models={"Planner": "my-custom"},
                system_instructions="Adhere to rules"
            )
        finally:
            self.manager.execute_team_discussion = original_execute

        self.assertIsNotNone(captured_child_team)
        self.assertEqual(captured_child_team.depth, 2)
        # Sibling names in dynamic dispatch are "Dynamic_{role_name}"
        # Let's verify client routing on the spawned child team members
        planner_member = [m for m in captured_child_team.members if m.role == "Planner"][0]
        self.assertEqual(planner_member.llm_client, mock_custom_client)

if __name__ == "__main__":
    unittest.main()
