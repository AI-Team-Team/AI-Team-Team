"""Health reports depend on declared evidence, never silence alone."""

import asyncio

from ai_team_team.core.exceptions import ToolArgumentError
from ..activity.values import capture, identifier
from ..timing import wait_until
from ai_team_team.database.persistence.records import thaw


class HealthMixin:
    async def report_health(self, execution_id, health, evidence_kind, evidence=None):
        job = self.jobs.get(execution_id)
        if job is None or job.finished.is_set():
            raise PermissionError("Health evidence requires this runtime's live execution.")
        actor = self.manager._active_tool_agent.get()
        if actor is not None and self.current.get() is not job and self.resource_job.get() is not job:
            raise PermissionError("An execution cannot report another execution's health.")
        if health not in {"healthy", "degraded", "stalled", "error", "unknown"}:
            raise ToolArgumentError("Unknown execution health state.")
        if evidence_kind not in job.tool.execution_contract.health_signals:
            raise ToolArgumentError("The executor did not declare this health signal.")
        evidence = dict(evidence or {})
        if set(evidence) - {"sequence", "units_completed", "provider_status"}:
            raise ToolArgumentError("Health evidence accepts only counters and a classified provider status.")
        if any(type(value) is not int or value < 0 for key, value in evidence.items() if key != "provider_status"):
            raise ToolArgumentError("Health counters must be nonnegative integers.")
        if "provider_status" in evidence and evidence["provider_status"] not in {"running", "completed", "failed", "stalled", "unavailable"}:
            raise ToolArgumentError("Invalid classified provider status.")
        async with self.manager._activity.lock:
            await self.report_health_locked(job, health, evidence_kind, evidence)

    async def report_health_locked(self, job, health, evidence_kind, evidence):
        """Order accepted signals and timeout observations under the same lock."""
        if self.sealed:
            return
        execution_id = job.execution_id
        row = self.manager._records.index[("executions", (execution_id,))]
        if row.values["status"] in {"completed", "failed", "cancelled"}:
            return
        if not job.started.is_set():
            raise ToolArgumentError("A queued execution cannot report runtime progress.")
        sample = self.clock.monotonic()
        latest = max((item for item in self.manager._records.snapshot()
            if item.table_name == "execution_observations" and item.values["execution_id"] == execution_id),
            key=lambda item: item.values["observation_index"] or 0, default=None)
        if (health != "healthy" and latest is not None and latest.values["health"] == health
                and latest.values["evidence_kind"] == evidence_kind and thaw(latest.values["evidence"]) == evidence):
            return
        observation_id = identifier("HEALTH")
        records = [capture(self.manager, "execution_observations", observation_id=observation_id,
            execution_id=execution_id, health=health, evidence_kind=evidence_kind, evidence=evidence,
            observed_at=self.clock.wall_time(), uncertain=int(health in {"stalled", "unknown"}),
            observation_index=self.next_observation_index(execution_id))]
        notices, ids = (), ()
        if health in {"degraded", "stalled", "error", "unknown"}:
            records.append(capture(self.manager, "executions", execution_id=execution_id, attention="required"))
            notices, ids = self.notice_records(job, observation_id)
        try:
            await self.commit_outcome((*records, *notices), notifications=ids)
        finally:
            if health == "healthy" and self.manager._records.index.get(records[0].identity) == records[0]:
                job.health_samples[evidence_kind] = sample
                job.health_updated.set()

    def start_health_monitor(self, job):
        if job.health_task is not None:
            return
        contract = job.tool.execution_contract
        if contract.heartbeat_timeout_seconds is None and contract.progress_timeout_seconds is None:
            return
        job.health_task = asyncio.create_task(self.monitor_health(job), name=f"att-health-{job.execution_id}")
        self.tasks.add(job.health_task)
        job.health_task.add_done_callback(self.worker_finished)

    async def monitor_health(self, job):
        reported_deadlines = {}
        while not job.finished.is_set() and not self.closing:
            async with self.manager._activity.lock:
                if job.finished.is_set() or self.closing or self.sealed:
                    return
                # Clearing before sampling under the reporting lock cannot
                # erase a newer accepted heartbeat during an awaited commit.
                job.health_updated.clear()
                deadlines = [(signal, job.health_samples.get(signal, job.started_monotonic) + timeout)
                    for signal in ("heartbeat", "progress")
                    if (timeout := getattr(job.tool.execution_contract, f"{signal}_timeout_seconds")) is not None]
                waiting = []
                for signal, deadline in deadlines:
                    if deadline <= self.clock.monotonic():
                        # Another signal's observation is not recovery of this
                        # signal. One accepted timeout per sample deadline
                        # prevents cross-signal repeats after a slow receipt.
                        if reported_deadlines.get(signal) != deadline:
                            await self.report_health_locked(job, "stalled", signal, {})
                            reported_deadlines[signal] = deadline
                    else:
                        # A later awaited observation may cross this deadline;
                        # keep it so the next iteration wakes immediately.
                        waiting.append(deadline)
            changed = asyncio.create_task(job.health_updated.wait())
            timer = asyncio.create_task(wait_until(self.clock, min(waiting))) if waiting else None
            try:
                await asyncio.wait((changed, timer) if timer else (changed,), return_when=asyncio.FIRST_COMPLETED)
            finally:
                changed.cancel()
                if timer:
                    timer.cancel()
                await asyncio.gather(*((changed, timer) if timer else (changed,)), return_exceptions=True)
