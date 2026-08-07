import os
import sys
import unittest
from unittest.mock import MagicMock, AsyncMock

# Setup paths
CURRENT_DIR = os.path.dirname(__file__)
ROOT_DIR = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from ai_team_team import ATTConfig, ATTManager, Agent, Tool, ATTException, LLMGenerationError

class TestLexicalRetry(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        import tempfile, os, shutil
        self._test_old_cwd = os.getcwd()
        self._test_tmpdir = tempfile.mkdtemp(prefix="att_test_")
        os.chdir(self._test_tmpdir)
        self.addCleanup(os.chdir, self._test_old_cwd)
        self.addCleanup(shutil.rmtree, self._test_tmpdir, ignore_errors=True)

        self.mock_client = MagicMock()
        self.mock_client.generate = AsyncMock(return_value='{"is_healthy": true, "reason": "Approved"}')
        self.root_ai = Agent(name="Root_AI", role="Architect", llm_client=self.mock_client)
        self.config = ATTConfig(llm_max_retries=2, llm_retry_backoff_factor=0.01, tool_calling_mode="react") # fast retry for test
        self.manager = ATTManager(root_ai=self.root_ai, config=self.config)

    async def test_lexical_argument_parsing_with_commas(self):
        """Verify that tool arguments containing commas inside quotes are parsed correctly."""
        received_args = []
        received_kwargs = {}

        def mock_tool(*args, **kwargs):
            nonlocal received_args, received_kwargs
            received_args = list(args)
            received_kwargs = kwargs
            return "Success"

        team = self.manager.create_agent_team(creator=self.root_ai, member_count=3)
        team.tools = {
            "query_db": Tool("query_db", "Query DB", mock_tool)
        }

        # 1. Test keyword argument with comma
        self.mock_client.generate.side_effect = [
            'Thought: Run tool.\nAction: query_db(sql="SELECT name, age FROM users", limit=5)',
            'Final Answer: Done'
        ]
        agent = team.members[0]
        await team.execute_react_step(agent, "run", "inst", max_steps=2, manager=self.manager)
        self.assertEqual(received_kwargs, {"sql": "SELECT name, age FROM users", "limit": 5})
        self.assertEqual(received_args, [])

        # 2. Test nested dict argument with commas
        self.mock_client.generate.side_effect = [
            'Thought: Run tool.\nAction: query_db(configs={"Planner": {"model": "default"}, "Writer": {"model": "default"}})',
            'Final Answer: Done'
        ]
        await team.execute_react_step(agent, "run", "inst", max_steps=2, manager=self.manager)
        self.assertEqual(received_kwargs, {
            "configs": {
                "Planner": {"model": "default"},
                "Writer": {"model": "default"}
            }
        })

    async def test_configurable_retry_mechanism_success(self):
        """Verify that LLM client generation retries upon failure and succeeds when it eventually works."""
        call_count = 0

        class FlakyClient:
            async def generate(self, prompt, system_instruction=None, temperature=0.3, require_json=False):
                nonlocal call_count
                call_count += 1
                if call_count < 2:
                    raise ConnectionError("Transient API Error")
                if require_json:
                    return '{"is_healthy": true, "reason": "Approved"}'
                return "Final Answer: Worked after retry"

        flaky = FlakyClient()
        agent = Agent(name="FlakyAgent", role="Test", llm_client=flaky)
        self.root_ai.llm_client = flaky
        config = ATTConfig(llm_max_retries=3, llm_retry_backoff_factor=0.01, tool_calling_mode="react")
        manager = ATTManager(root_ai=self.root_ai, config=config)
        team = manager.create_agent_team(creator=self.root_ai, member_count=3)
        
        # Replace flaky agent in the team
        team.members[0] = agent

        res = await team.execute_react_step(agent, "run", "inst", max_steps=2, manager=manager)
        self.assertEqual(res, "Worked after retry")
        self.assertEqual(call_count, 2) # 1 fail + 1 success

    async def test_exception_isolation_propagation(self):
        """Verify that permanent LLM failures raise LLMGenerationError and escalate anomaly without polluting history."""
        class DeadClient:
            async def generate(self, prompt, system_instruction=None, temperature=0.3, require_json=False):
                raise RuntimeError("Permanent API Error")

        dead = DeadClient()
        agent = Agent(name="DeadAgent", role="Test", llm_client=dead)
        self.root_ai.llm_client = dead
        config = ATTConfig(llm_max_retries=2, llm_retry_backoff_factor=0.001)
        manager = ATTManager(root_ai=self.root_ai, config=config)
        team = manager.create_agent_team(creator=self.root_ai, member_count=3)
        team.members[0] = agent

        anomaly_reported = False
        original_report = manager.supervisor.report_anomaly

        async def mock_report_anomaly(failed_team, reason, mgr):
            nonlocal anomaly_reported
            anomaly_reported = True
            await original_report(failed_team, reason, mgr)

        manager.supervisor.report_anomaly = mock_report_anomaly

        with self.assertRaises(LLMGenerationError):
            await manager.execute_team_discussion(team, "run", rounds=1)

        self.assertTrue(anomaly_reported)

    async def test_robust_action_parser(self):
        """Verify that XML-style actions, Markdown fences, and multiline parameter blocks are parsed correctly."""
        received_args = []
        received_kwargs = {}

        def mock_tool(*args, **kwargs):
            nonlocal received_args, received_kwargs
            received_args = list(args)
            received_kwargs = kwargs
            return "Success"

        team = self.manager.create_agent_team(creator=self.root_ai, member_count=3)
        team.tools = {
            "query_db": Tool("query_db", "Query DB", mock_tool)
        }
        agent = team.members[0]

        # 1. XML-style Action tag
        received_args, received_kwargs = [], {}
        self.mock_client.generate.side_effect = [
            '<action name="query_db">\nsql_command="SELECT * FROM characters", limit=10\n</action>',
            'Final Answer: Done'
        ]
        await team.execute_react_step(agent, "run", "inst", max_steps=2, manager=self.manager)
        self.assertEqual(received_kwargs, {"sql_command": "SELECT * FROM characters", "limit": 10})

        # 2. Markdown Code Block Fences
        received_args, received_kwargs = [], {}
        self.mock_client.generate.side_effect = [
            'Action: ```python\nquery_db(sql_command="SELECT * FROM characters")\n```',
            'Final Answer: Done'
        ]
        await team.execute_react_step(agent, "run", "inst", max_steps=2, manager=self.manager)
        self.assertEqual(received_kwargs, {"sql_command": "SELECT * FROM characters"})

        # 3. Multiline Argument Block
        received_args, received_kwargs = [], {}
        self.mock_client.generate.side_effect = [
            'Action: query_db(\n  sql_command="SELECT * FROM characters",\n  limit=5\n)',
            'Final Answer: Done'
        ]
        await team.execute_react_step(agent, "run", "inst", max_steps=2, manager=self.manager)
        self.assertEqual(received_kwargs, {"sql_command": "SELECT * FROM characters", "limit": 5})

    async def test_unquoted_argument_parsing_with_commas(self):
        """Verify that tool arguments containing commas inside unquoted strings (like SQL) are parsed correctly."""
        received_args = []
        received_kwargs = {}

        def mock_tool(*args, **kwargs):
            nonlocal received_args, received_kwargs
            received_args = list(args)
            received_kwargs = kwargs
            return "Success"

        team = self.manager.create_agent_team(creator=self.root_ai, member_count=3)
        team.tools = {
            "query_db": Tool("query_db", "Query DB", mock_tool)
        }
        agent = team.members[0]

        # 1. Unquoted keyword argument with comma
        self.mock_client.generate.side_effect = [
            'Thought: Run tool.\nAction: query_db(sql_command="SELECT name, status FROM users", limit=10)',
            'Final Answer: Done'
        ]
        await team.execute_react_step(agent, "run", "inst", max_steps=2, manager=self.manager)
        self.assertEqual(received_kwargs, {"sql_command": "SELECT name, status FROM users", "limit": 10})

        # 2. Unquoted positional argument with comma
        received_args, received_kwargs = [], {}
        self.mock_client.generate.side_effect = [
            'Thought: Run tool.\nAction: query_db("SELECT name, status FROM users", 5)',
            'Final Answer: Done'
        ]
        await team.execute_react_step(agent, "run", "inst", max_steps=2, manager=self.manager)
        self.assertEqual(received_args, ["SELECT name, status FROM users", 5])

if __name__ == "__main__":
    unittest.main()
