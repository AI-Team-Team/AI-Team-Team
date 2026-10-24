"""One health service over the common Manager, personal runtime, and writer."""

import asyncio
import contextvars
import logging

from ai_team_team.core.health import HealthAssessmentAdmission, HealthSubject
from ai_team_team.database.persistence.records import freeze, thaw

from ..activity.values import capture, identifier
from .assessment import HealthAssessmentMixin
from .detection import HealthDetectionMixin
from .incidents import HealthIncidentMixin
from .tools import AuditToolMixin


class HealthAssessmentUnavailable(RuntimeError):
    """The configured temporary assessment cannot be provisioned right now."""


class SupervisionService(HealthAssessmentMixin, HealthDetectionMixin, HealthIncidentMixin, AuditToolMixin):
    def __init__(self, manager):
        self.manager = manager
        self.logger = logging.getLogger("ATTManager.Supervision")
        self.lock = asyncio.Lock()
        self.detection_lock = asyncio.Lock()
        self.detection_tasks = {}
        self.incident_lock = asyncio.Lock()
        self.incident_delivery_tasks = {}
        self.active_tasks = set()
        self.finalizers = set()
        self.profiles = {}
        self.audit_tasks = {}
        self.changes = {}
        self.results = {}
        self.semantic_detector = None
        self.semantic_evidence_provider = None

    def is_supervisory_agent(self, agent_id):
        return any(team.team_kind == "supervisory" and any(member.agent_id == agent_id for member in team.members)
                   for team in self.manager.teams.values())

    def require_subject(self, subject):
        subject = HealthSubject.model_validate(subject)
        if subject.kind == "agent":
            agent = self.manager._agents_by_id.get(subject.subject_id)
            if (agent is None or agent.lifecycle_state != "active" or self.is_supervisory_agent(agent.agent_id)
                    or self.manager._topology.is_agent_pending(agent.agent_id)):
                raise ValueError("A health subject must be a live ordinary Agent.")
        elif subject.kind == "agent_team":
            team = self.manager.teams.get(subject.subject_id)
            self.manager._topology.require_available(team)
        return subject

    @staticmethod
    def validate_evidence(evidence):
        allowed = {"kind", "tool_name", "error_kind", "observation_ids", "window_seconds", "facts", "framework_operational_status"}
        value = thaw(freeze(evidence))
        if not isinstance(value, dict) or set(value) - allowed:
            raise ValueError("An audit accepts only explicitly permitted health evidence, never arbitrary runtime objects.")
        if value.get("kind") not in {"model_protocol", "tool_arguments", "semantic", "integrity", "host"}:
            raise ValueError("An audit requires an explicit evidence type.")
        if not isinstance(value.get("observation_ids", []), list) or any(type(item) is not str or not item for item in value.get("observation_ids", [])):
            raise ValueError("Health evidence references must be explicit observation IDs.")
        if not isinstance(value.get("facts", []), list) or any(type(item) is not str for item in value.get("facts", [])):
            raise ValueError("Explicit health facts must be text statements supplied by their authorized producer.")
        value.setdefault("observation_ids", [])
        value.setdefault("facts", [])
        return value

    async def admit(self, subject, evidence, *, fingerprint=None):
        manager = self.manager
        if manager._closing or manager._restore_in_progress:
            raise RuntimeError("Health-assessment admission is closed.")
        subject = self.require_subject(subject)
        evidence = self.validate_evidence(evidence)
        for source_id in evidence["observation_ids"]:
            source = manager._records.index.get(("health_observations", (source_id,)))
            if source is None or subject.kind != "agent" or source.values["agent_id"] != subject.subject_id:
                raise PermissionError("An audit evidence reference is missing or belongs to another subject.")
        fingerprint = fingerprint or self.fingerprint(subject, evidence)
        team = None
        audit_id = identifier("AUDIT")
        operation_id = f"AUDIT-ADMISSION-{audit_id}"
        admission_task = asyncio.current_task()
        self.active_tasks.add(admission_task)
        try:
            async with self.lock:
                current = next((row for row in manager._records.snapshot() if row.table_name == "audit_runs"
                    and row.values["status"] in {"prepared", "running"}
                    and row.values["template"].get("fingerprint") == fingerprint
                    and dict(row.values["template"]["subject"]) == subject.model_dump(mode="json")), None)
                if current is not None:
                    return HealthAssessmentAdmission(audit_id=current.values["audit_id"], status="COALESCED", deadline=current.values["deadline"])
                try:
                    team = manager._team_creation.create_supervisory_team()
                except (TypeError, ValueError, RuntimeError, OSError) as error:
                    raise HealthAssessmentUnavailable("The configured assessment team could not be provisioned.") from error
                now = manager._activity.clock.wall_time()
                row = capture(manager, "audit_runs", audit_id=audit_id, **subject.record_fields(),
                    temporary_team_id=team.team_id, template={"preset": "supervisor_audit", "fingerprint": fingerprint,
                        "subject": subject.model_dump(mode="json"), "evidence": evidence,
                        "operational_mode": manager.config.operational_status_decision_mode,
                        "quota_policy": "shared_model_ledger"},
                    electorate=[agent.agent_id for agent in team.members], runtime_generation=manager._resources.generation,
                    status="prepared", created_at=now, deadline=now + manager.config.health.audit_timeout_seconds, token_budget=0)
                records = [row]
                for position, agent in enumerate(team.members):
                    try:
                        alias, agent.llm_client = manager._runtime.provider_binding(agent.llm_client)
                    except (TypeError, ValueError) as error:
                        raise HealthAssessmentUnavailable("An assessment model binding is unavailable.") from error
                    records.append(capture(manager, "audit_participants", audit_id=audit_id, scoped_agent_id=agent.agent_id,
                        identity_snapshot={"agent_id": agent.agent_id, "name": agent.name, "role": agent.role},
                        model_alias=alias, position=position))
                try:
                    await manager._records.commit(records, operation_id=operation_id)
                finally:
                    if operation_id in manager._records.receipts:
                        profile = thaw(row.values)
                        for member in team.members:
                            self.profiles[member.agent_id] = profile
                        self.changes[audit_id] = asyncio.Event()
                        self.start_assessment(audit_id, team)
            return HealthAssessmentAdmission(audit_id=audit_id, status="ADMITTED", deadline=row.values["deadline"])
        except BaseException:
            if team is not None and operation_id not in manager._records.receipts:
                with manager._resources.settlement():
                    await manager._team_creation.dissolve_supervisory_team(team, persist=False)
            raise
        finally:
            self.active_tasks.discard(admission_task)

    def start_assessment(self, audit_id, team):
        task = asyncio.create_task(self.run_assessment(audit_id, team), context=contextvars.Context(), name=f"att-audit-{audit_id}")
        self.active_tasks.add(task)
        self.audit_tasks[audit_id] = task
        def finished(done):
            self.active_tasks.discard(done)
            if not done.cancelled() and done.exception() is not None:
                self.logger.error("Health assessment failed (%s).", type(done.exception()).__name__)
        task.add_done_callback(finished)

    def activity_changed(self, audit_id):
        event = self.changes.get(audit_id)
        if event is not None:
            event.set()

    async def wait(self, audit_id):
        task = self.audit_tasks.get(audit_id)
        if task is not None:
            await asyncio.shield(task)
        if audit_id in self.results:
            return self.results[audit_id]
        from ai_team_team.core.response import AuditResult, AuditStatus, OperationalStatus
        evidence = self.manager._records.index.get(("audit_evidence", (audit_id,)))
        if evidence is None:
            raise KeyError("Unknown or unresolved health assessment.")
        return AuditResult.model_validate(thaw(evidence.values["findings"])["result"], strict=False) if "result" in evidence.values["findings"] else AuditResult(
            status=AuditStatus.UNKNOWN, reason="This assessment was interrupted.", operational_status=OperationalStatus.UNKNOWN,
            operational_reason="No assessment result was confirmed.")

    async def cancel(self, audit_id):
        task = self.audit_tasks.get(audit_id)
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
