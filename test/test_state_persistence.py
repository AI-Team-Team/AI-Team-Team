import os
import shutil
import sys
import tempfile
import unittest
import sqlite3
import json
from unittest.mock import MagicMock, AsyncMock

# Setup paths
CURRENT_DIR = os.path.dirname(__file__)
ROOT_DIR = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from ai_team_team import ATTManager, Agent, AgentTeam, ATTConfig, DocumentLibrary

class TestStatePersistence(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.old_cwd = os.getcwd()
        self.tmpdir = tempfile.mkdtemp(prefix="att_persistence_test_")
        os.chdir(self.tmpdir)
        
        self.db_path = os.path.join(self.tmpdir, "att_state.db")
        
        # Setup mock critic client
        self.mock_critic = MagicMock()
        self.mock_critic.generate = AsyncMock(
            return_value='{"approved": true, "reason": "Arbitration approved."}'
        )
        
        # Setup mock client that will produce ReAct final answer
        self.mock_react_client = MagicMock()
        self.mock_react_client.generate = AsyncMock(
            return_value='Thought: We are doing the task.\nFinal Answer: Task complete!'
        )
        
        self.root_ai = Agent(name="Root_AI", role="Architect", llm_client=self.mock_react_client)
        self.manager = ATTManager(
            root_ai=self.root_ai,
            critic_client=self.mock_critic,
            db_path=self.db_path
        )
        self.manager.register_tools_context({"att_manager": self.manager})

    def tearDown(self):
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
        self.assertIn("SYSTEM NOTICE: CONTEXT SWITCH", notice_content)
        self.assertIn(team_b.team_id, notice_content)
        self.assertIn("Senior Developer", notice_content)

    async def test_agent_shared_hiring(self):
        """Verify that hiring an existing agent shares its message queue across teams."""
        agent = Agent(name="Shared_Agent", role="Analyst", llm_client=self.mock_react_client)
        self.manager.agents[agent.name] = agent
        
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
        self.assertTrue(any("SYSTEM NOTICE: CONTEXT SWITCH" in m["content"] for m in system_notices))

    async def test_state_persistence_and_recovery(self):
        """Verify the complete serialization & deserialization pipeline."""
        # 1. Create a deep lineage structure
        team_parent = self.manager.create_agent_team(
            creator=self.root_ai,
            team_purpose="Parent Team Goal",
            preset_name="generic"
        )
        
        team_child = self.manager.create_agent_team(
            creator=team_parent,
            team_purpose="Child Team Goal",
            preset_name="generic"
        )
        
        # Add initial doc
        team_parent.doc_library.write_file("readme.md", "Parent Readme Content")
        team_child.doc_library.write_file("child_docs/spec.txt", "Child Spec Content")
        
        # Setup proposals & inbox & broker agreements
        team_parent.receive_message({"from": "Child", "type": "escalation", "payload": "Help needed"})
        
        # Mock broker agreement
        self.manager.broker.peer_talk_agreements.add((team_parent.team_id, team_child.team_id))
        
        # Proposal
        team_parent.proposals["prop-123"] = {
            "action": "add_member",
            "target": "CandidateAgent",
            "initiator_type": "agent",
            "initiator_name": "Root_AI",
            "rationale": "More hands needed",
            "proposed_details": {"role": "Helper"},
            "votes": {"Root_AI": {"vote": "yes", "public": True}},
            "status": "active"
        }
        
        # Modify some states to trigger auto-save
        team_parent.team_progress = "In progress"
        team_parent.communication_rules["allow_sibling_talk"] = True
        
        # Force a manual save to confirm it writes successfully
        self.manager.save_state()
        
        # Assert database file was written
        self.assertTrue(os.path.exists(self.db_path))
        
        # 2. Simulated Crash - Destruct current manager & local state
        # (We also wipe out DocLib directories physically to see if recovery rebuilds them)
        shutil.rmtree(os.path.abspath(".att_doc_libs"), ignore_errors=True)
        
        new_root_ai = Agent(name="Root_AI", role="Architect", llm_client=self.mock_react_client)
        new_manager = ATTManager(
            root_ai=new_root_ai,
            critic_client=self.mock_critic,
            db_path=self.db_path
        )
        new_manager.register_tools_context({"att_manager": new_manager})
        
        # Load state from the database
        new_manager.load_state(self.db_path)
        
        # 3. Assertions to verify recovery was absolutely lossless
        self.assertEqual(len(new_manager.teams), 2)
        self.assertIn(team_parent.team_id, new_manager.teams)
        self.assertIn(team_child.team_id, new_manager.teams)
        
        restored_parent = new_manager.teams[team_parent.team_id]
        restored_child = new_manager.teams[team_child.team_id]
        
        # Verify lineage references
        self.assertEqual(restored_child.parent_team, restored_parent)
        self.assertIn(restored_child, restored_parent.child_teams)
        
        # Verify DocLib physical files reconstruction
        self.assertIsNotNone(restored_parent.doc_library)
        self.assertIsNotNone(restored_child.doc_library)
        
        self.assertEqual(restored_parent.doc_library.read_file("readme.md"), "1: Parent Readme Content")
        self.assertEqual(restored_child.doc_library.read_file("child_docs/spec.txt"), "1: Child Spec Content")
        
        # Verify inbox & proposals & broker agreements
        self.assertEqual(len(restored_parent.message_inbox), 1)
        self.assertEqual(restored_parent.message_inbox[0]["from"], "Child")
        
        self.assertIn("prop-123", restored_parent.proposals)
        self.assertEqual(restored_parent.proposals["prop-123"]["target"], "CandidateAgent")
        self.assertEqual(restored_parent.proposals["prop-123"]["votes"]["Root_AI"]["vote"], "yes")
        
        self.assertIn((team_parent.team_id, team_child.team_id), new_manager.broker.peer_talk_agreements)
        
        self.assertEqual(restored_parent.team_progress, "In progress")
        self.assertTrue(restored_parent.communication_rules["allow_sibling_talk"])
        
        # Verify we can still run a debate on recovered manager
        debate_result = await new_manager.execute_team_discussion(restored_parent, "Continue debate topic", rounds=1)
        self.assertTrue(
            "Task complete!" in debate_result or "Arbitration approved." in debate_result,
            f"Debate result: {debate_result} did not contain expected mock outputs."
        )

if __name__ == "__main__":
    unittest.main()
