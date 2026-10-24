"""Receipt-bound attachment, cooldown, and direct-child parent loss."""

from pathlib import Path

from ai_team_team import ATTConfig, Agent
from test.governance_client import PersonalGovernanceClient, settle_governance_activity
from test.test_att.test_agent_activity._support import ActivityTestCase


class InstitutionalTopologyTests(ActivityTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.root = Agent("Governor", "Architect", PersonalGovernanceClient(native=True))
        self.manager = self.make_manager(self.root, config=ATTConfig(workspace_root=self.workspace.name,
            tool_calling_mode="native", migration_policy="permissive"))

    async def test_target_acceptance_and_own_cooldown(self):
        moving = self.manager.create_agent_team(self.root)
        target = self.manager.create_agent_team(self.root)
        self.assertTrue(moving.is_independent)
        result = await self.manager.negotiate_and_execute_migration(moving, target, "A voluntary organizational attachment.")
        self.assertEqual(result.status, "PENDING")
        self.assertIsNone(moving.parent_team)
        await settle_governance_activity(self.manager)
        self.assertEqual(self.manager.inspect_migration_request(result.request_id).status, "EXECUTED")
        self.assertIs(moving.parent_team, target)
        self.assertEqual(moving._position_revision, 2)
        self.assertEqual(len(self.records("parent_acceptances")), 1)
        refused = await self.manager.negotiate_and_execute_migration(moving, None, "Leave immediately.")
        self.assertEqual(refused.status, "DENIED")
        self.assertIn("cooldown", refused.reason)

    async def test_explicit_agent_parent_without_root_substitution(self):
        parent = self.manager.register_agent(Agent("Personal parent", "Designer", self.root.llm_client))
        moving = self.manager.create_agent_team(self.root)
        result = await self.manager.negotiate_and_execute_migration(moving, parent, "Request this person's acceptance.")
        await settle_governance_activity(self.manager)
        self.assertEqual(self.manager.inspect_migration_request(result.request_id).status, "EXECUTED")
        self.assertIsNone(moving.parent_team)
        self.assertEqual(moving.organizational_parent.principal_id, parent.agent_id)
        cases = [case for case in self.manager._governance.cases.values() if case.business_id == result.request_id]
        self.assertEqual(cases[0].voter_agent_ids, [parent.agent_id])

    async def test_parent_team_dissolution_detaches_direct_children_only(self):
        self.manager.config.max_delegation_depth = 3
        parent = self.manager.create_agent_team(self.root)
        child = self.manager.create_agent_team(self.root, parent=parent)
        grandchild = self.manager.create_agent_team(self.root, parent=child)
        await self.manager.close_team_conversation(parent.team_id)
        self.assertTrue(child.is_independent)
        self.assertIs(grandchild.parent_team, child)
        self.assertEqual(grandchild.depth, 2)
        self.assertFalse(self.records("team_position_cooldowns"))
        await settle_governance_activity(self.manager)

    async def test_retiring_actual_agent_parent_preserves_creator_and_children(self):
        parent = self.manager.register_agent(Agent("Parent", "Designer", self.root.llm_client))
        child = self.manager.create_agent_team(self.root, parent=parent)
        original_members = tuple(child.members)
        await self.manager.retire_agent(parent.agent_id)
        self.assertTrue(child.is_independent)
        self.assertIs(child.creator, self.root)
        self.assertEqual(tuple(child.members), original_members)
        self.assertEqual(parent.lifecycle_state, "archived")
        await settle_governance_activity(self.manager)

    async def test_explicit_parents_survive_schema_15_restore(self):
        path = str(Path(self.workspace.name) / "topology.sqlite")
        parent = self.manager.create_agent_team(self.root, parent=self.root)
        child = self.manager.create_agent_team(self.root, parent=parent)
        await self.manager.save_state(path)
        await self.manager.load_state(path)
        self.assertEqual(self.manager.teams[parent.team_id].organizational_parent.principal_id, self.root.agent_id)
        self.assertEqual(self.manager.teams[child.team_id].parent_team.team_id, parent.team_id)
