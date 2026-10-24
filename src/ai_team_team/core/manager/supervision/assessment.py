"""All predefined findings form authority; no member compiles a team consensus."""

import asyncio
import contextvars

from ai_team_team.core.health import HealthSubject
from ai_team_team.core.response import AuditResult, AuditStatus, OperationalStatus
from ai_team_team.database.persistence.records import thaw
from ai_team_team.database.persistence.receipts import settle_commit

from ..activity.values import capture, identifier
from ..timing import wait_until


class HealthAssessmentMixin:
    @staticmethod
    def unknown(reason, *, framework_status=OperationalStatus.UNKNOWN, framework_reason="Assessment was unavailable."):
        return AuditResult(status=AuditStatus.UNKNOWN, reason=reason, operational_status=framework_status,
            operational_reason=framework_reason)

    def unknown_for_run(self, run, reason):
        template = run.values["template"]
        framework = OperationalStatus(template["evidence"].get("framework_operational_status", "unknown"))
        status = framework if template["operational_mode"] != "supervisor" else OperationalStatus.UNKNOWN
        return self.unknown(reason, framework_status=status, framework_reason="No new operational finding was confirmed.")

    def aggregate(self, run, findings):
        electorate = tuple(run.values["electorate"])
        if {row.values["scoped_agent_id"] for row in findings} != set(electorate) or len(findings) != len(electorate):
            return self.unknown_for_run(run, "Not every predefined auditor submitted a valid finding.")
        def majority(field, choices):
            return next((value for value in choices if sum(row.values[field] == value for row in findings) > len(electorate) / 2), "unknown")
        status = AuditStatus(majority("status", ("healthy", "unhealthy", "unknown")))
        mode = run.values["template"]["operational_mode"]
        framework = OperationalStatus(run.values["template"]["evidence"].get("framework_operational_status", "unknown"))
        operational = framework if mode == "framework" else OperationalStatus(majority("operational_status", ("healthy", "degraded", "unknown")))
        if mode == "framework_then_supervisor" and operational is OperationalStatus.UNKNOWN:
            operational = framework
        return AuditResult(status=status, reason="Complete predefined structured findings were aggregated by strict majority.",
            operational_status=operational, operational_reason="Runtime health is independent of the health conclusion.")

    async def run_assessment(self, audit_id, team):
        manager = self.manager
        result = self.unknown("The assessment did not produce a confirmed result.")
        failure = None
        timer = None
        row = manager._records.index[("audit_runs", (audit_id,))]
        try:
            await manager._records.commit((capture(manager, "audit_runs", audit_id=audit_id, status="running"),))
            clock = manager._activity.clock
            deadline = clock.monotonic() + max(0.0, row.values["deadline"] - clock.wall_time())
            timer = asyncio.create_task(wait_until(clock, deadline), context=contextvars.Context())
            sessions = [await manager._activity.admit_auditor(member.agent_id, self.profiles[member.agent_id]) for member in team.members]
            while True:
                findings = [item for item in manager._records.snapshot() if item.table_name == "audit_findings" and item.values["audit_id"] == audit_id]
                if len(findings) == len(team.members):
                    result = self.aggregate(row, findings)
                    break
                if clock.monotonic() >= deadline:
                    result = self.unknown_for_run(row, "The total assessment deadline elapsed.")
                    break
                if any(session.failure is not None or not session.active and not any(
                        item.values["scoped_agent_id"] == session.agent_id for item in findings) for session in sessions):
                    result = self.unknown_for_run(row, "A predefined auditor failed or stopped without a valid finding.")
                    break
                self.changes[audit_id].clear()
                changed = asyncio.create_task(self.changes[audit_id].wait())
                try:
                    await asyncio.wait((changed, timer), return_when=asyncio.FIRST_COMPLETED)
                finally:
                    changed.cancel()
                    await asyncio.gather(changed, return_exceptions=True)
        except asyncio.CancelledError as error:
            failure = error
            result = self.unknown_for_run(row, "The health assessment was cancelled or the manager closed.")
        except BaseException as error:
            failure = error
            result = self.unknown_for_run(row, f"The health assessment failed ({type(error).__name__}).")
        finally:
            if timer is not None:
                timer.cancel()
                await asyncio.gather(timer, return_exceptions=True)
            finalizer = asyncio.create_task(self.finish_assessment(audit_id, team, result, failure),
                context=contextvars.Context(), name=f"att-audit-finish-{audit_id}")
            self.finalizers.add(finalizer)
            try:
                await settle_commit(finalizer)
            finally:
                self.finalizers.discard(finalizer)
        from ai_team_team.core.exceptions import StatePersistenceError, StateRestoreError, DatabaseOwnershipError
        if isinstance(failure, (StatePersistenceError, StateRestoreError, DatabaseOwnershipError)):
            raise failure
        return result

    async def finish_assessment(self, audit_id, team, result, failure):
        manager = self.manager
        with manager._resources.settlement():
            await manager._activity.stop_auditors(audit_id)
            run = manager._records.index[("audit_runs", (audit_id,))]
            findings = [thaw(row.values) for row in manager._records.snapshot() if row.table_name == "audit_findings" and row.values["audit_id"] == audit_id]
            identities = [thaw(row.values["identity_snapshot"]) for row in manager._records.snapshot()
                          if row.table_name == "audit_participants" and row.values["audit_id"] == audit_id]
            records = (capture(manager, "audit_runs", audit_id=audit_id,
                status="unknown" if result.status is AuditStatus.UNKNOWN else "completed"),
                capture(manager, "audit_evidence", audit_id=audit_id,
                    evidence_references=thaw(run.values["template"]["evidence"]),
                    findings={"result": result.model_dump(mode="json"), "members": findings,
                              "failure_kind": type(failure).__name__ if failure else None},
                    result=result.status.value, identity_snapshots=identities,
                    created_at=manager._activity.clock.wall_time()))
            try:
                await manager._records.commit(records, allow_closing=True)
                self.results[audit_id] = result
            finally:
                # A failed writer is propagated, but cannot retain privileged
                # runtime identities or give late workers ordinary authority.
                for member in team.members:
                    self.profiles.pop(member.agent_id, None)
                if manager.teams.get(team.team_id) is team:
                    await manager._team_creation.dissolve_supervisory_team(team, persist=False)
            manager._emit_callback("on_system_event", "health_assessment_finished",
                {"audit_id": audit_id, "status": result.status.value, "operational_status": result.operational_status.value})
            if result.status is not AuditStatus.HEALTHY or result.operational_status is OperationalStatus.DEGRADED:
                subject = HealthSubject.from_record(run.values)
                mode = manager.config.audit_unknown_escalation_mode if result.status is AuditStatus.UNKNOWN else (
                    "wake" if result.status is AuditStatus.UNHEALTHY else manager.config.operational_degraded_escalation_mode)
                incident = await self.record_incident(subject, run.values["template"]["fingerprint"],
                    {"kind": "assessment", "audit_id": audit_id, "status": result.status.value,
                     "operational_status": result.operational_status.value}, occurrence_id=f"ASSESSMENT-{audit_id}", delivery_mode=mode)
                await self.deliver_incident(incident, mode)
        self.changes.pop(audit_id, None)

    async def interrupt_restored_assessments(self):
        manager = self.manager
        with manager._resources.settlement():
            for row in tuple(manager._records.snapshot()):
                if row.table_name == "audit_runs" and row.values["status"] in {"prepared", "running"}:
                    result = self.unknown_for_run(row, "The previous process ended before this assessment finished.")
                    identities = [thaw(item.values["identity_snapshot"]) for item in manager._records.snapshot()
                        if item.table_name == "audit_participants" and item.values["audit_id"] == row.values["audit_id"]]
                    await manager._records.commit((capture(manager, "audit_runs", audit_id=row.values["audit_id"], status="interrupted"),
                        capture(manager, "audit_evidence", audit_id=row.values["audit_id"],
                            evidence_references=thaw(row.values["template"]["evidence"]),
                            findings={"result": result.model_dump(mode="json"), "members": [], "failure_kind": "interrupted"},
                            result="unknown", identity_snapshots=identities, created_at=manager._activity.clock.wall_time())), allow_closing=True)
                    self.results[row.values["audit_id"]] = result
                    subject = HealthSubject.from_record(row.values)
                    await self.record_incident(subject, row.values["template"]["fingerprint"],
                        {"kind": "assessment", "audit_id": row.values["audit_id"], "status": "unknown"},
                        occurrence_id=f"ASSESSMENT-{row.values['audit_id']}", delivery_mode=manager.config.audit_unknown_escalation_mode)
            claimed_owners = {row.values["evidence"]["claim"]["agent_id"] for row in manager._records.snapshot()
                if row.table_name == "health_incidents" and row.values["status"] == "claimed"}
            for owner in claimed_owners:
                await self.release_claims(owner)
