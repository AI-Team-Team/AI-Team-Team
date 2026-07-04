import os
import sys
import unittest
import asyncio
from unittest.mock import MagicMock, AsyncMock

# Setup paths
CURRENT_DIR = os.path.dirname(__file__)
ROOT_DIR = os.path.abspath(os.path.join(CURRENT_DIR, "..", ".."))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from ai_team_team import ATTManager, Agent, Tool, ATTConfig

class TestATTReactTools(unittest.IsolatedAsyncioTestCase):
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
        self.config = ATTConfig(tool_calling_mode="react")
        self.manager = ATTManager(root_ai=self.root_ai, config=self.config)

    async def test_tool_auditor_approval(self):
        """Verify the Tool Auditor registration and interception hook."""
        # Setup a custom tool and auditor
        dummy_tool_called = False
        def dummy_tool(arg1):
            nonlocal dummy_tool_called
            dummy_tool_called = True
            return f"Processed: {arg1}"

        self.manager.register_tool("query_db", "Query Database", dummy_tool)

        # 1. Register auditor that rejects
        def reject_auditor(arg1):
            return False, "Unsafe SQL pattern"
        self.manager.register_tool_auditor("query_db", reject_auditor)

        team = self.manager.create_agent_team(creator=self.root_ai, member_count=3)
        # Configure LLM Client side-effects
        self.mock_client.generate.side_effect = [
            "Thought: Let's run query.\nAction: query_db('SELECT * FROM secrets')",
            "Thought: Got output.\nFinal Answer: Done!"
        ]

        agent = team.members[0]
        final_answer = await team.execute_react_step(agent, "Query secrets", "System instructions", max_steps=2, manager=self.manager)

        self.assertFalse(dummy_tool_called)
        self.assertEqual(final_answer, "Done!")

        # 2. Register auditor that approves
        dummy_tool_called = False
        def approve_auditor(arg1):
            return True, "Safe query"
        self.manager.register_tool_auditor("query_db", approve_auditor)

        self.mock_client.generate.side_effect = [
            "Thought: Let's run query.\nAction: query_db('SELECT * FROM characters')",
            "Thought: Got output.\nFinal Answer: Done!"
        ]

        final_answer = await team.execute_react_step(agent, "Query characters", "System instructions", max_steps=2, manager=self.manager)
        self.assertTrue(dummy_tool_called)
        self.assertEqual(final_answer, "Done!")

    async def test_async_tool_auditor_approval(self):
        """Verify that asynchronous tool auditors work correctly and are awaited without crashing."""
        dummy_tool_called = False
        def dummy_tool(arg1):
            nonlocal dummy_tool_called
            dummy_tool_called = True
            return f"Processed: {arg1}"

        self.manager.register_tool("query_db_async", "Query Database Async", dummy_tool)

        # Register an async auditor that rejects if secret, approves otherwise
        async def async_auditor(arg1):
            await asyncio.sleep(0.01)
            if "secrets" in arg1:
                return False, "Unsafe SQL pattern async"
            return True, "Safe query async"
        
        self.manager.register_tool_auditor("query_db_async", async_auditor)

        team = self.manager.create_agent_team(creator=self.root_ai, member_count=3)
        agent = team.members[0]

        # Test 1: Reject case
        self.mock_client.generate.side_effect = [
            "Thought: Let's run query.\nAction: query_db_async('SELECT * FROM secrets')",
            "Thought: Got output.\nFinal Answer: Done!"
        ]
        final_answer = await team.execute_react_step(agent, "Query secrets", "System instructions", max_steps=2, manager=self.manager)
        self.assertFalse(dummy_tool_called)
        self.assertEqual(final_answer, "Done!")

        # Test 2: Approve case
        dummy_tool_called = False
        self.mock_client.generate.side_effect = [
            "Thought: Let's run query.\nAction: query_db_async('SELECT * FROM characters')",
            "Thought: Got output.\nFinal Answer: Done!"
        ]
        final_answer = await team.execute_react_step(agent, "Query characters", "System instructions", max_steps=2, manager=self.manager)
        self.assertTrue(dummy_tool_called)
        self.assertEqual(final_answer, "Done!")

    async def test_react_loop_and_tools(self):
        """Verify the ReAct execution loop parsing and tool execution."""
        dummy_tool_called = False
        def dummy_tool(arg1):
            nonlocal dummy_tool_called
            dummy_tool_called = True
            return f"Processed: {arg1}"
            
        team = self.manager.create_agent_team(creator=self.root_ai, member_count=3)
        team.tools = {
            "dummy_tool": Tool("dummy_tool", "A dummy testing tool.", dummy_tool)
        }
        
        # Configure LLM Client side-effects for successive ReAct steps
        # Step 1: LLM decides to call Action
        # Step 2: LLM produces Final Answer
        self.mock_client.generate.side_effect = [
            "Thought: Let's run the dummy tool first.\nAction: dummy_tool(hello_world)",
            "Thought: I got the observation. We are done.\nFinal Answer: Success!"
        ]
        
        agent = team.members[0]
        final_answer = await team.execute_react_step(agent, "Run the task", "System instructions", max_steps=2)
        
        self.assertTrue(dummy_tool_called)
        self.assertEqual(final_answer, "Success!")

if __name__ == "__main__":
    unittest.main()
