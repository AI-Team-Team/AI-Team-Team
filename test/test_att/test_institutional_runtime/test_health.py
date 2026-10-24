"""Thresholds are assessment requests, not automatic intervention authority."""

from unittest.mock import AsyncMock, patch

from ai_team_team import ATTConfig, LLMResponse, ToolCall
from ai_team_team.core.health import HealthSubject
from ai_team_team.core.response import AuditStatus
from test.test_att.test_agent_activity._support import ActivityTestCase
from test.health_client import HealthModelClient


class HealthRuntimeTests(ActivityTestCase):
    async def test_strict_defaults_and_independent_deadlines(self):
        config = ATTConfig()
        self.assertEqual((config.health.protocol_failure_threshold, config.health.tool_argument_failure_threshold), (3, 5))
        self.assertEqual(config.health.observation_window_seconds, 600)
        self.assertEqual(config.health.audit_timeout_seconds, 600)
        self.assertEqual(config.parent_failover_timeout_seconds, 120)
        self.assertFalse(config.health.semantic_detection_enabled)
        for name in ("protocol_failure_threshold", "tool_argument_failure_threshold", "observation_window_seconds", "audit_timeout_seconds"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                setattr(config.health, name, 0)

    async def test_protocol_streak_uses_one_person_and_different_protocol_codes(self):
        self.manager.register_runtime_clock(self.clock)
        with patch.object(self.manager.supervisor, "admit", new=AsyncMock()) as admit:
            for index, kind in enumerate(("bad_identity", "bad_envelope", "bad_identity")):
                await self.manager.supervisor.observe(self.root.agent_id, "model_protocol", source_id=f"response-{index}",
                    valid=False, error_kind=kind)
            self.assertEqual(admit.await_count, 1)
            self.assertIs(self.root.llm_client, self.client)
            self.assertEqual(self.root.lifecycle_state, "active")
            incidents = self.records("health_incidents")
            self.assertEqual(len(incidents), 1)
            self.clock.advance(601)
            self.assertEqual(self.records("health_incidents"), incidents)

    async def test_success_window_and_duplicate_detection(self):
        self.manager.register_runtime_clock(self.clock)
        with patch.object(self.manager.supervisor, "admit", new=AsyncMock()) as admit:
            async def observe(source, valid=False):
                await self.manager.supervisor.observe(self.root.agent_id, "model_protocol", source_id=source,
                    valid=valid, error_kind="protocol" if not valid else None)
            await observe("one")
            await observe("one")
            await observe("two")
            await observe("valid", True)
            await observe("three")
            self.clock.advance(601)
            await observe("four")
            await observe("five")
            self.assertEqual(admit.await_count, 0)
            await observe("six")
            self.assertEqual(admit.await_count, 1)

    async def test_tool_streaks_are_per_tool_and_category(self):
        with patch.object(self.manager.supervisor, "admit", new=AsyncMock()) as admit:
            for index in range(4):
                await self.manager.supervisor.observe(self.root.agent_id, "tool_arguments", source_id=f"bad-{index}",
                    valid=False, tool_name="tool_a", error_kind="missing")
            await self.manager.supervisor.observe(self.root.agent_id, "tool_arguments", source_id="other-success",
                valid=True, tool_name="tool_b")
            self.assertEqual(admit.await_count, 0)
            await self.manager.supervisor.observe(self.root.agent_id, "tool_arguments", source_id="fifth",
                valid=False, tool_name="tool_a", error_kind="missing")
            self.assertEqual(admit.await_count, 1)
            await self.manager.supervisor.observe(self.root.agent_id, "tool_arguments", source_id="new-type",
                valid=False, tool_name="tool_a", error_kind="wrong_type")
            self.assertEqual(admit.await_count, 1)

    async def test_real_fresh_team_uses_common_runtime_and_all_findings(self):
        client = HealthModelClient()
        self.root.llm_client = client
        self.manager.register_llm_client("health-fixture", client)
        before = (self.root.agent_id, self.root.private_doc_library_id, list(self.root.messages))
        admission = await self.manager.request_health_assessment(HealthSubject(kind="att"),
            {"kind": "host", "facts": ["Assess explicitly permitted framework metadata."]})
        result = await self.manager.wait_for_health_assessment(admission.audit_id)
        self.assertEqual(result.status, AuditStatus.HEALTHY)
        self.assertEqual(len(self.records("audit_findings")), 3)
        self.assertTrue(self.records("audit_model_requests"))
        self.assertTrue(self.records("audit_execution_evidence"))
        self.assertTrue(self.records("audit_activity_checkpoints"))
        self.assertFalse(any(team.team_kind == "supervisory" for team in self.manager.teams.values()))
        self.assertEqual((self.root.agent_id, self.root.private_doc_library_id, self.root.messages), before)
        for _prompt, _instruction, names in client.calls:
            self.assertNotIn("read_private_file", names)
            self.assertNotIn("dispatch_subagent", names)
            self.assertNotIn("set_operation_scope", names)

    async def test_incident_generation_and_explicit_acknowledgement(self):
        service = self.manager.supervisor
        subject = HealthSubject(kind="att")
        row = await service.record_incident(subject, "stable-fingerprint", {"kind": "host"}, occurrence_id="first")
        duplicate = await service.record_incident(subject, "stable-fingerprint", {"kind": "host"}, occurrence_id="first")
        self.assertEqual(duplicate.values["occurrence_count"], 1)
        claim = await self.manager.claim_health_incident(row.values["incident_id"])
        self.assertEqual(claim["status"], "CLAIMED")
        row = await service.record_incident(subject, "stable-fingerprint", {"kind": "host"}, occurrence_id="second")
        result = await self.manager.acknowledge_health_incident(row.values["incident_id"], 1)
        self.assertEqual(result["status"], "STALE")
        await self.manager.acknowledge_health_incident(row.values["incident_id"], 2)
        self.assertEqual(self.manager.inspect_health_incident(row.values["incident_id"])["status"], "acknowledged")
        self.assertEqual(len(self.records("health_incident_events")), 4)
