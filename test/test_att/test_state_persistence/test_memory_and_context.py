from test.test_att.test_state_persistence._support import (
    ATTConfig,
    ATTManager,
    Agent,
    AgentTeam,
    AgreementDirection,
    ApprovalPrincipal,
    AsyncMock,
    CommunicationAgreement,
    CommunicationApproval,
    CommunicationApprovalStatus,
    CommunicationRequest,
    CommunicationRequestStatus,
    DocumentLibrary,
    MagicMock,
    StatePersistenceTestCase,
    json,
    os,
    route_fingerprint,
    sqlite3,
    time,
)


class TestStatePersistence(StatePersistenceTestCase):
    async def test_multi_turn_memory_format(self):
        """Verify that agent stores memory as list of dict turns, not concatenated string."""
        self.root_ai.messages.append({"role": "system", "content": "Initial System Instructions"})
        self.root_ai.messages.append({"role": "user", "content": "Hello"})
        self.root_ai.messages.append({"role": "assistant", "content": "Hi there!"})
        
        # Assert format is preserved
        self.assertEqual(len(self.root_ai.messages), 3)
        self.assertEqual(self.root_ai.messages[0]["role"], "system")
        self.assertEqual(self.root_ai.messages[1]["content"], "Hello")
        self.assertEqual(self.root_ai.messages[2]["role"], "assistant")

    async def test_context_switching_notices(self):
        """Verify that a context shift adds a SYSTEM notice warning to the agent's messages."""
        agent = Agent(name="Agent_A", role="Developer", llm_client=self.mock_react_client)
        self.manager.register_agent(agent)
        
        # Create team A
        team_a = self.manager.create_agent_team(
            creator=self.root_ai,
            preset_name="generic",
            team_purpose="Purpose A",
            member_configs={
                "HelperA": {"model": "critic"},
                "HelperB": {"model": "critic"},
            },
            existing_members=[agent],
        )
        
        # Initial ReAct step to establish first context
        await team_a.execute_react_step(agent, "Task 1", "Sys 1")
        self.assertIsNotNone(agent.last_context)
        self.assertEqual(agent.last_context["team_id"], team_a.team_id)
        
        # Create team B (context change)
        team_b = self.manager.create_agent_team(
            creator=self.root_ai,
            preset_name="generic",
            team_purpose="Purpose B",
            member_configs={
                "HelperC": {"model": "critic"},
                "HelperD": {"model": "critic"},
            },
            existing_member_ids=[agent.agent_id],
        )
        
        # Change role name to trigger switch notice
        agent.role = "Senior Developer"
        
        # Trigger next ReAct step inside team B
        await team_b.execute_react_step(agent, "Task 2", "Sys 2")
        
        # Verify context switch notice is injected as system role
        system_notices = [m for m in agent.messages if m.get("role") == "system"]
        self.assertTrue(len(system_notices) >= 1)
        notice_content = system_notices[-1]["content"]
        self.assertIn("TRANSITION NOTICE: ACTIVE TEAM UPDATE", notice_content)
        self.assertIn(team_b.team_id, notice_content)
        self.assertIn("Senior Developer", notice_content)

    async def test_agent_shared_membership(self):
        """Verify that role-neutral membership shares one Agent across teams."""
        agent = Agent(name="Shared_Agent", role="Analyst", llm_client=self.mock_react_client)
        self.manager.register_agent(agent)
        
        # Spawn team A with the existing Agent object.
        team_a = self.manager.create_agent_team(
            creator=self.root_ai,
            member_configs={
                "Helper1": {"model": "critic"},
                "Helper2": {"model": "critic"}
            },
            existing_members=[agent],
        )
        self.assertIn(agent, team_a.members)
        self.assertEqual(agent.role, "Analyst")
        
        # Execute action in Team A
        await team_a.execute_react_step(agent, "Task A", "Sys A")
        
        # Spawn team B with the same stable Agent ID.
        team_b = self.manager.create_agent_team(
            creator=self.root_ai,
            member_configs={
                "Helper3": {"model": "critic"},
                "Helper4": {"model": "critic"}
            },
            existing_member_ids=[agent.agent_id],
        )
        self.assertIn(agent, team_b.members)
        self.assertEqual(agent.role, "Analyst")
        
        # Execute action in Team B
        await team_b.execute_react_step(agent, "Task B", "Sys B")
        
        # Verify private memory length reflects turns in both teams
        self.assertTrue(len(agent.messages) > 2)
        # Verify Team B step triggered switch notice
        system_notices = [m for m in agent.messages if m.get("role") == "system"]
        self.assertTrue(any("TRANSITION NOTICE: ACTIVE TEAM UPDATE" in m["content"] for m in system_notices))
