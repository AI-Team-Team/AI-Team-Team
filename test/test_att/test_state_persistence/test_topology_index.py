"""Keep the live parent index authoritative across restore and rollback."""

import os
import tempfile
import unittest
from unittest.mock import patch

from ai_team_team import ATTConfig, ATTManager, Agent, StateRestoreError


class _UnusedClient:
    async def generate(self, **kwargs):
        raise AssertionError("Topology recovery must not invoke an LLM.")


class TopologyIndexTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        workspace = tempfile.TemporaryDirectory(prefix="att-topology-index-")
        self.addCleanup(workspace.cleanup)
        self.workspace = workspace.name
        client = _UnusedClient()
        self.manager = ATTManager(
            Agent("Root", "Coordinator", client),
            ATTConfig(
                workspace_root=self.workspace,
                migration_policy="permissive",
                max_delegation_depth=5,
            ),
        )
        self.manager.register_llm_client("default", client)
        self.addAsyncCleanup(self.manager.close)
        self.parent = self.manager.create_agent_team(self.manager.root_ai)
        self.moving = self.manager.create_agent_team(self.manager.root_ai)
        self.target = self.manager.create_agent_team(self.parent)
        self.original_index = self.manager._team_parent_map
        self.path = os.path.join(self.workspace, "state.sqlite")

    async def _migrate(self, moving, target):
        result = await self.manager.negotiate_and_execute_migration(
            moving, target, "Exercise the authoritative parent index."
        )
        self.assertEqual(result.status, "EXECUTED")

    def _assert_index(self, expected):
        self.assertIs(self.manager._team_parent_map, self.original_index)
        self.assertIs(self.manager._topology.parent_map, self.original_index)
        self.assertEqual(self.original_index, expected)

    async def test_tool_view_cannot_restore_an_obsolete_parent_after_load(self):
        descendant = self.manager.create_agent_team(self.moving)
        expected_index = dict(self.original_index)
        await self.manager.save_state(self.path)
        await self._migrate(self.moving, self.target)
        await self.manager.load_state(self.path)
        moving = self.manager.teams[self.moving.team_id]
        before = self.manager.list_entities("agent_team", end_index=999).model_dump()

        tools = self.manager.get_available_tools(moving, moving.members[0])

        self.assertIsNone(self.manager.find_parent_team(moving))
        self.assertNotIn("delegate_escalation", tools)
        self.assertEqual(
            self.manager.list_entities("agent_team", end_index=999).model_dump(), before
        )
        restored_descendant = self.manager.teams[descendant.team_id]
        self.assertIs(restored_descendant.parent_team, moving)
        self.assertIn(restored_descendant, moving.child_teams)
        self.assertEqual(restored_descendant.depth, 2)
        self._assert_index(expected_index)

    async def test_migration_after_restore_updates_the_parent_resolver(self):
        await self.manager.save_state(self.path)
        await self.manager.load_state(self.path)
        moving = self.manager.teams[self.moving.team_id]
        target = self.manager.teams[self.target.team_id]
        await self._migrate(moving, target)

        # Force a cache miss so this lookup must use the committed parent index.
        moving._parent_team = None
        moving.invalidate_depth_cache(recursive=True)
        self.assertIs(self.manager.find_parent_team(moving), target)
        self.assertIn(moving, target.child_teams)
        self.assertEqual(moving.depth, 3)
        self._assert_index(
            {self.target.team_id: self.parent.team_id, moving.team_id: target.team_id}
        )

    async def test_failed_restore_recovers_the_precommit_parent_index(self):
        await self.manager.save_state(self.path)
        await self._migrate(self.moving, self.target)
        expected_index = dict(self.original_index)
        expected_teams = dict(self.manager.teams)
        before = self.manager.list_entities("agent_team", end_index=999).model_dump()

        with (
            patch.object(
                self.manager.broker,
                "restore",
                side_effect=RuntimeError("Injected restore publication failure."),
            ),
            self.assertRaisesRegex(StateRestoreError, "Injected restore publication failure"),
        ):
            await self.manager.load_state(self.path)

        self._assert_index(expected_index)
        self.assertEqual(self.manager.teams, expected_teams)
        self.assertEqual(
            self.manager.list_entities("agent_team", end_index=999).model_dump(), before
        )
        self.moving._parent_team = None
        self.moving.invalidate_depth_cache(recursive=True)
        self.assertIs(self.manager.find_parent_team(self.moving), self.target)
        self.assertIn(self.moving, self.target.child_teams)

    async def test_failed_team_creation_restores_the_shared_index_in_place(self):
        expected_index = dict(self.original_index)
        expected_teams = dict(self.manager.teams)
        expected_children = list(self.parent.child_teams)
        managed_root = os.path.join(self.workspace, ".att_doc_libs")
        expected_directories = set(os.listdir(managed_root))
        add_child = self.parent.add_child_team

        def fail_after_parent_update(team):
            add_child(team)
            raise RuntimeError("Injected parent publication failure.")

        with (
            patch.object(self.parent, "add_child_team", side_effect=fail_after_parent_update),
            self.assertRaisesRegex(RuntimeError, "Injected parent publication failure"),
        ):
            self.manager.create_agent_team(self.parent)

        self._assert_index(expected_index)
        self.assertEqual(self.manager.teams, expected_teams)
        self.assertEqual(self.parent.child_teams, expected_children)
        self.assertEqual(set(os.listdir(managed_root)), expected_directories)
        await self._migrate(self.moving, self.target)
        self.moving._parent_team = None
        self.assertIs(self.manager.find_parent_team(self.moving), self.target)

    async def test_index_replacement_is_detached_and_accepts_its_own_index(self):
        expected_index = dict(self.original_index)
        replacement = dict(expected_index)
        self.manager._topology.replace_parent_map(replacement)
        replacement.clear()
        self._assert_index(expected_index)

        self.manager._topology.replace_parent_map(self.original_index)
        self._assert_index(expected_index)
