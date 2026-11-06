"""A vanished organizational scope cannot remove personal wake guarantees."""

import asyncio
from unittest.mock import Mock

from ai_team_team.core.activity.contracts import AgentTeamScope
from test.test_att.test_agent_activity._support import ActivityTestCase, call, idle
from ai_team_team.core.manager.activity.values import capture
from test.test_att.test_runtime_contracts._fixtures import AsyncBarrier, ModelStep


class SleepScopeTests(ActivityTestCase):
    async def test_protected_arrival_during_the_sleep_response_is_not_lost_at_the_boundary(self):
        self.manager.register_runtime_clock(self.clock)
        barrier = AsyncBarrier()
        sleep = call("set_activity_intent", {"intent": {"kind": "sleep", "countdown": {"minutes": 5}}})
        self.client.steps.extend((ModelStep(sleep, barrier), ModelStep(idle())))
        admission = await self.manager.activate_agent(self.root.agent_id)
        await barrier.wait_entered()
        try:
            event = self.manager._memory.record_event("permission_changed", agent=self.root,
                persist=False, inherit_context=False, payload={"resource_id": "changed-resource"})
            notice_id = await self.manager._activity.deliver_system_event(event)
        finally:
            barrier.release()
        await self.wait(admission, "sleep")
        await self.settle()
        self.assertEqual(len(self.client.requests), 2)
        self.assertEqual(self.manager.inspect_agent_activity(self.root.agent_id).intent, "idle")
        self.assertEqual(self.records("sleep_plans")[0].values["status"], "cancelled")
        self.assertTrue(any(row.values["notification_id"] == notice_id and row.values["status"] == "presented"
            for row in self.records("notification_claims")))

    async def test_provider_unavailability_does_not_extend_voluntary_sleep(self):
        self.manager.register_runtime_clock(self.clock)
        self.steps(call("set_activity_intent", {"intent": {"kind": "sleep", "countdown": {"minutes": 5}}}), idle())
        admitted = await self.manager.activate_agent(self.root.agent_id)
        await self.wait(admitted, "sleep")
        await self.manager._records.commit((capture(self.manager, "model_availability", agent_id=self.root.agent_id,
            model_alias="fixture", sequence_id="host-resource-repair", status="remediation_required",
            reason="configuration", request_budget=120, sequence_budget=600, last_confirmed={}),))
        timer = self.manager._activity.timers[self.root.agent_id]
        self.clock.advance(300)
        await asyncio.wait_for(timer, 10)
        current = self.manager.inspect_agent_activity(self.root.agent_id)
        self.assertEqual(current.intent, "continuing")
        self.assertEqual(current.availability, "unavailable")
        self.assertEqual(self.records("sleep_plans")[0].values["status"], "expired")
        self.assertEqual(len(self.client.requests), 1)
        await self.manager.clear_agent_model_unavailability(self.root.agent_id)
        await self.settle()
        self.assertEqual(len(self.client.requests), 2)
        self.assertEqual(self.manager.inspect_agent_activity(self.root.agent_id).intent, "idle")

    async def test_dissolution_during_sleep_wakes_the_same_person_in_personal_scope(self):
        self.manager.register_runtime_clock(self.clock)
        self.manager._activity.schedule_notice = Mock()
        team = self.manager.bootstrap_agent_team(self.root, existing_members=[self.root],
            member_configs={"Research": {"model": "fixture"}, "Review": {"model": "fixture"}})
        self.steps(call("set_activity_intent", {"intent": {"kind": "sleep", "countdown": {"minutes": 5}}}), idle())
        admitted = await self.manager.activate_agent(self.root.agent_id, scope=AgentTeamScope(team_id=team.team_id))
        await self.wait(admitted, "sleep")
        timer = self.manager._activity.timers[self.root.agent_id]
        await self.manager.close_team_conversation(team.team_id)
        self.clock.advance(300)
        await asyncio.wait_for(timer, 10)
        await self.settle()
        self.assertEqual(self.manager.inspect_agent_activity(self.root.agent_id).intent, "idle")
        self.assertEqual(self.manager.inspect_agent_activity(self.root.agent_id).scope.kind, "personal")
        self.assertEqual(len(self.client.requests), 2)
        self.assertEqual(self.root.lifecycle_state, "active")
