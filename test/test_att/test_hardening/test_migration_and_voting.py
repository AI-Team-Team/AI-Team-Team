import asyncio
from contextlib import closing
import os
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from ai_team_team import (
    ATTConfig,
    ATTManager,
    Agent,
    AuditResult,
    AuditStatus,
    StateRestoreError,
)
from ai_team_team.database.persistence import DatabaseStore
from ai_team_team.tool import get_default_tools

class TestATTHardening(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="att_hardening_")
        self.client = MagicMock()
        self.client.generate = AsyncMock(return_value="Final Answer: Done")
        self.root = Agent("Root", "Architect", llm_client=self.client)
        self.manager = ATTManager(
            self.root,
            ATTConfig(
                max_delegation_depth=6,
                migration_policy="permissive",
                enable_membership_voting=True,
                workspace_root=self.tmpdir,
            ),
        )

    async def asyncTearDown(self):
        await self.manager.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    async def test_migration_invalidates_all_descendant_depths(self):
        left = self.manager.create_agent_team(self.root)
        moving = self.manager.create_agent_team(left)
        descendant = self.manager.create_agent_team(moving)
        right = self.manager.create_agent_team(self.root)
        right_child = self.manager.create_agent_team(right)

        self.assertEqual(moving.depth, 2)
        self.assertEqual(descendant.depth, 3)
        self.assertEqual(right_child.depth, 2)

        success, _ = await self.manager.negotiate_and_execute_migration(
            moving, right_child, "Move the complete branch."
        )

        self.assertTrue(success)
        self.assertEqual(moving.depth, 3)
        self.assertEqual(descendant.depth, 4)
    async def test_migration_rejects_changed_approval_path(self):
        left = self.manager.create_agent_team(self.root)
        right = self.manager.create_agent_team(self.root)
        moving = self.manager.create_agent_team(left)
        self.manager.config.migration_policy = "ancestor_approval"
        started = asyncio.Event()
        release = asyncio.Event()

        class BlockingApproval:
            async def authorize_migration(
                self, team, target_parent, manager, rationale
            ):
                started.set()
                await release.wait()
                return True, "approved on old path"

        with patch(
            "ai_team_team.core.policies.resolve_migration_policy",
            return_value=BlockingApproval(),
        ):
            task = asyncio.create_task(
                self.manager.negotiate_and_execute_migration(
                    moving, right, "path changes"
                )
            )
            await started.wait()
            with self.manager._topology_lock:
                left.add_child_team(right)
                right._parent_team = left
                self.manager._team_parent_map[right.team_id] = left.team_id
                right.invalidate_depth_cache(recursive=True)
            release.set()
            success, reason = await task

        self.assertFalse(success)
        self.assertIn("approval path changed", reason)
        self.assertIs(moving.parent_team, left)
    async def test_parallel_votes_are_atomic_and_execute_once(self):
        team = self.manager.create_agent_team(self.root)
        first, second, third = team.members
        first_tools = get_default_tools(
            {"att_manager": self.manager}, first
        )
        response = await first_tools["initiate_membership_vote"](
            action="add",
            target="Verifier",
            rationale="Need independent verification.",
            proposed_details={"model": "default"},
        )
        proposal_id = response.split("'")[1]
        second_vote = get_default_tools(
            {"att_manager": self.manager}, second
        )["cast_vote"]
        third_vote = get_default_tools(
            {"att_manager": self.manager}, third
        )["cast_vote"]

        await asyncio.gather(
            second_vote(proposal_id, "Agree"),
            third_vote(proposal_id, "Agree"),
        )

        self.assertEqual(
            sum(
                member.name == "Dynamic_Verifier"
                for member in team.members
            ),
            1,
        )
        self.assertTrue(
            team.proposals[proposal_id]["proposed_details"]["executed"]
        )
        duplicate = await second_vote(proposal_id, "Agree")
        self.assertIn("already closed", duplicate)

        outsider = Agent("Outsider", "Observer", llm_client=self.client)
        outsider_vote = get_default_tools(
            {"att_manager": self.manager}, team
        )["cast_vote"]
        token = self.manager._active_tool_agent.set(outsider)
        try:
            rejected = await outsider_vote(proposal_id, "Agree")
        finally:
            self.manager._active_tool_agent.reset(token)
        self.assertIn("Only an active team member", rejected)
