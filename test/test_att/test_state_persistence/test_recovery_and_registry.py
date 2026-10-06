import asyncio

from ai_team_team import ParentApprovalCommunicationConfig
from test.governance_client import governance_action
from test.test_att.test_state_persistence._support import (
    ATTConfig,
    ATTManager,
    Agent,
    AgentTeam,
    AsyncMock,
    DocumentLibrary,
    MagicMock,
    StatePersistenceTestCase,
    json,
    os,
    shutil,
    sqlite3,
)


class TestStatePersistence(StatePersistenceTestCase):
    async def test_experts_are_discovered_on_demand_without_global_prompt_injection(self):
        """Keep global directory records out of prompts and available through explicit queries."""
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
        
        team = self.manager.bootstrap_agent_team(
            creator=self.root_ai,
            preset_name="generic",
            team_purpose="Testing expert discovery",
            member_configs={
                "HelperA": {"model": "critic"},
                "HelperB": {"model": "critic"},
            },
            existing_members=[self.root_ai],
        )
        
        await team.execute_react_step(self.root_ai, "List experts", "System base instructions")
        
        self.assertTrue(len(captured_sys_instruction) > 0)
        sys_inst = captured_sys_instruction[0]
        self.assertNotIn("## ACTIVE REGISTERED AGENTS AVAILABLE FOR MEMBERSHIP", sys_inst)
        for person in (expert_a, expert_b):
            self.assertNotIn(person.name, sys_inst)
            self.assertNotIn(person.agent_id, sys_inst)
            self.assertNotIn(person.role, sys_inst)
            self.assertNotIn(person.role_description, sys_inst)
        for name in ("list_entities", "search_entities", "inspect_entity"):
            self.assertIn(name, sys_inst)
        page = self.manager.search_entities(["Expert_"], entity_type="agent")
        self.assertEqual([item.agent_id for item in page.items], [expert_a.agent_id, expert_b.agent_id])
        self.assertEqual(self.manager.inspect_entity("agent", expert_a.agent_id).role_description, "Handles DB queries")

    async def test_state_persistence_and_recovery(self):
        """Verify the complete serialization & deserialization pipeline."""
        self.manager.config.file_read.max_read_tokens = 321
        self.manager.config.file_read.tokenizer_fallback = "strict"
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
        
        # Build a real governed channel with accepted personal-email choices.
        original_generate = self.mock_react_client.generate

        async def governance_generate(prompt, **kwargs):
            return governance_action(prompt) or await original_generate(prompt, **kwargs)

        self.mock_react_client.generate = governance_generate
        self.manager.config.communication = ParentApprovalCommunicationConfig()
        result = await self.manager.broker.request_peer_communication(
            team_parent, team_child, team_parent.members[0].agent_id, "Persist a governed channel"
        )
        await self.manager.execute_team_discussion(team_parent, "Consider the channel.", rounds=1, skip_audit=True)
        async with asyncio.timeout(5):
            while self.manager._emergency_tasks:
                await asyncio.gather(*tuple(self.manager._emergency_tasks))
                await asyncio.sleep(0)
        self.assertEqual(self.manager.broker.communication_requests[result.request_id].status.value, "APPROVED")
        agreement = next(iter(self.manager.broker.agreements.values()))
        self.mock_react_client.generate = original_generate
        team_parent.receive_message({"from": "Child", "type": "escalation", "payload": "Help needed"})
        
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
        
        self.assertEqual(restored_parent.doc_library.read_file("readme.md"), "Parent Readme Content")
        self.assertEqual(restored_child.doc_library.read_file("child_docs/spec.txt"), "Child Spec Content")
        self.assertEqual(new_manager.config.file_read.max_read_tokens, 321)
        self.assertEqual(new_manager.config.file_read.tokenizer_fallback, "strict")
        
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

    async def test_supervision_service_uses_restored_manager_root(self):
        """The supervision service reads the manager's restored root identity."""
        await self.manager.save_state()
        self.assertTrue(os.path.exists(self.db_path))
        await self.manager.close()

        temp_root_ai = Agent(name="Temp_Root_AI", role="Architect", llm_client=self.mock_react_client)
        new_manager = ATTManager(
            root_ai=temp_root_ai,
            db_path=self.db_path
        )
        new_manager.register_llm_client("critic", self.mock_react_client)
        self.assertIs(new_manager.supervisor.manager.root_ai, temp_root_ai)

        await new_manager.load_state(self.db_path)

        self.assertIsNot(new_manager.supervisor.manager.root_ai, temp_root_ai)
        self.assertIs(new_manager.supervisor.manager.root_ai, new_manager.root_ai)
        self.assertEqual(new_manager.root_ai.name, "Root_AI")
        await new_manager.close()
