"""Admission precedes dispatch; detachment never owns or cancels the worker."""

import asyncio
import contextvars
import hashlib
import inspect
import json
import os
import copy

from ai_team_team.core.exceptions import ToolArgumentError, ToolBusinessError
from ai_team_team.core.execution import ResourceClaim
from ai_team_team.core.response import ToolResult, ToolResultStatus
from ai_team_team.core.tool_runtime import ToolExecutor
from ai_team_team.database.persistence.receipts import settle_commit
from ai_team_team.database.persistence.records import thaw
from ..activity.values import capture, identifier, scope_fields
from ..timing import wait_until
from .resources import builtin_resources
from .values import CallableExecutor, ExecutorCall, Job


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


class DispatchMixin:
    def resolve_resources(self, context, tool, args, kwargs, *, owner=None):
        if owner is None:
            owner = self.check(context, team_required=tool.execution_contract.required_scope == "agent_team")
        elif tool.execution_contract.required_scope == "agent_team":
            self.manager._activity.validate_scope(owner.agent_id, context.scope)
        bound = tool._signature.bind(*thaw(args), **thaw(kwargs))
        bound.apply_defaults()
        claims, sources = (), ()
        if tool._builtin:
            claims, sources = builtin_resources(self.manager, owner, context.scope, tool.name, bound.arguments)
        elif tool.resource_resolver is not None:
            resolved = tool.resource_resolver(context.scope, dict(bound.arguments))
            if inspect.isawaitable(resolved):
                if inspect.iscoroutine(resolved):
                    resolved.close()
                raise ToolArgumentError("Resource resolvers must be synchronous and side-effect free.")
            claims = tuple(ResourceClaim.model_validate(claim) for claim in resolved)
        elif tool.execution_contract.effects == ("self_modification",):
            # The existing personal invocation already serializes self-only
            # controls. They cannot claim shared filesystem access implicitly.
            sources = ({"kind": "external", "executor": tool.executor},)
        else:
            claims = (ResourceClaim(namespace="global", resource_id="undeclared-shared-resource",
                access="read" if tool.execution_contract.effects == ("read_only",) else "write"),)
        from ai_team_team.doc_library import DocumentLibrary
        for claim in claims:
            if claim.namespace == "library":
                if DocumentLibrary._normalize_path(claim.path or "/", allow_root=True) != claim.path:
                    raise ToolArgumentError("Library resource claims require canonical paths.")
                if claim.access == "read" and not tool._builtin:
                    sources = (*sources, {"kind": "library", "lib_id": claim.resource_id,
                        "path": claim.path, "scope_team_id": getattr(context.scope, "team_id", None)})
            elif not tool._builtin:
                sources = (*sources, {"kind": "external", "executor": tool.executor})
        physical = [claim.model_copy(update={"path": os.path.normcase(claim.path).replace("\\", "/")})
                    if claim.namespace == "library" else claim for claim in claims]
        return tuple(sorted(set(physical), key=lambda item: (item.namespace, item.resource_id, item.path, item.access, item.subtree))), sources

    async def admit(self, context, tool, args, kwargs, *, call_id, visibility="foreground", description="", labels=(), enqueue=True):
        tool = copy.copy(tool)
        owner = self.check(context, team_required=tool.execution_contract.required_scope == "agent_team")
        self.validate_binding(tool)
        tool.validate_arguments(list(args), dict(kwargs))
        if type(description) is not str or not isinstance(labels, (tuple, list)) or any(type(label) is not str for label in labels):
            raise ToolArgumentError("Task descriptions and labels must be text.")
        args, kwargs = self.immutable_arguments(args, kwargs)
        claims, sources = self.resolve_resources(context, tool, args, kwargs)
        execution_id = identifier("EXECUTION")
        retry = {"policy": self.manager.config.tool_execution_retry_policy,
                 "max_retries": self.manager.config.max_tool_execution_retries,
                 "backoff": self.manager.config.tool_execution_retry_backoff_factor, "retry_safe": tool.retry_safe}
        job = Job(execution_id, context, tool, args, kwargs,
                  call_id or identifier("MODEL-CALL" if context.invocation_id else "HOST-CALL"), claims, sources, retry)
        admission = await self.admission_records(context, tool, args, kwargs, execution_id=execution_id,
            call_id=job.call_id, visibility=visibility, description=description, labels=labels, sources=sources)
        operation_id = identifier("EXECUTION-ADMISSION")
        try:
            await self.commit_admission(job, owner, admission, operation_id, enqueue=enqueue)
        except asyncio.CancelledError:
            if not enqueue and execution_id in self.jobs:
                with self.manager._resources.settlement():
                    await self.request_cancel(execution_id, actor=owner)
            raise
        return job

    async def commit_admission(self, job, owner, admission, operation_id, *, enqueue):
        context, tool, execution_id = job.context, job.tool, job.execution_id
        async with owner.lifecycle_lock, self.manager._activity.lock:
            self.check(context, team_required=tool.execution_contract.required_scope == "agent_team")
            cooling = self.manager._records.index.get(("tool_cooldowns", (owner.agent_id, tool.name)))
            if cooling is not None and self.manager._activity.cooldown_remaining(cooling) > 0:
                raise ToolBusinessError("The tool is cooling; no new execution was admitted.", error_kind="tool_cooldown")
            records = admission
            if ("agent_activities", (owner.agent_id,)) not in self.manager._records.index:
                records = (*records, capture(self.manager, "agent_activities", agent_id=owner.agent_id,
                    intent="idle", availability="ready", admission_id=None, arrival_generation=0,
                    presentation_generation=0, context_version=0))
            try:
                await self.manager._records.commit(records, operation_id=operation_id)
            finally:
                if operation_id in self.manager._records.receipts:
                    self.jobs[execution_id] = job
                    if enqueue:
                        self.enqueue(job)
                    else:
                        # A cancelled observer must not leave an accepted
                        # coordinated admission eligible for later dispatch.
                        job.finished.set()

    def worker_finished(self, task):
        self.tasks.discard(task)
        job = self.task_jobs.pop(task, None)
        if job is not None:
            job.finished.set()
            self.release_job(job)
        if not task.cancelled():
            error = task.exception()
            if error is not None:
                from ai_team_team.core.exceptions import ATTException
                if isinstance(error, ATTException):
                    self.remember_error(error)

    async def run(self, job, *, coordinated=False):
        token = self.current.set(job) if not coordinated else None
        resource_token = self.resource_job.set(job)
        job.finished.clear()
        try:
            with self.context(job.context, job.execution_id), self.manager._resources.execution() as authority:
                job.authority = authority
                async with self.resources.hold(job.execution_id, job.claims):
                    self.check(job.context, team_required=job.tool.execution_contract.required_scope == "agent_team")
                    if job.cancellation_requested:
                        return

                    async def before_attempt(index):
                        self.check(job.context, team_required=job.tool.execution_contract.required_scope == "agent_team")
                        current_claims, _sources = self.resolve_resources(job.context, job.tool, job.args, job.kwargs)
                        if current_claims != job.claims or _sources != job.sources:
                            raise ToolBusinessError("Resource bindings changed after admission; no new target was dispatched.", error_kind="resource_binding_changed")
                        async with self.manager._activity.lock:
                            row = self.manager._records.index[("executions", (job.execution_id,))]
                            started = row.values["started_at"]
                            records = (capture(self.manager, "executions", execution_id=job.execution_id,
                                status="running", started_at=started if started is not None else max(self.clock.wall_time(), row.values["created_at"])),
                                capture(self.manager, "execution_attempts", attempt_id=identifier("ATTEMPT"),
                                    execution_id=job.execution_id, attempt_index=index, retry_contract=job.retry,
                                    started_at=self.clock.wall_time(), dispatched=1))
                            await self.manager._records.commit(records)
                        self.validate_bindings(job)
                        job.attempts = index
                        if job.started_monotonic is None:
                            job.started_monotonic = self.clock.monotonic()
                            job.started.set()
                            self.start_health_monitor(job)

                    async def invoke(*args, **kwargs):
                        call = ExecutorCall(job.execution_id, job.context.agent_id, job.context.scope,
                                            job.tool, tuple(args), kwargs,
                                            lambda health, kind, evidence=None: self.report_health(job.execution_id, health, kind, evidence))
                        binding = self.bindings[job.tool.executor]
                        return await (binding.execute(call, job) if isinstance(binding, CallableExecutor)
                                      else binding.execute(call))

                    executor = ToolExecutor(self.manager._active_team.get(), self.actor(), self.manager)
                    job.result = await executor.execute(job.tool.name, thaw(job.args), thaw(job.kwargs),
                        call_id=job.call_id, invocation_id=job.execution_id, tools={job.tool.name: job.tool},
                        before_attempt=before_attempt, invoke=invoke, retry_config=job.retry, retry_sleep=self.clock.sleep)
                    job.result._execution_id = job.execution_id
                    if self.manager._closed or self.sealed:
                        return
                    if not self.closing and job.context.generation != self.manager._resources.generation:
                        raise PermissionError("An obsolete executor cannot publish into the new runtime.")
                    job.result = await self.finish_result(job, job.result)
        except asyncio.CancelledError as error:
            job.error = error
            if not self.manager._closed and not self.sealed:
                await self.interrupted(job)
            if coordinated:
                raise
        except BaseException as error:
            job.error = error
            if not self.manager._closed and not self.sealed:
                await self.interrupted(job)
            raise
        finally:
            if token is not None:
                self.current.reset(token)
            self.resource_job.reset(resource_token)
            job.finished.set()
            if job.health_task is not None:
                job.health_task.cancel()

    async def observe(self, job):
        observer = asyncio.current_task()
        self.observers[observer] = job
        async def wait_started():
            await job.started.wait()
        started = asyncio.create_task(wait_started())
        finished = asyncio.create_task(job.finished.wait())
        timer = None
        try:
            await asyncio.wait((started, finished), return_when=asyncio.FIRST_COMPLETED)
            if not job.finished.is_set() and job.tool.execution_contract.background_allowed:
                deadline = job.started_monotonic + self.manager.config.executions.automatic_detachment_seconds
                timer = asyncio.create_task(wait_until(self.clock, deadline))
                await asyncio.wait((finished, timer), return_when=asyncio.FIRST_COMPLETED)
                async with self.manager._activity.lock:
                    if not job.finished.is_set():
                        row = self.manager._records.index[("executions", (job.execution_id,))]
                        if row.values["status"] not in {"completed", "failed", "cancelled"}:
                            await self.manager._records.commit((capture(self.manager, "executions",
                                execution_id=job.execution_id, visibility="detached"),))
                            result = ToolResult(job.call_id, job.tool.name, self.handle(job).model_dump_json())
                            result._background_handle = True
                            result._execution_id = job.execution_id
                            return result
            await finished
            if job.error is not None:
                raise job.error
            return job.result
        except asyncio.CancelledError:
            if not self.closing and not self.manager._closing:
                with self.manager._resources.settlement():
                    await self.request_cancel(job.execution_id, actor=self.manager._agents_by_id[job.context.agent_id])
                if job.task is not None and not job.task.done():
                    await asyncio.wait((job.task,), timeout=self.manager.config.executions.cancellation_grace_seconds)
            raise
        finally:
            self.observers.pop(observer, None)
            for task in (started, finished, timer):
                if task is not None and not task.done():
                    task.cancel()
