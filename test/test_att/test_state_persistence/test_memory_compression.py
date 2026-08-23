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

