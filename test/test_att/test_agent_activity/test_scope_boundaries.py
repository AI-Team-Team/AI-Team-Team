"""Relationship changes alter invocation authority without replacing a person."""

import asyncio
from unittest.mock import Mock

from ai_team_team import Agent
from ai_team_team.core.activity.contracts import AgentTeamScope, SuppressionPreference
from test.test_att.test_agent_activity._support import ActivityTestCase, call, idle
from test.test_att.test_autonomous_activity_phase0._fixtures import AsyncBarrier, ModelStep, ScriptedModelClient


class ScopeBoundaryTests(ActivityTestCase):
    async def test_a_silent_member_does_not_hold_another_member_at_a_team_barrier(self):
        self.manager._activity.schedule_notice = Mock()
        gate = AsyncBarrier()
        self.client.steps.append(ModelStep(idle(), gate))
        other_client = ScriptedModelClient(ModelStep(idle()))
        other = self.manager.register_agent(Agent("IndependentMember", "Researcher", other_client))
        self.manager.register_llm_client("independent-member", other_client)
        team = self.manager.bootstrap_agent_team(self.root, existing_members=[self.root, other],
            member_configs={"Third": {"model": "fixture"}})
        first = await self.manager.activate_agent(self.root.agent_id, scope=AgentTeamScope(team_id=team.team_id))
        await gate.wait_entered()
        try:
            second = await self.manager.activate_agent(other.agent_id, scope=AgentTeamScope(team_id=team.team_id))
            await self.wait(second)
            self.assertEqual(len(other_client.requests), 1)
            self.assertTrue(self.manager._activity.sessions[self.root.agent_id].active)
            self.assertEqual(self.manager.inspect_agent_activity(other.agent_id).intent, "idle")
            self.assertFalse(self.records("chat_messages"))
        finally:
            gate.release()
        await self.wait(first)

    async def test_dissolution_during_a_provider_wait_closes_the_old_scope_before_tools_execute(self):
        self.manager._activity.schedule_notice = Mock()
        team = self.manager.bootstrap_agent_team(self.root, existing_members=[self.root],
            member_configs={"Peer1": {"model": "fixture"}, "Peer2": {"model": "fixture"}})
        barrier = AsyncBarrier()
        self.client.steps.extend((ModelStep(call("send_team_message", {"markdown": "must not publish"}), barrier), ModelStep(idle())))
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
        observations = [message for message in self.client.requests[1].prompt if message.get("role") == "tool"]
        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0]["tool_status"], "denied")
        self.assertEqual(observations[0]["tool_error_kind"], "scope_ended")

    async def test_the_same_valid_publication_succeeds_while_its_scope_remains_active(self):
        self.manager._activity.schedule_notice = Mock()
        team = self.manager.bootstrap_agent_team(self.root, existing_members=[self.root],
            member_configs={"Peer1": {"model": "fixture"}, "Peer2": {"model": "fixture"}})
        self.steps(call("send_team_message", {"markdown": "must publish"}), idle())
        admission = await self.manager.activate_agent(self.root.agent_id,
            scope=AgentTeamScope(team_id=team.team_id))
        await self.wait(admission)
        messages = self.records("chat_messages")
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].values["author_agent_id"], self.root.agent_id)
        stream = next(row for row in self.records("chat_streams") if row.values["team_id"] == team.team_id)
        self.assertEqual(messages[0].values["stream_id"], stream.values["stream_id"])
        self.assertEqual(self.client.unexpected_requests, 0)

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
