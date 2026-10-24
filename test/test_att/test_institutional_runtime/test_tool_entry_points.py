"""Individual autonomy and explicit organization choices use the normal tools."""

from unittest.mock import patch

from ai_team_team.core.activity.contracts import AgentTeamScope
from test.test_att.test_agent_activity._support import ActivityTestCase, call, idle


def proposal():
    return {
        "member_count": 3, "preset_name": "custom", "system_instructions": "",
        "team_purpose": "Voluntary research", "is_public_visible": False,
        "initiator_joins": False, "unanimous_acceptance_action": "require_confirmation",
        "late_join_policy": "disabled",
    }


class InstitutionalToolEntryTests(ActivityTestCase):
    async def test_personal_agent_can_create_an_independent_team_without_becoming_a_member(self):
        self.steps(call("propose_team_formation", {"proposal": proposal()}), idle())
        before = self.root.agent_id, self.root.private_doc_library_id, self.root.role
        admission = await self.manager.activate_agent(self.root.agent_id)
        await self.wait(admission)
        await self.settle()
        self.assertEqual(len(self.manager.teams), 1)
        team = next(iter(self.manager.teams.values()))
        self.assertTrue(team.is_independent)
        self.assertIs(team.creator, self.root)
        self.assertNotIn(self.root, team.members)
        self.assertEqual((self.root.agent_id, self.root.private_doc_library_id, self.root.role), before)
        self.assertEqual(len(self.client.requests), 2)
        self.assertFalse(self.client.unexpected_requests)

    async def test_agent_parent_is_an_explicit_personal_choice(self):
        self.steps(call("propose_team_formation", {"proposal": proposal(), "organizational_parent": "self"}), idle())
        admission = await self.manager.activate_agent(self.root.agent_id)
        await self.wait(admission)
        await self.settle()
        team = next(iter(self.manager.teams.values()))
        self.assertEqual((team.organizational_parent.kind, team.organizational_parent.principal_id),
            ("agent", self.root.agent_id))
        self.assertIsNone(team.parent_team)

    async def test_disabled_creation_is_removed_from_both_personal_and_team_views(self):
        team = self.manager.create_agent_team(self.root)
        self.manager.config.enable_dynamic_delegation = False
        for current in (None, team):
            tools = self.manager.get_available_tools(current, self.root if current is None else team.members[0])
            self.assertNotIn("propose_team_formation", tools)
            self.assertNotIn("dispatch_subagent", tools)

    async def test_migration_tool_can_choose_null_without_waiting_for_an_old_parent(self):
        parent = self.manager.create_agent_team(self.root)
        child = self.manager.bootstrap_agent_team(self.root, parent=parent, existing_members=[self.root],
            member_configs={"Helper1": {}, "Helper2": {}})
        self.steps(call("request_migration", {"target_parent": None, "rationale": "Choose independence."}),
            *(idle() for _ in range(4)))
        with patch.object(self.manager._activity, "schedule_notice"):
            admission = await self.manager.activate_agent(self.root.agent_id, scope=AgentTeamScope(team_id=child.team_id))
            await self.wait(admission)
            await self.settle()
        self.assertTrue(child.is_independent)
        self.assertEqual(self.records("team_position_cooldowns")[0].values["duration_seconds"], 600)
