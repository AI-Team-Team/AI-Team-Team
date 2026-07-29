import os
import sys
import asyncio
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, AsyncMock

# Setup paths
CURRENT_DIR = os.path.dirname(__file__)
ROOT_DIR = os.path.abspath(os.path.join(CURRENT_DIR, "..", ".."))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from ai_team_team import ATTManager, Agent, AgentTeam, ATTConfig

class TestEmergencyWakeup(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.old_cwd = os.getcwd()
        self.tmpdir = tempfile.mkdtemp(prefix="att_emergency_test_")
        os.chdir(self.tmpdir)
        
        self.mock_client = MagicMock()
        self.mock_client.generate = AsyncMock(return_value="Final Answer: Done")
        self.root_ai = Agent(name="Root_AI", role="Architect", llm_client=self.mock_client)
        self.config = ATTConfig(
            enable_emergency_wakeup=True,
            emergency_discussion_rounds=1
        )
        self.manager = ATTManager(root_ai=self.root_ai, config=self.config)
        self.manager.register_tools_context({"att_manager": self.manager})

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    async def test_round_by_round_inbox_consumption(self):
        """Verify that inbox alerts are consumed and injected at the start of every round."""
        team = self.manager.create_agent_team(creator=self.root_ai, member_count=3)
        
        # We will track the prompts sent to the LLM client
        generated_prompts = []
        
        async def mock_generate(prompt, system_instruction=None, temperature=0.3, require_json=False):
            # Check if this is the supervisor audit request
            if require_json or (system_instruction and "Auditor" in system_instruction):
                return '{"is_healthy": true, "reason": "Dialogue approved."}'

            # Record the prompt (which contains the inbox alerts if injected)
            if isinstance(prompt, list):
                # It's message history, get the last user message
                generated_prompts.append(prompt[-1]["content"])
            else:
                generated_prompts.append(prompt)
            
            # Simulate a child failure alert being injected in round 1
            if len(generated_prompts) == 3: # In round 1, after all 3 agents get called
                team.receive_message({
                    "type": "child_failure_escalation",
                    "from": "Supervisor",
                    "reason": "Deadlock in sub-team AT-xxxxxx"
                })
                
            return "Final Answer: Done"

        # Bind mock generator to all agents in team
        for agent in team.members:
            agent.llm_client.generate = mock_generate

        # Run a 2-round discussion
        await self.manager.execute_team_discussion(team, prompt="Process data", rounds=2)

        # There should be 6 LLM calls (3 agents * 2 rounds)
        self.assertEqual(len(generated_prompts), 6)

        # In round 1 (first 3 prompts), there should be no child failure alerts because they hadn't been triggered yet
        for p in generated_prompts[:3]:
            self.assertNotIn("Deadlock in sub-team AT-xxxxxx", p)

        # In round 2 (next 3 prompts), the alert should be injected in the round prompt
        for p in generated_prompts[3:]:
            self.assertIn("Deadlock in sub-team AT-xxxxxx", p)

        # Verify inbox was cleared after consumption in round 2
        self.assertEqual(len(team.message_inbox), 0)

    async def test_idle_emergency_wakeup(self):
        """Verify that receiving child_failure_escalation triggers active wakeup on an idle team."""
        team = self.manager.create_agent_team(creator=self.root_ai, member_count=3)
        
        self.assertFalse(team.is_running)

        # Mock execute_emergency_discussion to verify it gets called
        self.manager.execute_emergency_discussion = AsyncMock(return_value="Resolved")

        # Simulate receiving an emergency message on the idle team
        team.receive_message({
            "type": "child_failure_escalation",
            "from": "Supervisor",
            "reason": "Emergency child error"
        })

        # Allow asyncio event loop to schedule the background task
        await asyncio.sleep(0.1)

        # Verify manager's execute_emergency_discussion was triggered
        self.manager.execute_emergency_discussion.assert_called_once_with(
            team,
            {
                "type": "child_failure_escalation",
                "from": "Supervisor",
                "reason": "Emergency child error",
            },
            skip_audit=False,
        )

    async def test_emergency_escalation_callback(self):
        """Verify that on_emergency_escalation callback is invoked on emergency signals."""
        team = self.manager.create_agent_team(creator=self.root_ai, member_count=3)
        
        # Register callback
        callback_mock = MagicMock()
        self.manager.on_emergency_escalation = callback_mock

        # Simulate message
        team.receive_message({
            "type": "escalation_spawn",
            "from": "AT-child",
            "objective": "Need high-level help"
        })

        # Verify callback invocation
        callback_mock.assert_called_once_with(
            team.team_id,
            "escalation_spawn",
            "Need high-level help"
        )

    async def test_post_discussion_leftover_wakeup(self):
        """Verify that if an alert is left in the inbox when discussion finishes, a wakeup is triggered."""
        team = self.manager.create_agent_team(creator=self.root_ai, member_count=3)
        
        # When execution concludes, if there are messages left in the inbox,
        # it should trigger execute_emergency_discussion.
        # We will mock the generate function of one agent to append a message in round 2
        async def mock_generate(prompt, system_instruction=None, temperature=0.3, require_json=False):
            if require_json:
                return (
                    '{"is_healthy": true, '
                    '"reason": "Dialogue approved."}'
                )
            if (
                system_instruction
                and "Supervisory Auditor" in system_instruction
            ):
                return "Final Answer: Audit turn complete."
            # Inject message directly into inbox to simulate it arriving late
            team.message_inbox.append({
                "type": "child_failure_escalation",
                "from": "Supervisor",
                "reason": "Late anomaly"
            })
            return "Final Answer: Done"

        for agent in team.members:
            agent.llm_client.generate = mock_generate

        self.manager.execute_emergency_discussion = AsyncMock(return_value="Handled")

        # Run discussion for 1 round
        await self.manager.execute_team_discussion(team, prompt="Do task", rounds=1)

        # Allow asyncio task scheduling
        await asyncio.sleep(0.1)

        # Verify emergency discussion was triggered after the discussion exited
        self.manager.execute_emergency_discussion.assert_called_once()
        self.assertEqual(self.manager.execute_emergency_discussion.call_args[0][0].team_id, team.team_id)
        self.assertEqual(self.manager.execute_emergency_discussion.call_args[0][1]["reason"], "Late anomaly")

    async def test_emergency_discussion_runs_successfully(self):
        """Verify execute_emergency_discussion executes a discussion with correct prompt."""
        team = self.manager.create_agent_team(creator=self.root_ai, member_count=3)
        
        self.manager.execute_team_discussion = AsyncMock(return_value="Success")

        alert = {
            "type": "child_failure_escalation",
            "from": "Supervisor",
            "reason": "Deadlock alert"
        }

        # Run emergency discussion
        await self.manager.execute_emergency_discussion(team, alert)

        # Verify execute_team_discussion was called with the emergency prompt
        self.manager.execute_team_discussion.assert_called_once()
        self.assertEqual(self.manager.execute_team_discussion.call_args[0][0].team_id, team.team_id)
        prompt_arg = self.manager.execute_team_discussion.call_args[1]["prompt"]
        self.assertIn("EMERGENCY MEETING", prompt_arg)
        self.assertIn("Deadlock alert", prompt_arg)
        self.assertEqual(self.manager.execute_team_discussion.call_args[1]["rounds"], 1)

if __name__ == "__main__":
    unittest.main()
