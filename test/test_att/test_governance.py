import os
import sys
import unittest
import re
from unittest.mock import MagicMock, AsyncMock

# Setup paths
CURRENT_DIR = os.path.dirname(__file__)
ROOT_DIR = os.path.abspath(os.path.join(CURRENT_DIR, "..", ".."))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from ai_team_team import ATTManager, Agent, ATTConfig

class TestATTGovernance(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        import tempfile, os, shutil
        self._test_old_cwd = os.getcwd()
        self._test_tmpdir = tempfile.mkdtemp(prefix="att_test_")
        os.chdir(self._test_tmpdir)
        self.addCleanup(os.chdir, self._test_old_cwd)
        self.addCleanup(shutil.rmtree, self._test_tmpdir, ignore_errors=True)

        self.mock_client = MagicMock()
        self.mock_client.generate = AsyncMock(return_value='{"is_healthy": true, "reason": "Dialogue approved."}')
        self.root_ai = Agent(name="Root_AI", role="Architect", llm_client=self.mock_client)
        self.manager = ATTManager(root_ai=self.root_ai)

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
        match = re.search(r"'(VP-[0-9a-fA-F]+)'", res_init)
        self.assertIsNotNone(match)
        proposal_id = match.group(1)

        # The proposal should be active, initiator voted Agree
        self.assertIn(proposal_id, team.proposals)
        proposal = team.proposals[proposal_id]
        self.assertEqual(proposal["status"], "active")
        self.assertIn(agent1.agent_id, proposal["votes"])
        self.assertEqual(proposal["votes"][agent1.agent_id]["vote"], "Agree")

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

    async def test_deferred_membership_voting_in_discussion(self):
        """Verify that voting approval is deferred to the end of the round during active discussion."""
        # Enable membership voting in config
        config = ATTConfig(enable_membership_voting=True)
        self.manager.config = config
        self.manager.register_tools_context({"att_manager": self.manager})

        team = self.manager.create_agent_team(creator=self.root_ai, member_count=3)
        agent1, agent2, agent3 = team.members

        from ai_team_team.tool import get_default_tools

        # Bind tools with caller_node = agent1
        tools_agent1 = get_default_tools({"att_manager": self.manager}, agent1)
        initiate_vote = tools_agent1["initiate_membership_vote"]

        # Bind tools with caller_node = agent2
        tools_agent2 = get_default_tools({"att_manager": self.manager}, agent2)
        cast_vote_agent2 = tools_agent2["cast_vote"]

        # Bind tools with caller_node = agent3
        tools_agent3 = get_default_tools({"att_manager": self.manager}, agent3)
        cast_vote_agent3 = tools_agent3["cast_vote"]

        # Initiate vote to add a member
        res_init = await initiate_vote(
            action="add",
            target="QA_Expert",
            rationale="Need QA help",
            initiator_type="individual",
            proposed_details={
                "model": "default",
                "role_description": "Performs quality checks",
                "system_instructions": "Check test suite thoroughly"
            }
        )
        match = re.search(r"'(VP-[0-9a-fA-F]+)'", res_init)
        proposal_id = match.group(1)

        # Set team.is_running = True to simulate active discussion round
        team.is_running = True

        # Agent 2 votes Agree
        await cast_vote_agent2(proposal_id=proposal_id, vote="Agree")
        
        # Agent 3 votes Agree (reaches 3/3 Agree, 2/3 threshold satisfied)
        res_vote3 = await cast_vote_agent3(proposal_id=proposal_id, vote="Agree")
        
        # Verify that it is approved but the execution is deferred
        self.assertIn("deferred", res_vote3)
        proposal = team.proposals[proposal_id]
        self.assertEqual(proposal["status"], "approved")
        # Member should NOT be added yet (still 3 members)
        self.assertEqual(len(team.members), 3)

        # Mock generator client to return simple response
        mock_responses = ["Final Answer: Dialogue resolved"]
        async def mock_gen(model_name, prompt, system_instruction=None, temperature=0.3, require_json=False):
            if require_json:
                return '{"is_healthy": true, "reason": "Dialogue approved."}'
            return mock_responses.pop(0) if mock_responses else "Final Answer: done"
        self.manager.register_generator_handler(mock_gen)

        # Now execute discussion round, which will trigger the end-of-round deferred updates
        await self.manager.execute_team_discussion(team, prompt="Start debate", rounds=1)

        # At the end of the round, the deferred execution must add the member
        self.assertEqual(len(team.members), 4)
        new_agent = [m for m in team.members if m.role == "QA_Expert"][0]
        self.assertEqual(new_agent.name, "Dynamic_QA_Expert")

if __name__ == "__main__":
    unittest.main()
