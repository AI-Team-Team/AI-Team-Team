"""Outcomes, protected results, attention, and addressed notices commit together."""

import asyncio
import contextvars

from ai_team_team.core.response import ToolResult, ToolResultStatus
from ai_team_team.database.persistence.receipts import settle_commit
from ..activity.values import capture, identifier


class OutcomeMixin:
    async def finish_result(self, job, result):
        """Once returned, a factual outcome is owned by a local commit finalizer."""
        if job.outcome_task is None:
            job.result = result
            job.outcome_task = asyncio.create_task(self.accept_result(job, result),
                context=contextvars.Context(), name=f"att-execution-outcome-{job.execution_id}")
            self.finalizers.add(job.outcome_task)
            job.outcome_task.add_done_callback(self.finalizer_finished)
        return await settle_commit(job.outcome_task)

    async def accept_result(self, job, result):
        """Apply the same final authority check to normal and late outcomes."""
        result._execution_id = job.execution_id
        try:
            accepted = await self.complete(job, result)
        except PermissionError:
            result = ToolResult(job.call_id, job.tool.name,
                "Source permission changed before the result was accepted.",
                status=ToolResultStatus.DENIED, error_kind="permission_denied")
            result._execution_id = job.execution_id
            # Only this framework-generated constant is source independent.
            # Arbitrary failure bodies are subject to the same ACL as success.
            accepted = await self.complete(job, result, safe_denial=True)
        if not accepted:
            previous = self.manager._records.index[("executions", (job.execution_id,))]
            cancelled = previous.values["status"] == "cancelled"
            result = ToolResult(job.call_id, job.tool.name,
                "The execution was confirmed cancelled." if cancelled else "This outcome was not accepted by the execution runtime.",
                status=ToolResultStatus.BUSINESS_ERROR if cancelled else ToolResultStatus.DENIED,
                error_kind="execution_cancelled" if cancelled else "outcome_not_accepted")
            result._execution_id = job.execution_id
        job.result = result
        return result

    def next_observation_index(self, execution_id):
        return 1 + max((row.values["observation_index"] or 0 for row in self.manager._records.snapshot()
            if row.table_name == "execution_observations" and row.values["execution_id"] == execution_id), default=0)

    def notice_records(self, job, event_key):
        owner = job.context.agent_id
        marker = self.manager._records.index.get(("agent_activities", (owner,)))
        arrival = marker.values["arrival_generation"] + 1 if marker else 1
        notice_id = f"EXECUTION-NOTICE-{job.execution_id}-{event_key}"
        if ("agent_notifications", (notice_id,)) in self.manager._records.index:
            return (), ()
        from ..activity.values import Session
        session = self.manager._activity.sessions.get(owner) or Session(
            owner, identifier("ADMISSION"), self.manager._resources.generation, active=False, intent="idle")
        notice = capture(self.manager, "agent_notifications", notification_id=notice_id,
            agent_id=owner, source_kind="execution", execution_id=job.execution_id, classification="ordinary",
            deduplication_key=f"execution:{job.execution_id}:{event_key}", arrival_generation=arrival,
            created_at=self.clock.wall_time())
        return (notice, self.manager._activity.marker(session, arrival_generation=arrival)), (notice_id,)

    async def commit_outcome(self, records, *, notifications=(), dirty=None, authority_check=None):
        operation_id = identifier("EXECUTION-FACT")
        try:
            with self.manager._resources.settlement():
                return await self.manager._records.commit(records, operation_id=operation_id,
                    notifications=notifications, dirty=dirty, allow_closing=True, authority_check=authority_check)
        finally:
            if operation_id in self.manager._records.receipts and not self.closing:
                for notice in notifications:
                    self.manager._activity.schedule_notice(notice)

    def artifact_dirty(self, job):
        dirty = self.manager._new_dirty_state()
        with self.manager._snapshot_lock:
            for claim in job.claims:
                if claim.namespace != "library" or claim.access != "write":
                    continue
                dirty["libraries"].add(claim.resource_id)
                files = self.manager._library_files.get(claim.resource_id, {})
                selected = {path: text for path, text in files.items()
                    if path == claim.path or claim.subtree and (not claim.path or path.startswith(claim.path + "/"))}
                if claim.path:
                    selected.setdefault(claim.path, None)
                dirty["file_changes"].setdefault(claim.resource_id, {}).update(selected)
        return dirty

    async def complete(self, job, result, *, safe_denial=False):
        prepared = await self.prepare_result(job.tool, result)
        async with self.manager._activity.lock:
            if self.sealed:
                return False
            previous = self.manager._records.index[("executions", (job.execution_id,))]
            if previous.values["status"] in {"completed", "failed", "cancelled"}:
                return False
            health = "error" if result.status in {ToolResultStatus.INTERNAL_ERROR, ToolResultStatus.TRANSIENT_ERROR} else "healthy"
            if previous.values["started_at"] is None:
                health = "unknown"
            background = previous.values["visibility"] != "foreground"
            records = [
                capture(self.manager, "executions", execution_id=job.execution_id,
                    status="failed" if result.failed else "completed", outcome_unconfirmed=0,
                    attention="required" if background or result.failed else "none",
                    finished_at=max(self.clock.wall_time(), previous.values["started_at"] or previous.values["created_at"])),
                self.result_payload(job.execution_id, job.context.agent_id, prepared),
                capture(self.manager, "execution_observations", observation_id=identifier("EXECUTION-OBSERVATION"),
                    execution_id=job.execution_id, health=health, evidence_kind="terminal_result",
                    evidence={"status": result.status.value, "attempts": result.attempts},
                    observed_at=self.clock.wall_time(), uncertain=0,
                    observation_index=self.next_observation_index(job.execution_id)),
            ]
            cooldown = None
            cooldown_deadline = None
            if result.status in {ToolResultStatus.TRANSIENT_ERROR, ToolResultStatus.INTERNAL_ERROR} and result.error_kind != "auditor_failure":
                seconds = self.manager.config.activity.tool_cooldown_seconds
                include = self.manager.config.activity.cooldown_downtime == "include"
                cooldown = capture(self.manager, "tool_cooldowns", agent_id=job.context.agent_id,
                    tool_name=job.tool.name, fault_id=job.execution_id, accounting_mode="wall_time" if include else "remaining",
                    remaining_seconds=None if include else seconds, deadline=self.clock.wall_time() + seconds if include else None,
                    sampled_at=self.clock.wall_time())
                records.append(cooldown)
                cooldown_deadline = self.clock.monotonic() + seconds
            notices, ids = self.notice_records(job, "terminal") if background else ((), ())
            try:
                def authorize_result():
                    if not safe_denial:
                        owner = self.manager._agents_by_id.get(job.context.agent_id)
                        if owner is None or owner.lifecycle_state != "active" or not self.source_authorized(previous, owner, committing=True):
                            raise PermissionError("Source permission changed before the result was accepted.")
                        self.validate_bindings(job)
                await self.commit_outcome((*records, *notices), notifications=ids, dirty=self.artifact_dirty(job),
                                          authority_check=authorize_result)
            finally:
                if cooldown is not None and self.manager._records.index.get(cooldown.identity) == cooldown:
                    key = job.context.agent_id, job.tool.name
                    if cooldown.values["accounting_mode"] == "remaining":
                        self.manager._activity.cooldown_deadlines[key] = cooldown_deadline
                    else:
                        self.manager._activity.cooldown_deadlines.pop(key, None)
        self.manager._emit_callback("on_system_event", "execution_outcome_committed", {
            "execution_id": job.execution_id, "agent_id": job.context.agent_id,
            "tool_name": job.tool.name, "status": "failed" if result.failed else "completed"})
        return True
