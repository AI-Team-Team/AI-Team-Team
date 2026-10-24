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

from ai_team_team import ATTConfig, ATTManager, Agent, Tool
from ai_team_team.core.manager.activity.values import ModelUnavailable
from test.personal_activity import interact_and_idle

class TestLexicalRetry(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        import tempfile, os, shutil
        self._test_old_cwd = os.getcwd()
        self._test_tmpdir = tempfile.mkdtemp(prefix="att_test_")
        os.chdir(self._test_tmpdir)
        self.addCleanup(shutil.rmtree, self._test_tmpdir, ignore_errors=True)
        self.addCleanup(os.chdir, self._test_old_cwd)

        self.mock_client = MagicMock()
        self.mock_client.generate = AsyncMock(return_value='{"is_healthy": true, "reason": "Approved"}')
        self.root_ai = Agent(name="Root_AI", role="Architect", llm_client=self.mock_client)
        self.config = ATTConfig(tool_calling_mode="react")
        self.manager = ATTManager(root_ai=self.root_ai, config=self.config, persistence_mode="volatile")
        self.addAsyncCleanup(self.manager.close)

    async def test_lexical_argument_parsing_with_commas(self):
        """Verify that tool arguments containing commas inside quotes are parsed correctly."""
        received_args = []
        received_kwargs = {}

        def mock_tool(
            sql: str | None = None,
            limit: int | None = None,
            configs: dict[str, dict[str, str]] | None = None,
        ):
            nonlocal received_args, received_kwargs
            received_args = []
            received_kwargs = {
                key: value
                for key, value in {
                    "sql": sql,
                    "limit": limit,
                    "configs": configs,
                }.items()
                if value is not None
            }
            return "Success"

        team = self.manager.create_agent_team(parent=self.root_ai, creator=self.root_ai, member_count=3)
        team.tools = {
            "query_db": Tool("query_db", "Query DB", mock_tool)
        }

        # 1. Test keyword argument with comma
        self.mock_client.generate.side_effect = [
            'Thought: Run tool.\nAction: query_db(sql="SELECT name, age FROM users", limit=5)',
            'Final Answer: Done',
            "Action: set_activity_intent(intent={'kind': 'idle'})"
        ]
        agent = team.members[0]
        await interact_and_idle(self.manager, agent, "run", team=team)
        self.assertEqual(received_kwargs, {"sql": "SELECT name, age FROM users", "limit": 5})
        self.assertEqual(received_args, [])

        # 2. Test nested dict argument with commas
        self.mock_client.generate.side_effect = [
            'Thought: Run tool.\nAction: query_db(configs={"Planner": {"model": "default"}, "Writer": {"model": "default"}})',
            'Final Answer: Done',
            "Action: set_activity_intent(intent={'kind': 'idle'})"
        ]
        await interact_and_idle(self.manager, agent, "run", team=team)
        self.assertEqual(received_kwargs, {
            "configs": {
                "Planner": {"model": "default"},
                "Writer": {"model": "default"}
            }
        })

    async def test_configurable_typed_provider_retry_succeeds(self):
        calls = 0

        class FlakyClient:
            async def generate(self, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise ConnectionError("Transient API error")
                return "Final Answer: Worked after retry" if calls == 2 else "Action: set_activity_intent(intent={'kind': 'idle'})"

        client = FlakyClient()
        config = ATTConfig(workspace_root=self._test_tmpdir, tool_calling_mode="react")
        config.activity.llm.max_retries = 3
        config.activity.llm.backoff_base_seconds = 0.01
        manager = ATTManager(Agent("RetryRoot", "Architect", client), config, persistence_mode="volatile")
        manager.register_llm_client("flaky", client)
        self.addAsyncCleanup(manager.close)
        result = await interact_and_idle(manager, manager.root_ai, "Continue.")
        self.assertEqual(result.answer, "Worked after retry")
        self.assertEqual(calls, 3)
        requests = [row for row in manager._records.snapshot() if row.table_name == "model_requests"]
        self.assertEqual([row.values["outcome"] for row in requests], ["failed", "completed", "completed"])

    async def test_permanent_provider_failure_does_not_blame_or_replace_the_person(self):
        calls = 0

        class DeadClient:
            async def generate(self, **kwargs):
                nonlocal calls
                calls += 1
                raise ValueError("Provider configuration requires repair.")

        client = DeadClient()
        manager = ATTManager(Agent("Unavailable", "Researcher", client),
            ATTConfig(workspace_root=self._test_tmpdir), persistence_mode="volatile")
        manager.register_llm_client("unavailable", client)
        self.addAsyncCleanup(manager.close)
        person = manager.root_ai
        before = person.agent_id, person.private_doc_library_id, person.llm_client
        with self.assertRaises(ModelUnavailable):
            await manager.execute_agent_interaction(person, "Continue.")
        self.assertEqual(calls, 1)
        self.assertEqual((person.agent_id, person.private_doc_library_id, person.llm_client), before)
        self.assertFalse(any(row.table_name in {"audit_runs", "health_incidents"}
            for row in manager._records.snapshot()))

    async def test_robust_action_parser(self):
        """Verify that XML-style actions, Markdown fences, and multiline parameter blocks are parsed correctly."""
        received_args = []
        received_kwargs = {}

        def mock_tool(sql_command: str, limit: int | None = None):
            nonlocal received_args, received_kwargs
            received_args = []
            received_kwargs = {
                "sql_command": sql_command,
                **({"limit": limit} if limit is not None else {}),
            }
            return "Success"

        team = self.manager.create_agent_team(parent=self.root_ai, creator=self.root_ai, member_count=3)
        team.tools = {
            "query_db": Tool("query_db", "Query DB", mock_tool)
        }
        agent = team.members[0]

        # 1. XML-style Action tag
        received_args, received_kwargs = [], {}
        self.mock_client.generate.side_effect = [
            '<action name="query_db">\nsql_command="SELECT * FROM characters", limit=10\n</action>',
            'Final Answer: Done',
            "Action: set_activity_intent(intent={'kind': 'idle'})"
        ]
        await interact_and_idle(self.manager, agent, "run", team=team)
        self.assertEqual(received_kwargs, {"sql_command": "SELECT * FROM characters", "limit": 10})

        # 2. Markdown Code Block Fences
        received_args, received_kwargs = [], {}
        self.mock_client.generate.side_effect = [
            'Action: ```python\nquery_db(sql_command="SELECT * FROM characters")\n```',
            'Final Answer: Done',
            "Action: set_activity_intent(intent={'kind': 'idle'})"
        ]
        await interact_and_idle(self.manager, agent, "run", team=team)
        self.assertEqual(received_kwargs, {"sql_command": "SELECT * FROM characters"})

        # 3. Multiline Argument Block
        received_args, received_kwargs = [], {}
        self.mock_client.generate.side_effect = [
            'Action: query_db(\n  sql_command="SELECT * FROM characters",\n  limit=5\n)',
            'Final Answer: Done',
            "Action: set_activity_intent(intent={'kind': 'idle'})"
        ]
        await interact_and_idle(self.manager, agent, "run", team=team)
        self.assertEqual(received_kwargs, {"sql_command": "SELECT * FROM characters", "limit": 5})

    async def test_quoted_argument_parsing_with_commas(self):
        """Verify that quoted tool arguments may contain commas."""
        received_args = []
        received_kwargs = {}

        def mock_tool(sql_command: str, limit: int | None = None):
            nonlocal received_args, received_kwargs
            received_args = (
                [sql_command, limit] if limit is not None else [sql_command]
            )
            received_kwargs = {
                "sql_command": sql_command,
                **({"limit": limit} if limit is not None else {}),
            }
            return "Success"

        team = self.manager.create_agent_team(parent=self.root_ai, creator=self.root_ai, member_count=3)
        team.tools = {
            "query_db": Tool("query_db", "Query DB", mock_tool)
        }
        agent = team.members[0]

        # 1. Quoted keyword argument with comma
        self.mock_client.generate.side_effect = [
            'Thought: Run tool.\nAction: query_db(sql_command="SELECT name, status FROM users", limit=10)',
            'Final Answer: Done',
            "Action: set_activity_intent(intent={'kind': 'idle'})"
        ]
        await interact_and_idle(self.manager, agent, "run", team=team)
        self.assertEqual(received_kwargs, {"sql_command": "SELECT name, status FROM users", "limit": 10})

        # 2. Quoted positional argument with comma
        received_args, received_kwargs = [], {}
        self.mock_client.generate.side_effect = [
            'Thought: Run tool.\nAction: query_db("SELECT name, status FROM users", 5)',
            'Final Answer: Done',
            "Action: set_activity_intent(intent={'kind': 'idle'})"
        ]
        await interact_and_idle(self.manager, agent, "run", team=team)
        self.assertEqual(received_args, ["SELECT name, status FROM users", 5])

if __name__ == "__main__":
    unittest.main()
