"""Incident authority is revalidated after waiting for an unrelated commit."""

import asyncio
from unittest.mock import AsyncMock, patch

from ai_team_team.core.health import HealthSubject
from test.test_att.test_agent_activity._support import ActivityTestCase
from ._lock_support import ObservedLock


class IncidentAuthorityPublicationTests(ActivityTestCase):
    async def assert_parent_change_fences(self, action, *, durable):
        if durable:
            self.manager = self.make_manager(self.root, durable=True)
        manager = self.manager
        parent = manager.create_agent_team(self.root)
        subject_team = manager.create_agent_team(self.root, parent=parent)
        actor = parent.members[0]
        incident = await manager.supervisor.record_incident(
            HealthSubject(kind="agent_team", subject_id=subject_team.team_id),
            "changing-parent-authority", {"kind": "host"}, occurrence_id="parent-evidence")
        incident_id = incident.values["incident_id"]

        async def act(kind, *, claim_token=None):
            actor_token = manager._active_tool_agent.set(actor)
            team_token = manager._active_team.set(parent)
            try:
                if kind == "claim":
                    return await manager.claim_health_incident(incident_id)
                return await manager.acknowledge_health_incident(incident_id, 1, claim_token=claim_token)
            finally:
                manager._active_team.reset(team_token)
                manager._active_tool_agent.reset(actor_token)

        claim = await act("claim") if action == "acknowledge" else {}
        previous = manager._records.index[incident.identity]
        event_count = len(self.records("health_incident_events"))
        # Preserve an admitted request before its normal asynchronous finalizer.
        with patch.object(manager._migration, "complete_request", new=AsyncMock()):
            migration = await manager.negotiate_and_execute_migration(subject_team, None, "Voluntary independence.")
            await asyncio.sleep(0)
        gate = ObservedLock(manager._runtime_gate)
        with patch.object(manager._activity, "schedule_notice"), patch.object(manager, "_runtime_gate", gate):
            async with gate:
                moving = asyncio.create_task(manager._migration.complete_request(migration.request_id))
                await gate.wait_for_attempt(moving)
                self.assertTrue(manager._topology.transition_lock.locked())
                mutation = asyncio.create_task(act(action, claim_token=claim.get("token")))
                await gate.wait_for_attempt(mutation)
                self.assertTrue(manager.supervisor.incident_lock.locked())
                self.assertFalse(mutation.done())
            await moving
            self.assertTrue(subject_team.is_independent)
            with self.assertRaises(PermissionError):
                await mutation
        self.assertEqual(manager._records.index[incident.identity], previous)
        self.assertEqual(len(self.records("health_incident_events")), event_count)
        if durable:
            state = await manager._persistence.read(manager.db_path, reconcile=False)
            stored = next(row for row in state["records"] if row.identity == incident.identity)
            self.assertEqual(stored, previous)
        # Losing the former parent cannot prevent explicit Host handling.
        result = await manager.acknowledge_health_incident(incident_id, 1)
        self.assertEqual(result["status"], "ACKNOWLEDGED")

    async def test_claim_rechecks_parent_authority_before_volatile_acceptance(self):
        await self.assert_parent_change_fences("claim", durable=False)

    async def test_claim_rechecks_parent_authority_before_durable_acceptance(self):
        await self.assert_parent_change_fences("claim", durable=True)

    async def test_acknowledgement_rechecks_parent_authority_before_volatile_acceptance(self):
        await self.assert_parent_change_fences("acknowledge", durable=False)

    async def test_acknowledgement_rechecks_parent_authority_before_durable_acceptance(self):
        await self.assert_parent_change_fences("acknowledge", durable=True)
