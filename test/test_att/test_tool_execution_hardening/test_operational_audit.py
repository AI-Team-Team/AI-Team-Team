"""Independent framework and supervisory operational-health dimensions."""

from ai_team_team import HealthSubject, OperationalStatus, AuditStatus
from test.health_client import HealthModelClient
from test.test_att.test_agent_activity._support import ActivityTestCase


class TestOperationalAuditModes(ActivityTestCase):
    async def assess(self, mode, *, status="healthy", operational="healthy", submit=True):
        client = HealthModelClient(status=status, operational_status=operational, submit=submit)
        self.manager.register_llm_client(f"health-{len(self.manager.llm_clients)}", client)
        self.root.llm_client = client
        self.manager.config.operational_status_decision_mode = mode
        admission = await self.manager.request_health_assessment(HealthSubject(kind="att"),
            {"kind": "host", "facts": ["Structured runtime failures were observed."], "framework_operational_status": "degraded"})
        return await self.manager.wait_for_health_assessment(admission.audit_id)

    async def test_framework_keeps_its_own_operational_finding_independent_of_health(self):
        result = await self.assess("framework", status="unhealthy")
        self.assertEqual(result.status, AuditStatus.UNHEALTHY)
        self.assertEqual(result.operational_status, OperationalStatus.DEGRADED)

    async def test_supervisor_can_produce_a_different_operational_conclusion(self):
        result = await self.assess("supervisor")
        self.assertEqual(result.status, AuditStatus.HEALTHY)
        self.assertEqual(result.operational_status, OperationalStatus.HEALTHY)

    async def test_hybrid_retains_framework_status_when_no_complete_findings_exist(self):
        result = await self.assess("framework_then_supervisor", submit=False)
        self.assertEqual(result.status, AuditStatus.UNKNOWN)
        self.assertEqual(result.operational_status, OperationalStatus.DEGRADED)

    async def test_supervisor_failure_does_not_fabricate_framework_authority(self):
        result = await self.assess("supervisor", submit=False)
        self.assertEqual(result.status, AuditStatus.UNKNOWN)
        self.assertEqual(result.operational_status, OperationalStatus.UNKNOWN)
