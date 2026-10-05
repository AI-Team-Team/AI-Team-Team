import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from ai_team_team import ATTConfig, ATTManager, Agent
from ai_team_team.core.decision import DecisionOutcome


from test.governance_client import PersonalGovernanceClient
import asyncio


class MigrationClient(PersonalGovernanceClient):
    pass



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

        result = await self.manager.negotiate_and_execute_migration(
            child, second, "move"
        )
        self.assertEqual(result.status, "EXECUTED")
        self.assertIs(child.parent_team, second)

    async def test_ancestor_approval_uses_agent_teams_and_root_agent(self):
        first = self.manager.create_agent_team(self.root, member_count=3)
        second = self.manager.create_agent_team(self.root, member_count=3)
        child = self.manager.create_agent_team(first, member_count=3)

        result = await self.manager.negotiate_and_execute_migration(
            child, second, "move"
        )
        self.assertEqual(result.status, "PENDING")
        await self.finish(result.request_id)
        self.assertIs(child.parent_team, second)

    async def test_lineage_path_uses_every_explicit_principal(self):
        self.config.migration_policy = "lineage_path"
        first = self.manager.create_agent_team(self.root, member_count=3)
        second = self.manager.create_agent_team(self.root, member_count=3)
        target = self.manager.create_agent_team(second, member_count=3)
        child = self.manager.create_agent_team(first, member_count=3)

        result = await self.manager.negotiate_and_execute_migration(child, target, "move across branches")
        await self.finish(result.request_id)
        self.assertEqual(
            [principal.key for principal in self.manager.inspect_migration_request(result.request_id).principals],
            [
                f"agent_team:{first.team_id}",
                f"agent_team:{target.team_id}",
                f"agent_team:{second.team_id}",
                f"agent:{self.root.agent_id}",
            ],
        )

    async def finish(self, request_id):
        async with asyncio.timeout(10):
            while self.manager.inspect_migration_request(request_id).status == "PENDING":
                await asyncio.sleep(0.01)
        self.assertEqual(self.manager.inspect_migration_request(request_id).status, "EXECUTED")


if __name__ == "__main__":
    unittest.main()
