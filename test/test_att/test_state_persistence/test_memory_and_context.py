import os
import shutil
import sys
import tempfile
import unittest
import sqlite3
import json
import time
from unittest.mock import MagicMock, AsyncMock

# Setup paths
CURRENT_DIR = os.path.dirname(__file__)
ROOT_DIR = os.path.abspath(os.path.join(CURRENT_DIR, "..", ".."))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from ai_team_team import (
    ATTManager,
    Agent,
    AgentTeam,
    ATTConfig,
    DocumentLibrary,
    ApprovalPrincipal,
    CommunicationAgreement,
    CommunicationApproval,
    CommunicationRequest,
)
from ai_team_team.core.communication import (
    AgreementDirection,
    CommunicationApprovalStatus,
    CommunicationRequestStatus,
    route_fingerprint,
)

class TestStatePersistence(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.old_cwd = os.getcwd()
        self.tmpdir = tempfile.mkdtemp(prefix="att_persistence_test_")
        os.chdir(self.tmpdir)
        
        self.db_path = os.path.join(self.tmpdir, "att_state.db")

        # Setup mock client that will produce ReAct final answer
        self.mock_react_client = MagicMock()
        async def mock_generate(
            prompt,
            system_instruction=None,
            temperature=0.3,
            require_json=False,
            **kwargs,
        ):
            if require_json:
                return (
                    '{"is_healthy": true, '
                    '"reason": "Dialogue approved."}'
                )
            return (
                "Thought: We are doing the task.\n"
                "Final Answer: Task complete!"
            )

        self.mock_react_client.generate = mock_generate
        
        self.root_ai = Agent(name="Root_AI", role="Architect", llm_client=self.mock_react_client)
        self.manager = ATTManager(
            root_ai=self.root_ai,
            db_path=self.db_path
        )
        self.manager.register_llm_client("critic", self.mock_react_client)
        self.manager.register_tools_context({"att_manager": self.manager})

    async def asyncTearDown(self):
        await self.manager.close()
        os.chdir(self.old_cwd)
        shutil.rmtree(self.tmpdir, ignore_errors=True)

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
            team_purpose="Purpose A"
        )
        team_a.members.append(agent)
        
        # Initial ReAct step to establish first context
        await team_a.execute_react_step(agent, "Task 1", "Sys 1")
        self.assertIsNotNone(agent.last_context)
        self.assertEqual(agent.last_context["team_id"], team_a.team_id)
        
        # Create team B (context change)
        team_b = self.manager.create_agent_team(
            creator=self.root_ai,
            preset_name="generic",
            team_purpose="Purpose B"
        )
        team_b.members.append(agent)
        
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

    async def test_agent_shared_hiring(self):
        """Verify that hiring an existing agent shares its message queue across teams."""
        agent = Agent(name="Shared_Agent", role="Analyst", llm_client=self.mock_react_client)
        self.manager.register_agent(agent)
        
        # Spawn team A hiring the existing agent
        team_a = self.manager.create_agent_team(
            creator=self.root_ai,
            member_configs={
                "Analyst": {"hire_agent": "Shared_Agent"},
                "Helper1": {"model": "critic"},
                "Helper2": {"model": "critic"}
            }
        )
        self.assertIn(agent, team_a.members)
        
        # Execute action in Team A
        await team_a.execute_react_step(agent, "Task A", "Sys A")
        
        # Spawn team B hiring the same existing agent
        team_b = self.manager.create_agent_team(
            creator=self.root_ai,
            member_configs={
                "ExpertAnalyst": {"hire_agent": "Shared_Agent"},
                "Helper3": {"model": "critic"},
                "Helper4": {"model": "critic"}
            }
        )
        self.assertIn(agent, team_b.members)
        
        # Execute action in Team B
        await team_b.execute_react_step(agent, "Task B", "Sys B")
        
        # Verify private memory length reflects turns in both teams
        self.assertTrue(len(agent.messages) > 2)
        # Verify Team B step triggered switch notice
        system_notices = [m for m in agent.messages if m.get("role") == "system"]
        self.assertTrue(any("TRANSITION NOTICE: ACTIVE TEAM UPDATE" in m["content"] for m in system_notices))

