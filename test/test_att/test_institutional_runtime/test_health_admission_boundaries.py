"""Assessment capacity and temporary service failures never become Agent blame."""

import asyncio
from unittest.mock import patch

from ai_team_team import LLMResponse, StatePersistenceError, ToolCall
from ai_team_team.core.health import HealthSubject
from ai_team_team.core.manager.supervision.service import HealthAssessmentUnavailable
from ai_team_team.core.response import AuditStatus
from test.async_waits import wait_for_runtime
from test.health_client import HealthModelClient
from test.test_att.test_agent_activity._support import ActivityTestCase, idle


class HealthAdmissionBoundaryTests(ActivityTestCase):
    async def threshold(self):
        for index in range(3):
            await self.manager.supervisor.observe(self.root.agent_id, "model_protocol",
                source_id=f"protocol-{index}", valid=False, error_kind="invalid_envelope")

    async def test_unavailable_assessment_retains_incident_without_stopping_person(self):
        with patch.object(self.manager.supervisor, "admit", side_effect=HealthAssessmentUnavailable("Unavailable")):
            await self.threshold()
        self.assertEqual(len(self.records("health_incidents")), 1)
        self.assertEqual(len(self.records("health_observations")), 3)
        self.steps(idle())
        admission = await self.manager.activate_agent(self.root.agent_id)
        await self.wait(admission)
        self.assertEqual(self.manager.inspect_agent_activity(self.root.agent_id).intent, "idle")
        self.assertIs(self.root.llm_client, self.client)

    async def test_persistence_failure_is_not_classified_as_assessment_unavailability(self):
        with patch.object(self.manager.supervisor, "admit", side_effect=StatePersistenceError("Writer failed")):
            with self.assertRaises(StatePersistenceError):
                await self.threshold()
        self.assertEqual(len(self.records("health_incidents")), 1)

    async def test_audit_staging_filesystem_failure_does_not_interrupt_the_person(self):
        from pathlib import Path

        managed_root = Path(self.workspace.name) / ".att_doc_libs"
        before = set(managed_root.iterdir())
        malformed = LLMResponse(tool_calls=[ToolCall("duplicate", "one", {}), ToolCall("duplicate", "two", {})])
        self.steps(malformed, malformed, malformed, idle())
        original = self.manager._build_document_library
        staged = 0

        def failing_staging(**kwargs):
            nonlocal staged
            if kwargs.get("library_kind") == "agent_private":
                staged += 1
                if staged == 2:
                    raise OSError("Temporary audit storage is unavailable.")
            return original(**kwargs)

        with patch.object(self.manager, "_build_document_library", side_effect=failing_staging):
            admission = await self.manager.activate_agent(self.root.agent_id)
            await self.wait(admission)
        self.assertIsNone(self.manager._activity.sessions[self.root.agent_id].failure)
        self.assertEqual(len(self.records("health_incidents")), 1)
        self.assertEqual(len([row for row in self.records("health_observations") if not row.values["valid"]]), 3)
        self.assertFalse(self.records("audit_runs"))
        self.assertEqual(set(managed_root.iterdir()), before)
        self.assertEqual(set(self.manager.agents), {self.root.name})

    async def test_factory_persistence_failure_is_not_wrapped_as_temporary_unavailability(self):
        with patch.object(self.manager._team_creation, "create_supervisory_team", side_effect=StatePersistenceError("Writer failed")):
            with self.assertRaises(StatePersistenceError):
                await self.threshold()
        self.assertEqual(len(self.records("health_incidents")), 1)

    async def await_running(self, audit_id):
        async def running():
            while self.manager._records.index[("audit_runs", (audit_id,))].values["status"] != "running":
                await asyncio.sleep(0)
        await wait_for_runtime(self.manager, running(), label="Assessment starts its total deadline")

    async def test_total_deadline_includes_waiting_for_common_scheduler_capacity(self):
        self.manager.register_runtime_clock(self.clock)
        self.manager.config.activity.max_concurrent_activities = 1
        self.manager.config.activity.llm.request_timeout_seconds = 1_200
        self.manager.config.activity.llm.sequence_timeout_seconds = 1_200
        blocker_started, release = asyncio.Event(), asyncio.Event()

        class Client(HealthModelClient):
            async def generate(inner, prompt, system_instruction=None, tools=None, **kwargs):
                if "submit_health_finding" not in {tool.name for tool in tools or ()}:
                    blocker_started.set()
                    await release.wait()
                    return idle()
                return await super().generate(prompt, system_instruction, tools, **kwargs)

        client = Client()
        self.root.llm_client = client
        self.manager.register_llm_client("deadline", client)
        ordinary = await self.manager.activate_agent(self.root.agent_id)
        await wait_for_runtime(self.manager, blocker_started.wait(), label="Ordinary person holds capacity")
        admission = await self.manager.request_health_assessment(HealthSubject(kind="att"), {"kind": "host"})
        await self.await_running(admission.audit_id)
        self.clock.advance(600)
        result = await wait_for_runtime(self.manager, self.manager.wait_for_health_assessment(admission.audit_id),
            label="Queued audit expires without provider admission")
        self.assertEqual(result.status, AuditStatus.UNKNOWN)
        self.assertFalse(self.records("audit_model_requests"))
        self.assertFalse(self.records("audit_findings"))
        release.set()
        await self.wait(ordinary)

    async def test_provider_response_after_total_deadline_cannot_submit_finding(self):
        self.manager.register_runtime_clock(self.clock)
        started, release = asyncio.Event(), asyncio.Event()

        class Client(HealthModelClient):
            async def generate(inner, prompt, system_instruction=None, tools=None, **kwargs):
                started.set()
                await release.wait()
                return await super().generate(prompt, system_instruction, tools, **kwargs)

        client = Client()
        self.root.llm_client = client
        self.manager.register_llm_client("late-audit", client)
        admission = await self.manager.request_health_assessment(HealthSubject(kind="att"), {"kind": "host"})
        await wait_for_runtime(self.manager, started.wait(), label="Auditor provider request is in flight")
        self.clock.advance(600)
        release.set()
        result = await wait_for_runtime(self.manager, self.manager.wait_for_health_assessment(admission.audit_id),
            label="Late audit response loses authority")
        self.assertEqual(result.status, AuditStatus.UNKNOWN)
        self.assertFalse(self.records("audit_findings"))
        self.assertFalse(any(team.team_kind == "supervisory" for team in self.manager.teams.values()))
