import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from ai_team_team import ATTConfig, ATTManager, Agent
from ai_team_team.core.decision import DecisionOutcome


class MigrationClient:
    def __init__(self, approved=True):
        self.approved = approved

    async def generate(
        self,
        prompt=None,
        system_instruction=None,
        require_json=False,
        **kwargs,
    ):
        text = str(prompt)
        if "final ballot" in text or "governance principal" in str(
            system_instruction
        ):
            return json.dumps(
                {"approved": self.approved, "reason": "migration vote"}
            )
        if require_json:
            return '{"is_healthy": true, "reason": "healthy"}'
        return "Final Answer: discussed"

    def supports_output_token_limit(self):
        return True

    def supports_native_tool_calling(self):
        return False


class TestMigrationPolicies(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.old_cwd = os.getcwd()
        self.workspace = tempfile.mkdtemp(prefix="att-policies-")
        os.chdir(self.workspace)
        self.client = MigrationClient()
        self.root = Agent("Root", "Root governor", self.client)
        self.config = ATTConfig(
            migration_policy="ancestor_approval",
            workspace_root=self.workspace,
        )
        self.manager = ATTManager(self.root, self.config)
        self.manager.register_llm_client("default", self.client)

    async def asyncTearDown(self):
        await self.manager.close()
        os.chdir(self.old_cwd)
        shutil.rmtree(self.workspace, ignore_errors=True)

    async def test_permissive_migration(self):
        self.config.migration_policy = "permissive"
        first = self.manager.create_agent_team(self.root, member_count=3)
        second = self.manager.create_agent_team(self.root, member_count=3)
        child = self.manager.create_agent_team(first, member_count=3)

        approved, _ = await self.manager.negotiate_and_execute_migration(
            child, second, "move"
        )
        self.assertTrue(approved)
        self.assertIs(child.parent_team, second)

    async def test_ancestor_approval_uses_agent_teams_and_root_agent(self):
        first = self.manager.create_agent_team(self.root, member_count=3)
        second = self.manager.create_agent_team(self.root, member_count=3)
        child = self.manager.create_agent_team(first, member_count=3)

        approved, reason = await self.manager.negotiate_and_execute_migration(
            child, second, "move"
        )
        self.assertTrue(approved, reason)
        self.assertIs(child.parent_team, second)

    async def test_lineage_path_uses_every_explicit_principal(self):
        self.config.migration_policy = "lineage_path"
        first = self.manager.create_agent_team(self.root, member_count=3)
        second = self.manager.create_agent_team(self.root, member_count=3)
        target = self.manager.create_agent_team(second, member_count=3)
        child = self.manager.create_agent_team(first, member_count=3)

        decide = AsyncMock(
            return_value=DecisionOutcome("approved", "approved")
        )
        with patch.object(
            self.manager.broker.decision_provider,
            "decide_principal_boolean",
            decide,
        ):
            approved, reason = (
                await self.manager.negotiate_and_execute_migration(
                    child, target, "move across branches"
                )
            )

        self.assertTrue(approved, reason)
        self.assertEqual(
            [call.args[0].key for call in decide.await_args_list],
            [
                f"agent_team:{first.team_id}",
                f"agent_team:{target.team_id}",
                f"agent_team:{second.team_id}",
                f"agent:{self.root.agent_id}",
            ],
        )


if __name__ == "__main__":
    unittest.main()
