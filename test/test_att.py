import os
import sys
import unittest
import asyncio
from unittest.mock import MagicMock, AsyncMock

# Setup paths
CURRENT_DIR = os.path.dirname(__file__)
ROOT_DIR = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from ai_team_team import ATTManager, Agent, AgentTeam, Tool, ATTConfig

class TestATT(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mock_client = MagicMock()
        # Mock generate as async returning a JSON payload for audit and basic responses for debate
        self.mock_client.generate = AsyncMock(return_value='{"is_healthy": true, "reason": "Dialogue approved."}')
        
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

    async def test_tool_auditor_approval(self):
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
        final_answer = await team.execute_react_step(agent, "Query secrets", "System instructions", max_steps=2, manager=self.manager)

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

        final_answer = await team.execute_react_step(agent, "Query characters", "System instructions", max_steps=2, manager=self.manager)
        self.assertTrue(dummy_tool_called)
        self.assertEqual(final_answer, "Done!")

    async def test_async_tool_auditor_approval(self):
        """Verify that asynchronous tool auditors work correctly and are awaited without crashing."""
        dummy_tool_called = False
        def dummy_tool(arg1):
            nonlocal dummy_tool_called
            dummy_tool_called = True
            return f"Processed: {arg1}"

        self.manager.register_tool("query_db_async", "Query Database Async", dummy_tool)

        # Register an async auditor that rejects if secret, approves otherwise
        async def async_auditor(arg1):
            await asyncio.sleep(0.01)
            if "secrets" in arg1:
                return False, "Unsafe SQL pattern async"
            return True, "Safe query async"
        
        self.manager.register_tool_auditor("query_db_async", async_auditor)

        team = self.manager.create_agent_team(creator=self.root_ai, member_count=3)
        agent = team.members[0]

        # Test 1: Reject case
        self.mock_client.generate.side_effect = [
            "Thought: Let's run query.\nAction: query_db_async(SELECT * FROM secrets)",
            "Thought: Got output.\nFinal Answer: Done!"
        ]
        final_answer = await team.execute_react_step(agent, "Query secrets", "System instructions", max_steps=2, manager=self.manager)
        self.assertFalse(dummy_tool_called)
        self.assertEqual(final_answer, "Done!")

        # Test 2: Approve case
        dummy_tool_called = False
        self.mock_client.generate.side_effect = [
            "Thought: Let's run query.\nAction: query_db_async(SELECT * FROM characters)",
            "Thought: Got output.\nFinal Answer: Done!"
        ]
        final_answer = await team.execute_react_step(agent, "Query characters", "System instructions", max_steps=2, manager=self.manager)
        self.assertTrue(dummy_tool_called)
        self.assertEqual(final_answer, "Done!")

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

    async def test_react_loop_and_tools(self):
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
        final_answer = await team.execute_react_step(agent, "Run the task", "System instructions", max_steps=2)
        
        self.assertTrue(dummy_tool_called)
        self.assertEqual(final_answer, "Success!")

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

    async def test_arbitrary_depth_limit(self):
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
        
        # Mock critic client response to approve the migration
        self.mock_client.generate.return_value = '{"approved": true, "reason": "Approved by Arbiter"}'
        
        # Call migration tool
        res = await c1.tools["request_migration"](t2.team_id, "Need to align with P2 objectives")
        
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

    def test_heterogeneous_registry_mode1(self):
        """Verify Mode 1 (Dependency Injection) client registration and routing."""
        mock_custom_client = MagicMock()
        mock_custom_client.generate = AsyncMock(return_value="Custom Response")

        # Register custom client directly to dictionary
        self.manager.llm_clients["my-custom"] = mock_custom_client
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

    async def test_global_generator_handler_routing(self):
        """Verify model config registration, callback handler routing, and metadata in identity prompts."""
        # 1. Register a model configuration
        self.manager.register_model("gemini", {
            "model_type": "llm",
            "model_name": "gemini-3.5-flash",
            "ai_note": "gemini-3.5-flash - A very impressive large model"
        })
        self.assertIn("gemini", self.manager.model_configs)

        # 2. Register global generator callback
        generated_requests = []
        async def my_handler(model_name, prompt, system_instruction=None, temperature=0.3, require_json=False):
            generated_requests.append({
                "model": model_name,
                "prompt": prompt,
                "system": system_instruction,
                "json": require_json
            })
            if require_json:
                return '{"is_healthy": true, "reason": "Approved"}'
            return "Final Answer: Handler Output"

        self.manager.register_generator_handler(my_handler)

        # 3. Spawn team and assign role to the model
        preset = self.manager.get_preset("generic")
        team = self.manager.create_agent_team(
            creator=self.root_ai,
            member_count=3,
            roles_and_presets=preset["roles"],
            roles_and_models={"Specialist_A": "gemini"}
        )

        specialist_a = [m for m in team.members if m.name == "Specialist_A"][0]
        
        # 4. Trigger debate step
        res = await team.execute_react_step(specialist_a, "Test Task", "System instructions", max_steps=1, manager=self.manager)
        self.assertEqual(res, "Handler Output")
        self.assertEqual(len(generated_requests), 1)
        self.assertEqual(generated_requests[0]["model"], "gemini")
        # Ensure model's ai_note is present in system instructions passed to prompt builder
        self.assertIn("gemini-3.5-flash - A very impressive large model", generated_requests[0]["system"])

        # 5. Verify critic/supervisor routing fallback
        self.manager.critic_client = None
        is_healthy, reason = await self.manager.supervisor.audit_team_dialog(team, "Dummy dialogue")
        self.assertTrue(is_healthy)
        self.assertEqual(reason, "Approved")
        self.assertEqual(len(generated_requests), 2)
        self.assertEqual(generated_requests[1]["model"], "critic")
        self.assertTrue(generated_requests[1]["json"])

    async def test_dispatch_subagent_routing(self):
        """Verify that dispatch_subagent correctly propagates roles_and_models to dynamic child teams using configuration routing."""
        # Setup tools context
        self.manager.register_tools_context({"att_manager": self.manager})

        # Register config and generator callback
        self.manager.register_model("my-custom-model", {
            "model_type": "llm",
            "model_name": "custom-real-model",
            "ai_note": "custom model note"
        })
        
        called_models = []
        async def mock_handler(model_name, prompt, system_instruction=None, temperature=0.3, require_json=False):
            called_models.append(model_name)
            if require_json:
                return '{"is_healthy": true, "reason": "Dialogue approved."}'
            return "Final Answer: ok"

        self.manager.register_generator_handler(mock_handler)

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

        async def mock_execute_team_discussion(child_team, prompt, rounds=2):
            nonlocal captured_child_team
            captured_child_team = child_team
            return "Mocked debate result"

        self.manager.execute_team_discussion = mock_execute_team_discussion

        try:
            await dispatch_tool(
                task="Do task",
                team_purpose="Sub task",
                member_configs={
                    "Planner": {"model": "my-custom-model"},
                    "Researcher": {"model": "my-custom-model"},
                    "Writer": {"model": "my-custom-model"}
                },
                system_instructions="Adhere to rules"
            )
        finally:
            self.manager.execute_team_discussion = original_execute

        self.assertIsNotNone(captured_child_team)
        self.assertEqual(captured_child_team.depth, 2)
        # Sibling names in dynamic dispatch are "Dynamic_{role_name}"
        # Let's verify client routing on the spawned child team members
        planner_member = [m for m in captured_child_team.members if m.role == "Planner"][0]
        self.assertEqual(planner_member.llm_client.model_name, "my-custom-model")
        self.assertEqual(planner_member.llm_client.handler, mock_handler)

    async def test_dispatch_subagent_dynamic_member_count_validation(self):
        """Verify dynamic subagent member count resolution and validation from member_configs."""
        self.manager.register_tools_context({"att_manager": self.manager})

        called_models = []
        async def mock_handler(model_name, prompt, system_instruction=None, temperature=0.3, require_json=False):
            called_models.append(model_name)
            if require_json:
                return '{"is_healthy": true, "reason": "Dialogue approved."}'
            return "Final Answer: ok"

        self.manager.register_generator_handler(mock_handler)

        preset = self.manager.get_preset("generic")
        team = self.manager.create_agent_team(
            creator=self.root_ai,
            member_count=3,
            roles_and_presets=preset["roles"]
        )

        dispatch_tool = team.tools["dispatch_subagent"]

        # 1. Spawn dynamic subagent with 3 dynamic roles -> success
        res = await dispatch_tool(
            task="Do task",
            team_purpose="Sub task",
            member_configs={
                "Code_Architect": {"model": "default"},
                "Security_Auditor": {"model": "default"},
                "Quality_Assurance": {"model": "default"}
            },
            system_instructions="Adhere to rules"
        )
        self.assertNotIn("Error", res)

        # 2. Spawn dynamic subagent with 2 dynamic roles -> failure (min_subagent_team_size is 3)
        res_fail = await dispatch_tool(
            task="Do task",
            team_purpose="Sub task",
            member_configs={
                "Architect": {"model": "default"},
                "Reviewer": {"model": "default"}
            },
            system_instructions="Adhere to rules"
        )
        self.assertIn("Error", res_fail)
        self.assertIn("MUST have at least 3 members", res_fail)

    async def test_member_configs_spawning_and_prompting(self):
        """Verify dynamic role prompts and ai_note prompt injection."""
        self.manager.register_tools_context({"att_manager": self.manager})
        self.manager.register_model("my-custom-model", {
            "model_type": "llm",
            "model_name": "custom-real-model",
            "ai_note": "A very impressive large model"
        })

        system_instruction_captured = None
        async def mock_handler(model_name, prompt, system_instruction=None, temperature=0.3, require_json=False):
            nonlocal system_instruction_captured
            system_instruction_captured = system_instruction
            if require_json:
                return '{"is_healthy": true, "reason": "Dialogue approved."}'
            return "Final Answer: ok"

        self.manager.register_generator_handler(mock_handler)

        # Create a child team using member_configs
        member_configs = {
            "Lead_Planner": {
                "model": "my-custom-model",
                "role_description": "Responsible for structural orchestration and task scheduling.",
                "system_instructions": "Prioritize clarity, decompose objectives, and verify sub-tasks."
            },
            "Senior_Researcher": {
                "model": "default",
                "role_description": "Responsible for factual lookup.",
                "system_instructions": "Ensure sources are reliable."
            },
            "Technical_Writer": {
                "model": "default",
                "role_description": "Responsible for drafting cohesive documents.",
                "system_instructions": "Maintain high readability."
            }
        }

        team = self.manager.create_agent_team(
            creator=self.root_ai,
            member_configs=member_configs
        )

        self.assertEqual(len(team.members), 3)
        planner = [m for m in team.members if m.role == "Lead_Planner"][0]
        self.assertEqual(planner.role_description, "Responsible for structural orchestration and task scheduling.")
        self.assertEqual(planner.system_instructions, "Prioritize clarity, decompose objectives, and verify sub-tasks.")

        # Run execute_react_step on Lead_Planner to capture system instructions
        await team.execute_react_step(planner, "Start task", "Base system instruction", max_steps=1, manager=self.manager)

        self.assertIsNotNone(system_instruction_captured)
        self.assertIn("Prioritize clarity, decompose objectives, and verify sub-tasks.", system_instruction_captured)
        self.assertIn("Responsible for structural orchestration and task scheduling.", system_instruction_captured)
        self.assertIn("my-custom-model: A very impressive large model", system_instruction_captured)

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

    async def test_parent_admin_member_tools(self):
        """Verify parent member addition/removal with size checks."""
        self.manager.register_tools_context({"att_manager": self.manager})

        # Spawn parent team A and child team B
        team_a = self.manager.create_agent_team(creator=self.root_ai, member_count=3)
        team_b = self.manager.create_agent_team(creator=team_a, member_count=3)

        add_tool = team_a.tools["add_team_member"]
        remove_tool = team_a.tools["remove_team_member"]

        # 1. Try to remove a member when size is at minimum (3) -> should fail
        res_remove_fail = await remove_tool(team_id=team_b.team_id, agent_name=team_b.members[0].name)
        self.assertIn("must maintain at least 3 members", res_remove_fail)

        # 2. Add a member -> should succeed
        res_add = await add_tool(
            team_id=team_b.team_id,
            role_name="QA_Expert",
            model_name="default",
            role_description="Performs quality checks",
            system_instructions="Check test suite thoroughly"
        )
        self.assertIn("Successfully added new member", res_add)
        self.assertEqual(len(team_b.members), 4)
        new_member = [m for m in team_b.members if m.role == "QA_Expert"][0]
        self.assertEqual(new_member.name, "Dynamic_QA_Expert")

        # 3. Remove a member now that size is 4 -> should succeed
        res_remove = await remove_tool(team_id=team_b.team_id, agent_name="Dynamic_QA_Expert")
        self.assertIn("Successfully removed member 'Dynamic_QA_Expert'", res_remove)
        self.assertEqual(len(team_b.members), 3)

        # 4. Try from a non-parent team B trying to modify itself or another non-child team -> should be blocked
        other_team = self.manager.create_agent_team(creator=self.root_ai, member_count=3)
        add_tool_other = other_team.tools["add_team_member"]
        res_unauthorized = await add_tool_other(
            team_id=team_b.team_id,
            role_name="Hacker",
            model_name="default",
            role_description="Attacks",
            system_instructions="Hack"
        )
        self.assertIn("is not the parent of child", res_unauthorized)

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

    async def test_membership_voting_system(self):
        """Verify proposal initiation, casting ballots, abstaining/skipping, automatic execution when all members vote, and retraction."""
        # Enable membership voting in config
        config = ATTConfig(enable_membership_voting=True)
        self.manager.config = config
        self.manager.register_tools_context({"att_manager": self.manager})

        team = self.manager.create_agent_team(creator=self.root_ai, member_count=3)
        agent1, agent2, agent3 = team.members

        # Settle tools context for individual agents by letting them invoke tools
        from ai_team_team.tool import get_default_tools

        # Bind tools with caller_node = agent1
        tools_agent1 = get_default_tools({"att_manager": self.manager}, agent1)
        initiate_vote = tools_agent1["initiate_membership_vote"]
        retract_vote = tools_agent1["retract_membership_vote"]
        cast_vote_agent1 = tools_agent1["cast_vote"]

        # Bind tools with caller_node = agent2
        tools_agent2 = get_default_tools({"att_manager": self.manager}, agent2)
        cast_vote_agent2 = tools_agent2["cast_vote"]
        retract_vote_agent2 = tools_agent2["retract_membership_vote"]

        # Bind tools with caller_node = agent3
        tools_agent3 = get_default_tools({"att_manager": self.manager}, agent3)
        cast_vote_agent3 = tools_agent3["cast_vote"]

        # 1. Initiate vote to add a member
        res_init = await initiate_vote(
            action="add",
            target="Tester",
            rationale="Need testing help",
            initiator_type="individual",
            proposed_details={
                "model": "default",
                "role_description": "Performs testing",
                "system_instructions": "Test everything"
            }
        )
        self.assertIn("Vote proposal", res_init)
        
        # Extract proposal ID from output (typically contains VP-<hex>)
        import re
        match = re.search(r"'(VP-[0-9a-fA-F]+)'", res_init)
        self.assertIsNotNone(match)
        proposal_id = match.group(1)

        # The proposal should be active, initiator voted Agree
        self.assertIn(proposal_id, team.proposals)
        proposal = team.proposals[proposal_id]
        self.assertEqual(proposal["status"], "active")
        self.assertIn(agent1.name, proposal["votes"])
        self.assertEqual(proposal["votes"][agent1.name]["vote"], "Agree")

        # 2. Test retraction authorization: Agent2 tries to retract Agent1's proposal -> should fail
        res_retract_fail = await retract_vote_agent2(proposal_id=proposal_id)
        self.assertIn("Error: Only the initiator", res_retract_fail)
        self.assertEqual(proposal["status"], "active")

        # 3. Test retraction by initiator -> should succeed
        res_retract_success = await retract_vote(proposal_id=proposal_id)
        self.assertIn("Successfully retracted", res_retract_success)
        self.assertEqual(proposal["status"], "retracted")

        # 4. Initiate a new proposal VP-2
        res_init2 = await initiate_vote(
            action="add",
            target="Auditor",
            rationale="Security audit",
            initiator_type="individual",
            proposed_details={
                "model": "default",
                "role_description": "Performs security audits",
                "system_instructions": "Find vulnerabilities"
            }
        )
        match2 = re.search(r"'(VP-[0-9a-fA-F]+)'", res_init2)
        proposal_id2 = match2.group(1)
        proposal2 = team.proposals[proposal_id2]

        # 5. Vote: Agent 2 votes Agree, Agent 3 votes Agree
        # This makes it 3/3 Agree. Since all members voted, it should automatically evaluate and approve the proposal
        res_vote2 = await cast_vote_agent2(proposal_id=proposal_id2, vote="Agree")
        self.assertIn("Successfully cast vote", res_vote2)
        self.assertEqual(proposal2["status"], "active") # Still 1 voter remaining (agent 3)

        res_vote3 = await cast_vote_agent3(proposal_id=proposal_id2, vote="Agree")
        self.assertIn("approved", res_vote3)
        self.assertEqual(proposal2["status"], "approved")

        # Verify that the new member is added
        self.assertEqual(len(team.members), 4)
        new_agent = [m for m in team.members if m.role == "Auditor"][0]
        self.assertEqual(new_agent.name, "Dynamic_Auditor")

        # 6. Test vote rejection: Initiate a proposal to remove the newly added member
        # This time, we want to reject it. Team now has 4 members: agent1, agent2, agent3, Dynamic_Auditor
        tools_auditor = get_default_tools({"att_manager": self.manager}, new_agent)
        cast_vote_auditor = tools_auditor["cast_vote"]

        res_init3 = await initiate_vote(
            action="remove",
            target="Dynamic_Auditor",
            rationale="Auditing complete",
            initiator_type="individual"
        )
        match3 = re.search(r"'(VP-[0-9a-fA-F]+)'", res_init3)
        proposal_id3 = match3.group(1)
        proposal3 = team.proposals[proposal_id3]

        # agent1 (initiator) voted Agree.
        # agent2, agent3, Dynamic_Auditor vote Disagree.
        await cast_vote_agent2(proposal_id=proposal_id3, vote="Disagree")
        await cast_vote_agent3(proposal_id=proposal_id3, vote="Disagree")
        res_final_vote = await cast_vote_auditor(proposal_id=proposal_id3, vote="Disagree")

        self.assertIn("rejected", res_final_vote)
        self.assertEqual(proposal3["status"], "rejected")
        # Dynamic_Auditor should still be in the team
        self.assertIn(new_agent, team.members)

if __name__ == "__main__":
    unittest.main()
