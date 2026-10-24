from test.test_att.test_hardening._support import (
    ATTConfig,
    ATTManager,
    ATTHardeningTestCase,
    Agent,
    AsyncMock,
    AuditResult,
    AuditStatus,
    DatabaseStore,
    MagicMock,
    StateRestoreError,
    asyncio,
    closing,
    get_default_tools,
    os,
    patch,
    sqlite3,
)
from test.governance_client import approve_pending_business, settle_governance_activity


class TestATTHardening(ATTHardeningTestCase):
    async def test_migration_invalidates_all_descendant_depths(self):
        left = self.manager.create_agent_team(self.root, parent=self.root)
        moving = self.manager.create_agent_team(left, parent=left)
        descendant = self.manager.create_agent_team(moving, parent=moving)
        right = self.manager.create_agent_team(self.root, parent=self.root)
        right_child = self.manager.create_agent_team(right, parent=right)

        self.assertEqual(moving.depth, 2)
        self.assertEqual(descendant.depth, 3)
        self.assertEqual(right_child.depth, 2)

        result = await self.manager.negotiate_and_execute_migration(
            moving, right_child, "Move the complete branch."
        )

        self.assertEqual(result.status, "PENDING")
        await approve_pending_business(self.manager, result.request_id)
        self.assertEqual(self.manager.inspect_migration_request(result.request_id).status, "EXECUTED")
        self.assertEqual(moving.depth, 3)
        self.assertEqual(descendant.depth, 4)
    async def test_migration_rejects_changed_approval_path(self):
        left = self.manager.create_agent_team(self.root, parent=self.root)
        right = self.manager.create_agent_team(self.root, parent=self.root)
        moving = self.manager.create_agent_team(left, parent=left)
        self.manager.config.migration_policy = "ancestor_approval"

        result = await self.manager.negotiate_and_execute_migration(moving, right, "path changes")
        await settle_governance_activity(self.manager)
        original_cases = list(self.manager._governance.cases.values())
        self.manager.config.migration_policy = "permissive"
        change = await self.manager.negotiate_and_execute_migration(right, left, "Change a relevant ancestor path.")
        await approve_pending_business(self.manager, change.request_id)

        for item in original_cases:
            for agent_id in item.voter_agent_ids:
                actor = self.manager._agents_by_id[agent_id]
                token = self.manager._active_tool_agent.set(actor)
                try:
                    await self.manager.submit_governance_choice(item.case_id, {"approved": True}, actor=actor)
                finally:
                    self.manager._active_tool_agent.reset(token)
        await self.manager._migration.complete_request(result.request_id)
        current = self.manager.inspect_migration_request(result.request_id)
        self.assertEqual(current.status, "STALE")
        self.assertIn("approval path changed", current.reason)
        self.assertIs(moving.parent_team, left)
    async def test_parallel_votes_are_atomic_and_execute_once(self):
        team = self.manager.create_agent_team(self.root, parent=self.root)
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
