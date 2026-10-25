"""Per-owner shutdown keeps control requests distinct from external facts."""

import asyncio
import contextvars

from ai_team_team.core.exceptions import ATTException
from ai_team_team.database.persistence.receipts import settle_commit

from ..activity.values import capture, identifier


class ExecutionLifecycleMixin:
    async def stop_retained_owner(self, owner):
        ids = [row.values["execution_id"] for row in self.manager._records.snapshot()
            if row.table_name == "executions" and row.values["agent_id"] == owner.agent_id
            and row.values["status"] in {"queued", "running"}]
        return await settle_commit(asyncio.gather(*(self.stop_for_lifecycle(execution_id, owner) for execution_id in ids)))

    async def stop_for_lifecycle(self, execution_id, owner):
        job = self.jobs.get(execution_id)
        row = self.owned(execution_id, owner)
        if row.values["status"] in {"completed", "failed", "cancelled"}:
            return self.control_result(row, "ALREADY_TERMINAL")
        if job is not None and row.values["status"] == "running" and job.tool.execution_contract.suspension == "provider":
            result = await self.suspend_for_lifecycle(job, owner)
            if result is not None:
                return result
        if owner.lifecycle_state == "active":
            return await self.request_cancel(execution_id, actor=owner)
        return await self._request_cancel(execution_id, owner, self.manager._resources.generation, retained_owner=True)

    async def suspend_for_lifecycle(self, job, owner):
        manager = self.manager
        if job.outcome_task is not None:
            await settle_commit(job.outcome_task)
            return self.control_result(self.owned(job.execution_id, owner), "ALREADY_TERMINAL")
        async with manager._activity.lock:
            row = self.owned(job.execution_id, owner)
            if row.values["status"] in {"completed", "failed", "cancelled"}:
                return self.control_result(row, "ALREADY_TERMINAL")
            if job.suspended:
                return self.control_result(row, "SUSPENDED")
            control_id = identifier("SUSPEND")
            await self.commit_outcome((capture(manager, "execution_controls", control_id=control_id,
                execution_id=job.execution_id, requester_agent_id=owner.agent_id, operation="suspend",
                acknowledgement="requested", requested_at=self.clock.wall_time(), outcome_race={}),))
            if job.authority is not None:
                manager._resources.revoke(job.authority)
        binding = self.bindings[job.tool.executor]
        async def suspend():
            # Hooks receive no ordinary tool authority, and their response is
            # only evidence about external suspension, never a business result.
            tokens = ((manager._active_tool_agent, manager._active_tool_agent.set(owner)),
                (manager._active_team, manager._active_team.set(manager.teams.get(getattr(job.context.scope, "team_id", None)))),
                (manager._resources._authority, manager._resources._authority.set(job.authority)))
            try:
                return await binding.suspend(job.execution_id)
            finally:
                for variable, token in reversed(tokens):
                    variable.reset(token)
        task = asyncio.create_task(suspend(), context=contextvars.Context(), name=f"att-suspend-{job.execution_id}")
        done, _pending = await asyncio.wait((task,), timeout=manager.config.executions.cancellation_grace_seconds)
        acknowledged = False
        error = None
        if task in done:
            try:
                acknowledged = task.result() is True
            except ATTException as failure:
                error = failure
                self.remember_error(failure)
            except (Exception, asyncio.CancelledError):
                pass
        else:
            task.cancel()
            self.tasks.add(task)
            task.add_done_callback(self.worker_finished)
        if job.outcome_task is not None:
            await settle_commit(job.outcome_task)
        async with manager._activity.lock:
            row = self.owned(job.execution_id, owner)
            terminal = row.values["status"] in {"completed", "failed", "cancelled"}
            await self.commit_outcome((capture(manager, "execution_controls", control_id=control_id,
                acknowledgement="acknowledged" if acknowledged else "uncertain",
                acknowledged_at=self.clock.wall_time() if acknowledged else None,
                outcome_race={"terminal": terminal, "suspended": acknowledged}),))
            if acknowledged and not terminal:
                job.suspended = True
                if job.health_task is not None:
                    job.health_task.cancel()
                if job.task is not None:
                    job.task.cancel()
        if error is not None:
            raise error
        return self.control_result(row, "ALREADY_TERMINAL" if terminal else "SUSPENDED") if terminal or acknowledged else None
