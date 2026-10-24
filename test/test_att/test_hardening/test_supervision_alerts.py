"""Current organizational authority, explicit acknowledgement, and guard failures."""

from ai_team_team import HealthSubject
from test.governance_client import approve_pending_business
from test.health_client import HealthModelClient
from test.test_att.test_agent_activity._support import ActivityTestCase


class TestHealthAuthority(ActivityTestCase):
    async def test_incident_authority_follows_the_actual_parent_not_notification_history(self):
        client = HealthModelClient()
        self.root.llm_client = client
        self.manager.register_llm_client("health", client)
        first = self.manager.create_agent_team(self.root)
        second = self.manager.create_agent_team(self.root)
        child = self.manager.create_agent_team(self.root, parent=first)
        row = await self.manager.supervisor.record_incident(
            HealthSubject(kind="agent_team", subject_id=child.team_id), "stable", {"kind": "host"},
            occurrence_id="attention", delivery_mode="queue")
        await self.manager.supervisor.deliver_incident(row, "queue")
        move = await self.manager.negotiate_and_execute_migration(child, second, "Choose a new parent.")
        await approve_pending_business(self.manager, move.request_id)
        person = first.members[0]
        actor = self.manager._active_tool_agent.set(person)
        scope = self.manager._active_team.set(first)
        try:
            with self.assertRaises(PermissionError):
                await self.manager.claim_health_incident(row.values["incident_id"])
        finally:
            self.manager._active_team.reset(scope)
            self.manager._active_tool_agent.reset(actor)
        person = second.members[-1]
        actor = self.manager._active_tool_agent.set(person)
        scope = self.manager._active_team.set(second)
        try:
            claim = await self.manager.claim_health_incident(row.values["incident_id"])
            result = await self.manager.acknowledge_health_incident(
                row.values["incident_id"], claim["occurrence_count"], claim_token=claim["token"])
            self.assertEqual(result["status"], "ACKNOWLEDGED")
        finally:
            self.manager._active_team.reset(scope)
            self.manager._active_tool_agent.reset(actor)
        self.assertFalse(self.records("audit_runs"))

    async def test_protection_failure_is_recorded_without_leaking_exception_body(self):
        def protect():
            raise RuntimeError("PRIVATE-PROTECTION-SENTINEL")

        with self.assertRaisesRegex(RuntimeError, "PRIVATE-PROTECTION-SENTINEL"):
            await self.manager.report_integrity_fault(HealthSubject(kind="att"),
                "permission_guard_failure", protect=protect)
        incident = self.records("health_incidents")[0]
        self.assertFalse(incident.values["evidence"]["latest"]["protection_applied"])
        self.assertEqual(incident.values["evidence"]["latest"]["protection_error_type"], "RuntimeError")
        self.assertNotIn("PRIVATE-PROTECTION-SENTINEL", str(incident.values))
        self.assertFalse(self.records("audit_runs"))
