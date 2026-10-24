"""Durable institutional anchors bind the clock before disposable workers exist."""

import asyncio
from pathlib import Path
from unittest.mock import patch

from ai_team_team import ATTConfig, ATTManager, Agent, TokenLimitExceededError
from ai_team_team.core.activity.contracts import ToolExecutionContract
from ai_team_team.core.health import HealthSubject
from ai_team_team.core.response import AuditStatus
from test.health_client import HealthModelClient
from test.test_att.test_agent_activity._support import ActivityTestCase, idle
from ._lock_support import ObservedLock


class RuntimeClockOwnershipTests(ActivityTestCase):
    def use_health_client(self):
        client = HealthModelClient()
        self.root.llm_client = client
        self.manager.register_llm_client("health-clock", client)

    async def test_clock_can_be_bound_after_untimed_topology_setup(self):
        self.manager.create_agent_team(self.root)
        self.manager.register_runtime_clock(self.clock)
        self.assertIs(self.manager._activity.clock, self.clock)

    async def test_only_the_host_can_bind_a_clock(self):
        token = self.manager._active_tool_agent.set(self.root)
        try:
            with self.assertRaises(PermissionError):
                self.manager.register_runtime_clock(self.clock)
        finally:
            self.manager._active_tool_agent.reset(token)

    async def test_clock_binding_is_closed_during_lifecycle_publication(self):
        for field in ("_closing", "_restore_in_progress"):
            with self.subTest(field=field), patch.object(self.manager, field, True):
                with self.assertRaises(RuntimeError):
                    self.manager.register_runtime_clock(self.clock)

    async def test_admitted_audit_binds_clock_before_its_workers_run(self):
        self.use_health_client()
        admission = await self.manager.request_health_assessment(HealthSubject(kind="att"), {"kind": "host"})
        self.assertFalse(self.manager._activity.sessions)
        with self.assertRaisesRegex(RuntimeError, "before activity or timers"):
            self.manager.register_runtime_clock(self.clock)
        result = await self.manager.wait_for_health_assessment(admission.audit_id)
        self.assertEqual(result.status, AuditStatus.HEALTHY)
        self.assertFalse(self.manager._activity.sessions)
        with self.assertRaises(RuntimeError):
            self.manager.register_runtime_clock(self.clock)

    async def test_queued_audit_admission_binds_clock_before_its_receipt(self):
        self.use_health_client()
        gate = ObservedLock(self.manager._runtime_gate)
        with patch.object(self.manager, "_runtime_gate", gate):
            async with gate:
                admission = asyncio.create_task(self.manager.request_health_assessment(HealthSubject(kind="att"), {"kind": "host"}))
                await gate.wait_for_attempt(admission)
                self.assertFalse(admission.done())
                self.assertFalse(self.records("audit_runs"))
                with self.assertRaises(RuntimeError):
                    self.manager.register_runtime_clock(self.clock)
            admitted = await admission
        self.assertEqual((await self.manager.wait_for_health_assessment(admitted.audit_id)).status, AuditStatus.HEALTHY)

    async def test_queued_personal_admission_binds_clock_before_its_session_is_published(self):
        self.steps(idle())
        gate = ObservedLock(self.manager._runtime_gate)
        with patch.object(self.manager, "_runtime_gate", gate):
            async with gate:
                admission = asyncio.create_task(self.manager.activate_agent(self.root.agent_id))
                await gate.wait_for_attempt(admission)
                self.assertFalse(self.manager._activity.sessions)
                with self.assertRaises(RuntimeError):
                    self.manager.register_runtime_clock(self.clock)
            admitted = await admission
        await self.wait(admitted)

    async def test_queued_background_admission_binds_clock_before_its_job_is_published(self):
        async def operation():
            return "A completed clock-binding fixture."

        self.manager.register_tool("clock_operation", func=operation,
            execution_contract=ToolExecutionContract(effects=("read_only",), background_allowed=True,
                required_scope="personal", mutation_safety="none"), resource_resolver=lambda _scope, _arguments: ())
        gate = ObservedLock(self.manager._runtime_gate)
        with patch.object(self.manager, "_runtime_gate", gate), patch.object(self.manager._activity, "schedule_notice"):
            async with gate:
                admission = asyncio.create_task(self.manager.start_background_task("clock_operation", {}, actor=self.root))
                await gate.wait_for_attempt(admission)
                self.assertFalse(self.manager._executions.jobs)
                with self.assertRaises(RuntimeError):
                    self.manager.register_runtime_clock(self.clock)
            handle = await admission
            await self.manager._executions.jobs[handle.execution_id].finished.wait()

    async def test_pending_parent_resource_attempt_binds_clock_without_personal_workers(self):
        self.manager.config.failover_policy = "parent"
        self.manager.register_llm_client("replacement-clock", HealthModelClient())
        parent = self.manager.register_agent(Agent("ResourceParent", "Governor", self.client))
        team = self.manager.create_agent_team(self.root, parent=parent)
        with patch.object(self.manager._activity, "schedule_notice"):
            attempt = await self.manager.request_model_resource(team.members[0], team, TokenLimitExceededError("Exhausted"))
            self.assertEqual(attempt.status, "PENDING")
            self.assertFalse(self.manager._activity.sessions)
            with self.assertRaises(RuntimeError):
                self.manager.register_runtime_clock(self.clock)

    async def test_position_cooldown_binds_clock_without_a_model_call(self):
        team = self.manager.create_agent_team(self.root, parent=self.root)
        with patch.object(self.manager._activity, "schedule_notice"):
            result = await self.manager.negotiate_and_execute_migration(team, None, "Choose independence.")
            self.assertEqual(result.status, "EXECUTED")
            self.assertFalse(self.manager._activity.sessions)
            with self.assertRaises(RuntimeError):
                self.manager.register_runtime_clock(self.clock)

    async def test_retained_detector_streak_binds_its_observation_window(self):
        await self.manager.supervisor.observe(self.root.agent_id, "model_protocol", source_id="first-protocol-response",
            valid=False, error_kind="invalid_envelope")
        self.assertFalse(self.manager._activity.sessions)
        self.assertFalse(self.records("audit_runs"))
        with self.assertRaises(RuntimeError):
            self.manager.register_runtime_clock(self.clock)

    async def test_restored_completed_assessment_retains_clock_ownership_without_workers(self):
        self.use_health_client()
        admission = await self.manager.request_health_assessment(HealthSubject(kind="att"), {"kind": "host"})
        await self.manager.wait_for_health_assessment(admission.audit_id)
        database = str(Path(self.workspace.name) / "clock-restore.sqlite")
        await self.manager.save_state(database)
        await self.manager.close()
        client = self.root.llm_client
        restored = ATTManager(Agent("Restorer", "Architect", client),
            ATTConfig(workspace_root=str(Path(self.workspace.name) / "restorer")), persistence_mode="volatile")
        self.addAsyncCleanup(restored.close)
        restored.register_llm_client("health-clock", client)
        await restored.load_state(database)
        self.assertFalse(restored._activity.sessions)
        self.assertFalse(restored.supervisor.active_tasks)
        with self.assertRaises(RuntimeError):
            restored.register_runtime_clock(self.clock)
