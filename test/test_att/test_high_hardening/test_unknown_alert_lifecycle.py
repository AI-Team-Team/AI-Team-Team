"""Retained incidents have explicit processing generations, never discussion TTLs."""

import asyncio
from pathlib import Path

from ai_team_team import ATTConfig, ATTManager, Agent, HealthSubject
from test.health_client import HealthModelClient
from test.test_att.test_agent_activity._support import ActivityTestCase


class TestHealthIncidentLifecycle(ActivityTestCase):
    async def test_deduplication_and_outbox_survive_restore(self):
        service = self.manager.supervisor
        parent = self.manager.create_agent_team(self.root)
        child = self.manager.create_agent_team(self.root, parent=parent)
        subject = HealthSubject(kind="agent_team", subject_id=child.team_id)
        first = await service.record_incident(subject, "unavailable-audit", {"kind": "host"},
            occurrence_id="outage-1", delivery_mode="queue")
        second = await service.record_incident(subject, "unavailable-audit", {"kind": "host"},
            occurrence_id="outage-2", delivery_mode="queue")
        self.assertEqual(first.values["incident_id"], second.values["incident_id"])
        # Crash between incident acceptance and outbox dispatch is recoverable.
        path = str(Path(self.workspace.name) / "incident.sqlite")
        await self.manager.save_state(path)
        await self.manager.close()
        client = HealthModelClient()
        restored = ATTManager(Agent("Temporary", "Architect", client),
            ATTConfig(workspace_root=self.workspace.name), persistence_mode="volatile")
        restored.register_llm_client("fixture", client)
        self.addAsyncCleanup(restored.close)
        await restored.load_state(path)
        async with asyncio.timeout(10):
            while restored.supervisor.incident_delivery_tasks:
                await asyncio.gather(*tuple(restored.supervisor.incident_delivery_tasks.values()))
                await asyncio.sleep(0)
        current = restored.inspect_health_incident(first.values["incident_id"])
        self.assertEqual(current["occurrence_count"], 2)
        self.assertEqual(current["first_at"], first.values["first_at"])
        self.assertEqual(current["status"], "pending")
        self.assertEqual(len([row for row in restored._records.snapshot()
            if row.table_name == "agent_notifications" and row.values["classification"] == "health"]), 3)
        self.assertFalse(any(row.table_name == "activity_admissions" for row in restored._records.snapshot()))
        restored.supervisor.resume_incident_delivery()
        async with asyncio.timeout(10):
            while restored.supervisor.incident_delivery_tasks:
                await asyncio.gather(*tuple(restored.supervisor.incident_delivery_tasks.values()))
                await asyncio.sleep(0)
        self.assertEqual(len([row for row in restored._records.snapshot()
            if row.table_name == "agent_notifications"]), 3)

    async def test_claim_failure_cancellation_new_generations_and_manual_clear(self):
        self.manager.register_runtime_clock(self.clock)
        subject = HealthSubject(kind="att")
        service = self.manager.supervisor
        first = await service.record_incident(subject, "stable", {"kind": "host"}, occurrence_id="first")
        incident_id = first.values["incident_id"]
        for error in (RuntimeError("Handling failed."), asyncio.CancelledError()):
            with self.subTest(error=type(error).__name__):
                with self.assertRaises(type(error)):
                    async with self.manager.handle_health_incident(incident_id):
                        raise error
                self.assertEqual(self.manager.inspect_health_incident(incident_id)["status"], "pending")
        claim = await self.manager.claim_health_incident(incident_id)
        await service.record_incident(subject, "stable", {"kind": "host"}, occurrence_id="second")
        self.assertEqual((await self.manager.acknowledge_health_incident(
            incident_id, claim["occurrence_count"]))["status"], "STALE")
        self.manager.config.audit_unknown_soft_threshold = 2
        identifiers = [incident_id]
        for index in range(4):
            row = await service.record_incident(subject, f"unique-{index}", {"kind": "host"},
                occurrence_id=f"unique-occurrence-{index}")
            identifiers.append(row.values["incident_id"])
        self.clock.advance(100_000)
        self.assertEqual(len(self.records("health_incidents")), 5)
        self.assertTrue(all(row.values["status"] == "pending" for row in self.records("health_incidents")))
        cleared = await self.manager.clear_health_incidents(identifiers)
        self.assertEqual(len(cleared), 5)
        self.assertTrue(all(item["status"] == "ACKNOWLEDGED" for item in cleared))
        self.assertEqual(len(self.records("health_incidents")), 5)
