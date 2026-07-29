import os
import sys
import unittest
from unittest.mock import MagicMock, AsyncMock

# Setup paths
CURRENT_DIR = os.path.dirname(__file__)
ROOT_DIR = os.path.abspath(os.path.join(CURRENT_DIR, "..", ".."))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from ai_team_team import ATTManager, Agent, AgentTeam, ATTConfig

class TestPolicies(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        import tempfile, os, shutil
        self._test_old_cwd = os.getcwd()
        self._test_tmpdir = tempfile.mkdtemp(prefix="att_test_")
        os.chdir(self._test_tmpdir)
        self.addCleanup(os.chdir, self._test_old_cwd)
        self.addCleanup(shutil.rmtree, self._test_tmpdir, ignore_errors=True)

        self.mock_client = MagicMock()
        self.mock_client.generate = AsyncMock(
            return_value='{"approved": true, "reason": "Approved by representative."}'
        )
        self.root_ai = Agent(name="Root_AI", role="Architect", llm_client=self.mock_client)
        self.config = ATTConfig(
            communication_policy="permissive",
            migration_policy="ancestor_approval",
            min_subagent_team_size=3
        )
        self.manager = ATTManager(
            root_ai=self.root_ai,
            config=self.config
        )
        self.manager.llm_clients["critic"] = self.mock_client
        self.manager.register_tools_context({"att_manager": self.manager})

    async def test_permissive_policies(self):
        """Verify that permissive policies auto-approve communication and migration instantly."""
        self.config.communication_policy = "permissive"
        self.config.migration_policy = "permissive"

        # Create two separate team branches
        parent_a = self.manager.create_agent_team(
            creator=self.root_ai,
            member_configs={
                "A1": {"model": "critic"}, "A2": {"model": "critic"}, "A3": {"model": "critic"}
            }
        )
        parent_b = self.manager.create_agent_team(
            creator=self.root_ai,
            member_configs={
                "B1": {"model": "critic"}, "B2": {"model": "critic"}, "B3": {"model": "critic"}
            }
        )

        team_a = self.manager.create_agent_team(
            creator=parent_a,
            member_configs={
                "A1_1": {"model": "critic"}, "A1_2": {"model": "critic"}, "A1_3": {"model": "critic"}
            }
        )
        team_b = self.manager.create_agent_team(
            creator=parent_b,
            member_configs={
                "B1_1": {"model": "critic"}, "B1_2": {"model": "critic"}, "B1_3": {"model": "critic"}
            }
        )

        # 1. Permissive P2P communication tunnel
        success = await self.manager.broker.establish_peer_agreement(team_a, team_b, rationale="Friendly hello")
        self.assertTrue(success)
        self.assertIn((team_a.team_id, team_b.team_id), self.manager.broker.peer_talk_agreements)

        # 2. Permissive team migration
        # Try migrating team_a under team_b
        mig_success, reason = await self.manager.negotiate_and_execute_migration(team_a, team_b, rationale="Move under B")
        self.assertTrue(mig_success)
        self.assertEqual(team_a.parent_team, team_b)

    async def test_rule_gated_communication(self):
        """Verify that rule_gated communication evaluates symmetric rules correctly."""
        self.config.communication_policy = "rule_gated"

        # Parent team of sender
        parent_a = self.manager.create_agent_team(
            creator=self.root_ai,
            team_purpose="Parent branch A",
            member_configs={
                "PA1": {"model": "critic"}, "PA2": {"model": "critic"}, "PA3": {"model": "critic"}
            }
        )
        # Parent team of recipient
        parent_b = self.manager.create_agent_team(
            creator=self.root_ai,
            team_purpose="Parent branch B",
            member_configs={
                "PB1": {"model": "critic"}, "PB2": {"model": "critic"}, "PB3": {"model": "critic"}
            }
        )

        sender = self.manager.create_agent_team(
            creator=parent_a,
            team_purpose="Sender team",
            member_configs={
                "S1": {"model": "critic"}, "S2": {"model": "critic"}, "S3": {"model": "critic"}
            }
        )
        recipient = self.manager.create_agent_team(
            creator=parent_b,
            team_purpose="Recipient team search",
            member_configs={
                "R1": {"model": "critic"}, "R2": {"model": "critic"}, "R3": {"model": "critic"}
            }
        )

        # Set up non-symmetric rules first (should fail)
        parent_a.communication_rules["rules"] = [f"allow_team:{recipient.team_id}"]
        parent_b.communication_rules["rules"] = [] # Denies by default

        success = await self.manager.broker.establish_peer_agreement(sender, recipient, rationale="P2P attempt")
        self.assertFalse(success)

        # Now set up symmetric rules
        # parent_a allows target recipient team
        parent_a.communication_rules["rules"] = [f"allow_team:{recipient.team_id}"]
        # parent_b allows parent_a lineage
        parent_b.communication_rules["rules"] = [f"allow_parent:{parent_a.team_id}"]

        success2 = await self.manager.broker.establish_peer_agreement(sender, recipient, rationale="P2P attempt 2")
        self.assertTrue(success2)

        # Test regex purpose matching
        parent_b.communication_rules["rules"] = ["allow_purpose:.*sender.*"]
        ok_regex = await self.manager.broker.establish_peer_agreement(recipient, sender, rationale="Regex test")
        self.assertTrue(ok_regex)

    async def test_proxied_communication(self):
        """Verify that proxied communication asks parent representatives and evaluates LLM outputs."""
        self.config.communication_policy = "proxied"

        parent_a = self.manager.create_agent_team(
            creator=self.root_ai,
            member_configs={
                "PA1": {"model": "critic"}, "PA2": {"model": "critic"}, "PA3": {"model": "critic"}
            }
        )
        parent_b = self.manager.create_agent_team(
            creator=self.root_ai,
            member_configs={
                "PB1": {"model": "critic"}, "PB2": {"model": "critic"}, "PB3": {"model": "critic"}
            }
        )
        
        sender = self.manager.create_agent_team(
            creator=parent_a,
            member_configs={
                "S1": {"model": "critic"}, "S2": {"model": "critic"}, "S3": {"model": "critic"}
            }
        )
        recipient = self.manager.create_agent_team(
            creator=parent_b,
            member_configs={
                "R1": {"model": "critic"}, "R2": {"model": "critic"}, "R3": {"model": "critic"}
            }
        )

        # Case 1: Parent representatives approve
        parent_a.members[0].llm_client.generate = AsyncMock(return_value='{"approved": true, "reason": "Fine by me"}')
        parent_b.members[0].llm_client.generate = AsyncMock(return_value='{"approved": true, "reason": "Sure"}')
        
        success = await self.manager.broker.establish_peer_agreement(sender, recipient, rationale="Let's talk")
        self.assertTrue(success)

        # Case 2: One parent representative rejects
        parent_b.members[0].llm_client.generate = AsyncMock(return_value='{"approved": false, "reason": "No security check completed"}')
        # Reset agreements set to verify rejection
        self.manager.broker.peer_talk_agreements.clear()
        
        success_rejected = await self.manager.broker.establish_peer_agreement(sender, recipient, rationale="Let's talk")
        self.assertFalse(success_rejected)

    async def test_ancestor_approval_migration(self):
        """Verify that ancestor_approval migration evaluates LCA and parent team leader approvals using representative LLM clients."""
        self.config.migration_policy = "ancestor_approval"

        # Spawn parent branch 1
        branch1 = self.manager.create_agent_team(
            creator=self.root_ai,
            team_purpose="Branch 1",
            member_configs={
                "H1": {"model": "critic"}, "H2": {"model": "critic"}, "H3": {"model": "critic"}
            }
        )
        # Spawn child team under branch 1 (the one migrating)
        team = self.manager.create_agent_team(
            creator=branch1,
            team_purpose="Migrating team",
            member_configs={
                "M1": {"model": "critic"}, "M2": {"model": "critic"}, "M3": {"model": "critic"}
            }
        )
        # Spawn parent branch 2 (destination)
        branch2 = self.manager.create_agent_team(
            creator=self.root_ai,
            team_purpose="Branch 2",
            member_configs={
                "D1": {"model": "critic"}, "D2": {"model": "critic"}, "D3": {"model": "critic"}
            }
        )

        # Setup mock clients for representatives
        # LCA is Root AI (since branch1 and branch2 both have creator=Root AI)
        self.root_ai.llm_client.generate = AsyncMock(return_value='{"approved": true, "reason": "LCA approved"}')
        branch1.members[0].llm_client.generate = AsyncMock(return_value='{"approved": true, "reason": "Parent approved"}')
        branch2.members[0].llm_client.generate = AsyncMock(return_value='{"approved": true, "reason": "Dest approved"}')

        mig_success, reason = await self.manager.negotiate_and_execute_migration(team, branch2, rationale="Structural shift")
        self.assertTrue(mig_success)
        self.assertEqual(team.parent_team, branch2)

        # Case 2: Rejected by destination branch2 representative
        team2 = self.manager.create_agent_team(
            creator=branch1,
            team_purpose="Migrating team 2",
            member_configs={
                "X1": {"model": "critic"}, "X2": {"model": "critic"}, "X3": {"model": "critic"}
            }
        )
        branch2.members[0].llm_client.generate = AsyncMock(return_value='{"approved": false, "reason": "Branch 2 has too many sub-teams"}')
        
        mig_rejected, reason2 = await self.manager.negotiate_and_execute_migration(team2, branch2, rationale="Re-attempt")
        self.assertFalse(mig_rejected)
        self.assertIn("Rejected by representative", reason2)
        self.assertIn("Branch 2 has too many sub-teams", reason2)

    async def test_agent_self_summarization(self):
        """Verify that memory pruning and inbox alerts are summarized using the agent/member's own llm_client."""
        self.config.enable_memory_compression = True
        self.config.max_memory_turns = 2
        self.config.inbox_summarize_threshold_chars = 10

        agent = Agent(name="Summarizing_Agent", role="Summarizer")
        agent.llm_client = MagicMock()
        # Mock LLM response for summaries
        agent.llm_client.generate = AsyncMock(return_value="Summary paragraph content.")

        team = self.manager.create_agent_team(
            creator=self.root_ai,
            team_purpose="Pruning test team",
            member_configs={
                "Summarizer": agent,
                "Helper1": {"model": "critic"},
                "Helper2": {"model": "critic"}
            }
        )

        # 1. Memory Compression Verification
        agent.messages = [
            {"role": "system", "content": "Initial System Instructions"},
            {"role": "user", "content": "Turn 1"},
            {"role": "assistant", "content": "Ans 1"},
            {"role": "user", "content": "Turn 2"},
            {"role": "assistant", "content": "Ans 2"},
        ] # Length = 5. Limit = max_memory_turns + 2 = 4. 5 > 4, so it will prune.

        # Trigger ReAct step
        # Note: the mock client generate is captured, which returns the summary
        await team.execute_react_step(agent, "Turn 3 request", "Sys instructions")

        # The summary generated must be present in agent.messages
        system_archives = [m for m in agent.messages if "*** HISTORICAL SUMMARY ARCHIVE ***" in m.get("content", "")]
        self.assertEqual(len(system_archives), 1)
        self.assertIn("Summary paragraph content.", system_archives[0]["content"])

        # 2. Inbox Summarization Verification
        team.message_inbox = [
            {"from": "Supervisor", "reason": "Signal A is failing"},
            {"from": "Supervisor", "reason": "Signal B is failing"},
        ] # raw inbox text length will be: "- **From [Supervisor]**: Signal A is failing\n..." which exceeds 10 chars.

        # Verify executing team discussion triggers inbox summarization using team representative's client
        # Let's mock team.members[0]'s llm_client (which is Summarizing_Agent)
        agent.llm_client.generate = AsyncMock(return_value="Brief summary of supervisor failures.")
        
        # We need debate prompt to return final answer to stop discussion
        # Summarizing_Agent's generate must return final answer
        async def mock_discussion_completion(*args, **kwargs):
            prompt = kwargs.get("prompt") or args[0]
            # If it is the inbox summarization call
            if "Summarize the following system alerts" in str(prompt):
                return "Brief summary of supervisor failures."
            # Otherwise, ReAct step completion
            return "Thought: Done.\nFinal Answer: Discussion completed."
        
        agent.llm_client.generate = mock_discussion_completion

        debate_result = await self.manager.execute_team_discussion(
            team,
            "Final topic debate",
            rounds=1,
            skip_audit=True,
        )
        self.assertIn("Discussion completed", debate_result)

if __name__ == "__main__":
    unittest.main()
