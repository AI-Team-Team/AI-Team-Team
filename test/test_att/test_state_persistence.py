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

    async def test_memory_compression_audit(self):
        """Verify that dialogue is compressed and early turns summarized when exceeding max_turns + 2."""
        self.manager.config.enable_memory_compression = True
        self.manager.config.max_memory_turns = 4

        # Mock agent's own client to return the summary text when requested
        async def mock_agent_generate(prompt, system_instruction=None, temperature=0.3, require_json=False):
            if "Summarize the preceding execution logs" in str(prompt):
                return "This is a summary of early task executions."
            return 'Thought: We are doing the task.\nFinal Answer: Task complete!'
        self.mock_react_client.generate = mock_agent_generate

        agent = Agent(name="Compressed_Agent", role="Summarizer", llm_client=self.mock_react_client)
        self.manager.register_agent(agent)
        
        team = self.manager.create_agent_team(
            creator=self.root_ai,
            preset_name="generic",
            team_purpose="Testing compression"
        )
        team.members.append(agent)

        agent.messages = [
            {"role": "system", "content": "Initial System Instructions"},
            {"role": "user", "content": "Turn 1 request"},
            {"role": "assistant", "content": "Turn 1 answer"},
            {"role": "user", "content": "Turn 2 request"},
            {"role": "assistant", "content": "Turn 2 answer"},
            {"role": "user", "content": "Turn 3 request"},
            {"role": "assistant", "content": "Turn 3 answer"},
        ]

        await team.execute_react_step(agent, "Turn 4 request", "Sys instructions")

        system_archives = [m for m in agent.messages if "*** HISTORICAL SUMMARY ARCHIVE ***" in m.get("content", "")]
        self.assertEqual(len(system_archives), 1)
        self.assertIn("This is a summary of early task executions.", system_archives[0]["content"])
        self.assertEqual(agent.messages[0]["content"], "Initial System Instructions")

    async def test_memory_compression_prevents_tool_splitting(self):
        """Verify that memory compression slice does not split tool calls and responses."""
        self.manager.config.enable_memory_compression = True
        self.manager.config.max_memory_turns = 4

        async def mock_agent_generate(prompt, system_instruction=None, temperature=0.3, require_json=False):
            if "Summarize the preceding execution logs" in str(prompt):
                return "This is a summary of early task executions."
            return 'Thought: We are doing the task.\nFinal Answer: Task complete!'
        self.mock_react_client.generate = mock_agent_generate

        agent = Agent(name="Compressed_Agent", role="Summarizer", llm_client=self.mock_react_client)
        self.manager.register_agent(agent)
        team = self.manager.create_agent_team(
            creator=self.root_ai,
            preset_name="generic",
            team_purpose="Testing compression"
        )
        team.members.append(agent)

        agent.messages = [
            {"role": "system", "content": "Initial System Instructions"},
            {"role": "user", "content": "Turn 1 request"},
            {"role": "assistant", "content": "Turn 1 answer"},
            {"role": "user", "content": "Turn 2 request"},
            {"role": "assistant", "content": "Turn 2 answer", "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "call_1", "name": "read_file", "content": "File content"},
            {"role": "assistant", "content": "Turn 3 answer"},
            {"role": "user", "content": "Turn 4 request"},
        ]

        await team.execute_react_step(agent, "Turn 5 request", "Sys instructions")

        self.assertEqual(agent.messages[2]["role"], "assistant")
        self.assertIn("tool_calls", agent.messages[2])
        self.assertEqual(agent.messages[3]["role"], "tool")
        self.assertEqual(agent.messages[3]["tool_call_id"], "call_1")

    async def test_global_expert_listing(self):
        """Verify that all global experts are injected into the agent's identity profile header."""
        expert_a = Agent(
            name="Expert_A",
            role="Database Analyst",
            role_description="Handles DB queries",
            llm_client=self.mock_react_client,
        )
        expert_b = Agent(
            name="Expert_B",
            role="Security Auditor",
            role_description="Inspects vulnerabilities",
            llm_client=self.mock_react_client,
        )
        
        self.manager.register_agent(expert_a)
        self.manager.register_agent(expert_b)
        
        captured_sys_instruction = []
        async def mock_generate(prompt, system_instruction=None, temperature=0.3, require_json=False):
            captured_sys_instruction.append(system_instruction)
            return 'Final Answer: Done'
        
        self.mock_react_client.generate = mock_generate
        
        team = self.manager.create_agent_team(
            creator=self.root_ai,
            preset_name="generic",
            team_purpose="Testing expert discovery"
        )
        team.members.append(self.root_ai)
        
        await team.execute_react_step(self.root_ai, "List experts", "System base instructions")
        
        self.assertTrue(len(captured_sys_instruction) > 0)
        sys_inst = captured_sys_instruction[0]
        self.assertIn("## GLOBAL EXPERTS AVAILABLE FOR HIRE", sys_inst)
        self.assertIn("Expert_A", sys_inst)
        self.assertIn("Expert_B", sys_inst)
        self.assertIn("Database Analyst", sys_inst)
        self.assertIn("Handles DB queries", sys_inst)

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
        
        principal = ApprovalPrincipal(
            kind="agent", principal_id=self.root_ai.agent_id
        )
        resolved_at = time.time()
        request = CommunicationRequest(
            sender_team_id=team_parent.team_id,
            recipient_team_id=team_child.team_id,
            initiated_by_agent_id=self.root_ai.agent_id,
            rationale="Persist a governed channel",
            direction=AgreementDirection.BIDIRECTIONAL,
            policy_snapshot={
                "policy": "parent_approval",
                "request_delivery": "queue",
                "direction": "bidirectional",
            },
            approval_principals=[principal],
            route_fingerprint=route_fingerprint([principal]),
            status=CommunicationRequestStatus.APPROVED,
            resolved_at=resolved_at,
        )
        approval = CommunicationApproval(
            request_id=request.request_id,
            principal=principal,
            sequence=0,
            status=CommunicationApprovalStatus.APPROVED,
            resolved_at=resolved_at,
        )
        agreement = CommunicationAgreement(
            source_team_id=team_parent.team_id,
            target_team_id=team_child.team_id,
            direction=AgreementDirection.BIDIRECTIONAL,
            created_from_request_id=request.request_id,
            policy_snapshot=request.policy_snapshot,
        )
        self.manager.broker.communication_requests[request.request_id] = request
        self.manager.broker.communication_approvals[approval.key] = approval
        self.manager.broker.agreements[agreement.agreement_id] = agreement
        
        # Proposal
        team_parent.proposals["prop-123"] = {
            "action": "add",
            "target": "CandidateAgent",
            "initiator_type": "individual",
            "initiator_name": "Root_AI",
            "initiator_agent_id": self.root_ai.agent_id,
            "rationale": "More hands needed",
            "proposed_details": {"model": "critic"},
            "votes": {
                self.root_ai.agent_id: {
                    "vote": "Agree",
                    "public": True,
                    "rationale": "More hands needed",
                }
            },
            "status": "active"
        }
        
        # Modify some states to trigger auto-save
        team_parent.team_progress = "In progress"
        
        # Force a manual save to confirm it writes successfully
        await self.manager.save_state()
        
        # Assert database file was written
        self.assertTrue(os.path.exists(self.db_path))
        
        # 2. Simulated Crash - Destruct current manager & local state
        # (We also wipe out DocLib directories physically to see if recovery rebuilds them)
        shutil.rmtree(os.path.abspath(".att_doc_libs"), ignore_errors=True)
        await self.manager.close()
        
        new_root_ai = Agent(name="Root_AI", role="Architect", llm_client=self.mock_react_client)
        new_manager = ATTManager(
            root_ai=new_root_ai,
            db_path=self.db_path
        )
        new_manager.register_llm_client("critic", self.mock_react_client)
        new_manager.register_tools_context({"att_manager": new_manager})
        
        # Load state from the database
        await new_manager.load_state(self.db_path)
        
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
        self.assertEqual(
            restored_parent.proposals["prop-123"]["votes"][
                self.root_ai.agent_id
            ]["vote"],
            "Agree",
        )
        
        self.assertIn(agreement.agreement_id, new_manager.broker.agreements)
        
        self.assertEqual(restored_parent.team_progress, "In progress")
        
        # Verify we can still run a debate on recovered manager
        debate_result = await new_manager.execute_team_discussion(restored_parent, "Continue debate topic", rounds=1)
        self.assertTrue(
            "Task complete!" in debate_result or "Arbitration approved." in debate_result,
            f"Debate result: {debate_result} did not contain expected mock outputs."
        )
        await new_manager.close()

    async def test_supervisor_reference_sync_on_load_state(self):
        """Verify that SupervisoryTeam.root_ai reference is updated to the newly loaded root_ai in load_state."""
        await self.manager.save_state()
        self.assertTrue(os.path.exists(self.db_path))
        await self.manager.close()

        temp_root_ai = Agent(name="Temp_Root_AI", role="Architect", llm_client=self.mock_react_client)
        new_manager = ATTManager(
            root_ai=temp_root_ai,
            db_path=self.db_path
        )
        new_manager.register_llm_client("critic", self.mock_react_client)
        self.assertIs(new_manager.supervisor.root_ai, temp_root_ai)

        await new_manager.load_state(self.db_path)

        self.assertIsNot(new_manager.supervisor.root_ai, temp_root_ai)
        self.assertIs(new_manager.supervisor.root_ai, new_manager.root_ai)
        self.assertEqual(new_manager.root_ai.name, "Root_AI")
        await new_manager.close()

if __name__ == "__main__":
    unittest.main()
