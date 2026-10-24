"""Health authority is explicit evidence, never business-progress evaluation."""

import asyncio

from ai_team_team import AuditStatus, HealthSubject
from test.health_client import HealthModelClient
from test.test_att.test_agent_activity._support import ActivityTestCase


class TestATTSupervision(ActivityTestCase):
    async def health_client(self, **options):
        client = HealthModelClient(**options)
        self.manager.register_llm_client("health", client)
        self.root.llm_client = client
        return client

    async def assess(self, subject=None, **evidence):
        admission = await self.manager.request_health_assessment(subject or HealthSubject(kind="att"),
            {"kind": "host", "facts": ["Explicitly permitted health metadata."], **evidence})
        return await self.manager.wait_for_health_assessment(admission.audit_id)

    async def test_complete_explicit_findings_form_a_health_conclusion(self):
        await self.health_client()
        result = await self.assess()
        self.assertEqual(result.status, AuditStatus.HEALTHY)
        self.assertEqual(len(self.records("audit_findings")), 3)
        self.assertFalse(self.records("health_incidents"))

    async def test_ordinary_answers_and_missing_findings_supply_no_health_authority(self):
        await self.health_client(submit=False)
        result = await self.assess()
        self.assertEqual(result.status, AuditStatus.UNKNOWN)
        self.assertFalse(self.records("audit_findings"))
        self.assertEqual(len(self.records("health_incidents")), 1)

    async def test_unhealthy_subject_escalates_without_recursively_auditing_parent(self):
        await self.health_client(status="unhealthy")
        parent = self.manager.create_agent_team(self.root)
        child = self.manager.create_agent_team(self.root, parent=parent)
        result = await self.assess(HealthSubject(kind="agent_team", subject_id=child.team_id))
        await self.settle()
        self.assertEqual(result.status, AuditStatus.UNHEALTHY)
        self.assertEqual(len(self.records("audit_runs")), 1)
        self.assertEqual(len(self.records("health_incidents")), 1)
        self.assertEqual(self.records("health_incidents")[0].values["status"], "pending")
        self.assertEqual({row.values["agent_id"] for row in self.records("agent_notifications")}, {member.agent_id for member in parent.members})

    async def test_confirmed_integrity_fault_applies_protection_before_incident_commit(self):
        protected = []
        row = await self.manager.report_integrity_fault(HealthSubject(kind="att"), "permission_invariant", protect=lambda: protected.append(True))
        self.assertEqual(protected, [True])
        self.assertTrue(row["evidence"]["latest"]["protection_applied"])
        self.assertFalse(self.records("audit_runs"))
        self.assertEqual(len(self.records("health_incident_events")), 1)

    async def test_framework_callbacks_do_not_publish_permitted_evidence_bodies(self):
        await self.health_client()
        events = []
        self.manager.on_system_event = lambda event, payload: events.append((event, payload))
        await self.assess(facts=["HOST_PERMITTED_EVIDENCE_BODY"])
        await self.manager.flush_callbacks()
        self.assertTrue(any(name == "health_assessment_finished" for name, _ in events))
        self.assertNotIn("HOST_PERMITTED_EVIDENCE_BODY", repr(events))

    async def test_health_admission_rejects_unapproved_evidence_fields(self):
        with self.assertRaises(ValueError):
            await self.manager.request_health_assessment(HealthSubject(kind="att"),
                {"kind": "host", "private_documents": ["PRIVATE_BODY"]})
        self.assertFalse(self.records("audit_runs"))
        self.assertFalse(any(team.team_kind == "supervisory" for team in self.manager.teams.values()))
