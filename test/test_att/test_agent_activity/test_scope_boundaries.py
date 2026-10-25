"""Relationship changes alter invocation authority without replacing a person."""

import asyncio
from unittest.mock import Mock

from ai_team_team.core.activity.contracts import AgentTeamScope, SuppressionPreference
from test.test_att.test_agent_activity._support import ActivityTestCase, call, idle
from test.test_att.test_autonomous_activity_phase0._fixtures import AsyncBarrier, ModelStep


class ScopeBoundaryTests(ActivityTestCase):
    async def test_dissolution_during_a_provider_wait_closes_the_old_scope_before_tools_execute(self):
        self.manager._activity.schedule_notice = Mock()
        team = self.manager.bootstrap_agent_team(self.root, existing_members=[self.root],
            member_configs={"Peer1": {"model": "fixture"}, "Peer2": {"model": "fixture"}})
        barrier = AsyncBarrier()
        self.client.steps.extend((ModelStep(call("send_team_message", {"team_id": team.team_id, "message": "must not publish"}), barrier), ModelStep(idle())))
        admission = await self.manager.activate_agent(self.root.agent_id, scope=AgentTeamScope(team_id=team.team_id))
        await barrier.wait_entered()
        try:
            await self.manager.close_team_conversation(team.team_id)
        finally:
            barrier.release()
        await self.wait(admission)
        self.assertFalse(self.records("chat_messages"))
        self.assertEqual(self.manager.inspect_agent_activity(self.root.agent_id).scope.kind, "personal")
        self.assertEqual(self.root.lifecycle_state, "active")
        self.assertEqual(len(self.client.requests), 2)

    async def test_two_deaths_in_shared_teams_complete_without_a_lock_cycle(self):
        self.manager._activity.schedule_notice = Mock()
        team = self.manager.create_agent_team(self.root, parent=self.root)
        first, second = team.members[:2]
        shared = self.manager.bootstrap_agent_team(self.root, existing_members=[first, second],
            member_configs={"Third": {"model": "fixture"}})
        await asyncio.wait_for(asyncio.gather(
            self.manager.mark_agent_dead(first.agent_id, confirm=True),
            self.manager.mark_agent_dead(second.agent_id, confirm=True)), 10)
        self.assertEqual(first.lifecycle_state, "dead")
        self.assertEqual(second.lifecycle_state, "dead")
        self.assertEqual(len(team.members), 1)
        self.assertEqual(len(shared.members), 1)
        self.assertIs(self.manager._agents_by_id[first.agent_id], first)

    async def test_notification_filter_for_an_external_at_confers_no_membership_or_file_rights(self):
        self.manager._activity.schedule_notice = Mock()
        team = self.manager.create_agent_team(self.root, parent=self.root)
        result = await self.manager.set_notification_suppression(
            SuppressionPreference(scope="agent_team", source_id=team.team_id), actor=self.root)
        self.assertEqual(result["source_id"], team.team_id)
        self.assertNotIn(self.root, team.members)
        self.assertEqual(self.manager.inspect_agent_activity(self.root.agent_id).intent, "idle")
