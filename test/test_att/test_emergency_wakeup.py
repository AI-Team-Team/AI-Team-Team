"""Protected event-driven attention replaces emergency discussion sessions."""

from ai_team_team import HealthSubject
from test.health_client import HealthModelClient
from test.test_att.test_agent_activity._support import ActivityTestCase


class TestProtectedHealthAttention(ActivityTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.health = HealthModelClient()
        self.manager.register_llm_client("health", self.health)
        self.root.llm_client = self.health
        self.parent = self.manager.create_agent_team(self.root)
        self.child = self.manager.create_agent_team(self.root, parent=self.parent)

    async def incident(self, mode, *, occurrence="one", fingerprint="stable"):
        row = await self.manager.supervisor.record_incident(
            HealthSubject(kind="agent_team", subject_id=self.child.team_id), fingerprint,
            {"kind": "host"}, occurrence_id=occurrence, delivery_mode=mode)
        await self.manager.supervisor.deliver_incident(row, mode)
        return row

    async def test_queue_retains_attention_without_forcing_personal_activity(self):
        row = await self.incident("queue")
        await self.settle()
        self.assertFalse(self.records("activity_admissions"))
        self.assertEqual(len(self.records("agent_notifications")), 3)
        member = self.parent.members[0]
        admission = await self.manager.activate_agent(member.agent_id)
        await self.wait(admission)
        self.assertEqual(self.manager.inspect_health_incident(row.values["incident_id"])["status"], "pending")
        self.assertIn(row.values["incident_id"], str(member.messages))

    async def test_wake_uses_existing_personal_activity_and_never_acknowledges_implicitly(self):
        row = await self.incident("wake")
        await self.settle()
        self.assertEqual(len(self.records("activity_admissions")), 3)
        self.assertEqual(self.manager.inspect_health_incident(row.values["incident_id"])["status"], "pending")
        self.assertFalse(self.records("audit_runs"))

    async def test_duplicate_occurrence_never_adds_another_notice(self):
        first = await self.incident("queue")
        second = await self.incident("queue")
        self.assertEqual(first.values["incident_id"], second.values["incident_id"])
        self.assertEqual(second.values["occurrence_count"], 1)
        self.assertEqual(len(self.records("agent_notifications")), 3)

    async def test_new_occurrence_merges_but_does_not_discard_old_evidence(self):
        first = await self.incident("queue")
        second = await self.incident("queue", occurrence="two")
        self.assertEqual(first.values["incident_id"], second.values["incident_id"])
        self.assertEqual(second.values["occurrence_count"], 2)
        self.assertEqual(len(self.records("health_incident_events")), 2)
        self.assertEqual(len(self.records("agent_notifications")), 6)
        self.assertFalse(self.records("activity_admissions"))

    async def test_plain_organizational_inbox_input_is_not_an_execution_command(self):
        self.child.receive_message({"type": "ordinary", "reason": "Explicit organization metadata."})
        await self.settle()
        self.assertEqual(len(self.child.message_inbox), 1)
        self.assertFalse(self.records("activity_admissions"))
        self.assertFalse(hasattr(self.manager, "execute_emergency_discussion"))
