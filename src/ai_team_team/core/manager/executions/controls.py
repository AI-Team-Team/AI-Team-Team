"""Cancellation requests and factual acknowledgements are different records."""

import asyncio
import contextvars
import inspect

from ai_team_team.core.execution import TaskControlResult
from ai_team_team.core.exceptions import ATTException
from ai_team_team.core.response import ToolResult, ToolResultStatus
from ai_team_team.database.persistence.receipts import settle_commit
from ..activity.values import capture, identifier


TERMINAL = {"completed", "failed", "cancelled"}


class ControlMixin:
    def control_result(self, row, status):
        return TaskControlResult(execution_id=row.values["execution_id"], status=status,
            durability=self.manager.persistence_mode, state_version=row.version)

    async def request_cancel(self, execution_id, *, actor=None):
        owner = self.actor(actor)
        self.owned(execution_id, owner)
        task = self.stop_tasks.get(execution_id)
        if task is None:
            task = asyncio.create_task(self._request_cancel(execution_id, owner, self.manager._resources.generation),
                context=contextvars.Context(), name=f"att-execution-control-{execution_id}")
            self.stop_tasks[execution_id] = task
            self.tasks.add(task)
            def finished(done):
                self.stop_tasks.pop(execution_id, None)
                self.worker_finished(done)
            task.add_done_callback(finished)
        # The protocol owns both the accepted receipt and its runtime handoff.
        # Cancelling this observer cannot strand a requested stop in the DB.
        return await settle_commit(task)

    async def _request_cancel(self, execution_id, owner, generation):
        if (generation != self.manager._resources.generation and not self.closing or self.manager._closed
                or self.manager._agents_by_id.get(owner.agent_id) is not owner or owner.lifecycle_state != "active"):
            raise PermissionError("The captured control owner or runtime is no longer active.")
        job = self.jobs.get(execution_id)
        if job is not None and job.outcome_task is not None:
            await settle_commit(job.outcome_task)
        async with self.manager._activity.lock:
            row = self.owned(execution_id, owner)
            if row.values["status"] in TERMINAL:
                return self.control_result(row, "ALREADY_TERMINAL")
            existing = next((item for item in self.manager._records.snapshot()
                if item.table_name == "execution_controls" and item.values["execution_id"] == execution_id
                and item.values["operation"] == "stop"), None)
            control_id = existing.values["control_id"] if existing else identifier("EXECUTION-CONTROL")
            if existing is None:
                await self.commit_outcome((capture(self.manager, "execution_controls", control_id=control_id,
                    execution_id=execution_id, requester_agent_id=owner.agent_id, operation="stop",
                    acknowledgement="requested", requested_at=self.clock.wall_time(), outcome_race={}),))
            job = self.jobs.get(execution_id)
            if job is None:
                return self.control_result(row, "UNCONFIRMED")
            job.control_id = control_id
            if job.outcome_task is not None:
                # The callable returned while the stop receipt was in flight.
                # Its local outcome commit wins over a speculative stop.
                outcome = job.outcome_task
            else:
                outcome = None
                job.cancellation_requested = True
            if outcome is not None:
                hook = None
            else:
                if job.authority is not None:
                    self.manager._resources.revoke(job.authority)
                if row.values["status"] == "queued":
                    await self.cancelled_records(job)
                    if job.task is not None:
                        job.task.cancel()
                    else:
                        job.finished.set()
                        self.release_job(job)
                        self.wakeup.set()
                    return self.control_result(self.manager._records.index[row.identity], "CANCELLED")
                if job.task is not None and not job.task.done():
                    job.task.cancel()
                # External stop hooks are bounded; local commits are not.
                binding = self.bindings[job.tool.executor]
                hook = getattr(binding, "cancel", None)
        if outcome is not None:
            await settle_commit(outcome)
            return self.control_result(self.manager._records.index[row.identity], "ALREADY_TERMINAL")
        acknowledged = False
        stop_error = None
        if hook is not None:
            async def stop():
                manager = self.manager
                owner_token = manager._active_tool_agent.set(owner)
                team_token = manager._active_team.set(manager.teams.get(getattr(job.context.scope, "team_id", None)))
                authority_token = manager._resources._authority.set(job.authority)
                try:
                    if inspect.iscoroutinefunction(hook):
                        value = await hook(execution_id)
                    else:
                        thread = asyncio.create_task(asyncio.to_thread(hook, execution_id), name="att-executor-stop-thread")
                        self.tasks.add(thread)
                        thread.add_done_callback(self.worker_finished)
                        # Expiring the observer's grace period does not stop a
                        # real thread or discard its later fatal exception.
                        value = await asyncio.shield(thread)
                    return await value if inspect.isawaitable(value) else value
                finally:
                    manager._resources._authority.reset(authority_token)
                    manager._active_team.reset(team_token)
                    manager._active_tool_agent.reset(owner_token)
            stopped = asyncio.create_task(stop(), context=contextvars.Context())
            done, _pending = await asyncio.wait((stopped,), timeout=self.manager.config.executions.cancellation_grace_seconds)
            if stopped in done:
                try:
                    acknowledged = stopped.result() is True
                except ATTException as error:
                    # A failed authoritative operation is not an ordinary
                    # provider refusal or timeout, even if stopping is unknown.
                    stop_error = error
                    self.remember_error(error)
                except (Exception, asyncio.CancelledError):
                    acknowledged = False
            else:
                stopped.cancel()
                self.tasks.add(stopped)
                stopped.add_done_callback(self.worker_finished)
        if job.outcome_task is not None:
            await settle_commit(job.outcome_task)
        async with self.manager._activity.lock:
            row = self.manager._records.index[row.identity]
            if row.values["status"] in TERMINAL:
                result = self.control_result(row, "CANCELLED" if row.values["status"] == "cancelled" else "ALREADY_TERMINAL")
            elif acknowledged:
                await self.cancelled_records(job)
                result = self.control_result(self.manager._records.index[row.identity], "CANCELLED")
            else:
                await self.uncertain_records(job)
                result = self.control_result(self.manager._records.index[row.identity], "UNCONFIRMED")
        if result.status == "UNCONFIRMED":
            self.manager._emit_callback("on_system_event", "execution_stop_unconfirmed", {
                "execution_id": execution_id, "agent_id": owner.agent_id,
                "reason": "Unable to stop or cancel; subsequent state unconfirmed"})
        if stop_error is not None:
            raise stop_error
        return result

    async def cancelled_records(self, job):
        previous = self.manager._records.index[("executions", (job.execution_id,))]
        records = [capture(self.manager, "executions", execution_id=job.execution_id,
            status="cancelled", outcome_unconfirmed=0, attention="required",
            finished_at=max(self.clock.wall_time(), previous.values["started_at"] or previous.values["created_at"]))]
        if job.control_id:
            records.append(capture(self.manager, "execution_controls", control_id=job.control_id,
                acknowledgement="acknowledged", acknowledged_at=self.clock.wall_time(), outcome_race={"stopped": True}))
        notices, ids = self.notice_records(job, "cancelled")
        await self.commit_outcome((*records, *notices), notifications=ids)
        job.result = ToolResult(job.call_id, job.tool.name, "The execution was confirmed cancelled.",
                               status=ToolResultStatus.BUSINESS_ERROR, error_kind="execution_cancelled")
        job.result._execution_id = job.execution_id
        if isinstance(job.error, asyncio.CancelledError):
            job.error = None

    async def uncertain_records(self, job):
        records = [capture(self.manager, "executions", execution_id=job.execution_id,
                           outcome_unconfirmed=1, attention="required")]
        if job.control_id:
            control = self.manager._records.index[("execution_controls", (job.control_id,))]
            if control.values["acknowledgement"] != "acknowledged":
                records.append(capture(self.manager, "execution_controls", control_id=job.control_id,
                                       acknowledgement="uncertain", outcome_race={"stopped": False}))
        notices, ids = self.notice_records(job, "uncertain")
        await self.commit_outcome((*records, *notices), notifications=ids)

    async def interrupted(self, job):
        outcome_error = None
        if job.outcome_task is not None:
            try:
                await settle_commit(job.outcome_task)
            except BaseException as error:
                outcome_error = job.error = error
        async with self.manager._activity.lock:
            if self.sealed:
                if outcome_error is not None:
                    raise outcome_error
                return
            row = self.manager._records.index[("executions", (job.execution_id,))]
            if row.values["status"] in TERMINAL:
                if isinstance(job.error, asyncio.CancelledError):
                    job.error = None
                if outcome_error is not None:
                    raise outcome_error
                return
            cooperative = job.tool.execution_contract.cancellation == "cooperative" and not job.pending_threads
            if isinstance(job.error, asyncio.CancelledError) and (row.values["status"] == "queued" or cooperative):
                await self.cancelled_records(job)
            else:
                await self.uncertain_records(job)
        if outcome_error is not None:
            raise outcome_error

    async def acknowledge(self, execution_id, *, actor=None):
        owner = self.actor(actor)
        async with self.manager._activity.lock:
            row = self.owned(execution_id, owner)
            if row.values["attention"] != "acknowledged":
                await self.commit_outcome((capture(self.manager, "executions", execution_id=execution_id, attention="acknowledged"),))
            return self.control_result(self.manager._records.index[row.identity], "ACKNOWLEDGED")

    async def close(self):
        self.closing = True
        if self.scheduler:
            self.scheduler.cancel()
        stopping = []
        for job in tuple(self.jobs.values()):
            if job.finished.is_set():
                continue
            owner = self.manager._agents_by_id[job.context.agent_id]
            stopping.append(asyncio.create_task(self.request_cancel(job.execution_id, actor=owner),
                context=contextvars.Context(), name=f"att-executor-stop-{job.execution_id}"))
        if stopping:
            outcomes = await settle_commit(asyncio.gather(*stopping, return_exceptions=True))
            for outcome in outcomes:
                if isinstance(outcome, BaseException):
                    self.remember_error(outcome)
        if self.tasks:
            await asyncio.wait(tuple(self.tasks), timeout=self.manager.config.executions.cancellation_grace_seconds)
        # Drain accepted local facts before cutting off late external returns.
        # No time limit is imposed on persistence or result preparation.
        while True:
            if self.finalizers:
                await settle_commit(asyncio.gather(*tuple(self.finalizers), return_exceptions=True))
            async with self.manager._activity.lock:
                if self.finalizers:
                    continue
                for job in tuple(self.jobs.values()):
                    row = self.manager._records.index[("executions", (job.execution_id,))]
                    if row.values["status"] not in TERMINAL:
                        if row.values["status"] == "queued":
                            await self.cancelled_records(job)
                            job.finished.set()
                        else:
                            await self.uncertain_records(job)
                if self.finalizers:
                    continue
                self.sealed = True
                break
        if self.scheduler:
            await asyncio.gather(self.scheduler, return_exceptions=True)
        if self.errors:
            raise self.errors[0]
