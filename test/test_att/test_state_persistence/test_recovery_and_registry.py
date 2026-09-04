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
    shutil,
    sqlite3,
    time,
)


class TestStatePersistence(StatePersistenceTestCase):
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
        self.assertIn("## ACTIVE REGISTERED AGENTS AVAILABLE FOR MEMBERSHIP", sys_inst)
        self.assertIn("Expert_A", sys_inst)
        self.assertIn("Expert_B", sys_inst)
        self.assertIn(expert_a.agent_id, sys_inst)
        self.assertIn(expert_b.agent_id, sys_inst)
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
