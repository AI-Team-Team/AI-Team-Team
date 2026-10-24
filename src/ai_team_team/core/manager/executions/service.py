"""One execution owner survives foreground waits, not runtime replacement."""

import asyncio
import contextvars
import inspect
from collections import deque
from contextlib import contextmanager

from ai_team_team.core.activity.contracts import BackgroundTaskHandle, PersonalScope
from ai_team_team.core.exceptions import StateRestoreError, ToolArgumentError, ToolPermissionError
from ai_team_team.core.response import ToolResult
from ai_team_team.database.persistence.records import freeze

from .controls import ControlMixin
from .audit import AuditExecutionMixin
from .dispatch import DispatchMixin
from .queries import QueryMixin
from .outcomes import OutcomeMixin
from .health import HealthMixin
from .evidence import EvidenceMixin
from .resources import ResourceCoordinator, conflict
from .values import CallableExecutor, ExecutionContext


class ExecutionService(AuditExecutionMixin, DispatchMixin, ControlMixin, QueryMixin, OutcomeMixin, HealthMixin, EvidenceMixin):
    def __init__(self, manager):
        self.manager = manager
        self.jobs = {}
        self.tasks = set()
        self.finalizers = set()
        self.bindings = {"callable": CallableExecutor()}
        self.current = contextvars.ContextVar(f"att_execution_{id(manager)}", default=None)
        self.resource_job = contextvars.ContextVar(f"att_execution_resources_{id(manager)}", default=None)
        self.lock = asyncio.Lock()
        self.ready = deque()
        self.active_jobs = set()
        self.wakeup = asyncio.Event()
        self.scheduler = None
        self.task_jobs = {}
        self.observers = {}
        self.stop_tasks = {}
        self.resources = ResourceCoordinator()
        self.closing = False
        self.sealed = False
        self.errors = []
        self.cursors = {}

    @property
    def clock(self):
        return self.manager._activity.clock

    def actor(self, actor=None):
        self.manager._resources.check_authority()
        current = self.manager._active_tool_agent.get()
        if current is not None:
            if actor is not None and actor is not current:
                raise PermissionError("An invocation cannot select another execution owner.")
            actor = current
        if actor is None or self.manager._agents_by_id.get(actor.agent_id) is not actor:
            raise PermissionError("Task access requires the registered owner.")
        return self.manager._activity.require_agent(actor.agent_id)

    def check(self, context, *, team_required=False):
        self.manager._resources.check_authority()
        if self.closing or self.manager._closing or self.manager._restore_in_progress or context.generation != self.manager._resources.generation:
            raise PermissionError("The execution runtime is no longer active.")
        owner = self.manager._activity.require_agent(context.agent_id)
        if team_required:
            if context.scope.kind != "agent_team":
                raise PermissionError("This execution requires its original AgentTeam scope.")
            self.manager._activity.validate_scope(context.agent_id, context.scope)
        return owner

    def check_model_wait(self):
        if self.current.get() is not None:
            raise ToolPermissionError("Executors must send addressed mail instead of waiting on personal model activity.")
        job = self.resource_job.get()
        if job is not None and job.claims:
            raise ToolPermissionError("Personal coordination cannot wait on nested model activity while holding shared resource reservations; use addressed mail or a source-free foreground self-modification control.")

    @contextmanager
    def context(self, context, execution_id):
        owner = self.check(context)
        team = self.manager.teams.get(getattr(context.scope, "team_id", None))
        tokens = [(self.manager._active_tool_agent, self.manager._active_tool_agent.set(owner)),
                  (self.manager._active_team, self.manager._active_team.set(team)),
                  (self.manager._active_tool_invocation_id, self.manager._active_tool_invocation_id.set(execution_id))]
        try:
            yield
        finally:
            for variable, token in reversed(tokens):
                variable.reset(token)

    def register_binding(self, name, executor):
        if self.manager._active_tool_agent.get() is not None:
            raise PermissionError("Only the Host registers executors.")
        if type(name) is not str or not name.strip() or name in self.bindings:
            raise ValueError("An executor requires a unique nonblank name.")
        if not inspect.iscoroutinefunction(getattr(executor, "execute", None)):
            raise ValueError("A registered executor must implement async execute(call).")
        self.bindings[name] = executor

    def validate_binding(self, tool):
        binding = self.bindings.get(tool.executor)
        if binding is None:
            raise ValueError(f"Executor {tool.executor!r} is not registered.")
        cancellation = tool.execution_contract.cancellation
        if cancellation in {"provider", "isolated"} and not callable(getattr(binding, "cancel", None)):
            raise ValueError("The declared executor stop capability requires a cancel hook.")
        if cancellation == "cooperative" and tool.executor == "callable" and not inspect.iscoroutinefunction(tool.func):
            raise ValueError("Synchronous callables cannot promise coroutine cancellation.")

    async def start(self, tool_name, arguments, *, actor=None, scope=None, description="", labels=()):
        owner = self.actor(actor)
        session = self.manager._activity.current.get()
        if session is not None:
            if scope is not None or session.agent_id != owner.agent_id:
                raise ToolPermissionError("A tool cannot override its captured execution scope.")
            scope = session.scope
        else:
            scope = self.manager._activity.validate_scope(owner.agent_id, scope or PersonalScope())
        context = ExecutionContext(owner.agent_id, session.invocation_id if session else None,
                                   self.manager._resources.generation, scope)
        team = self.manager.teams.get(getattr(scope, "team_id", None))
        tools = self.manager.get_available_tools(team, owner)
        tool = tools.get(tool_name)
        if tool is None or not tool.execution_contract.background_allowed:
            raise ToolPermissionError("This registered operation is not available for background execution.")
        if type(arguments) is not dict:
            raise ToolArgumentError("Background arguments must be a JSON object.")
        parent = self.manager._records.index.get(("executions", (self.manager._active_tool_invocation_id.get(),))) if session is not None else None
        call_id = parent.values["call_id"] if parent is not None else None
        job = await self.admit(context, tool, (), arguments, call_id=call_id,
                               visibility="explicit_background", description=description, labels=labels)
        return self.handle(job)

    def handle(self, job):
        row = self.manager._records.index[("executions", (job.execution_id,))]
        return BackgroundTaskHandle(execution_id=job.execution_id,
            durability=self.manager.persistence_mode, state_version=row.version)

    async def execute(self, session, name, args, kwargs, *, call_id, tools):
        if session.audit_profile is not None:
            return await self.execute_audit_profile(session, name, args, kwargs, call_id=call_id, tools=tools)
        tool = tools.get(name)
        if tool is None:
            from ai_team_team.core.tool_runtime import ToolExecutor
            return await ToolExecutor(self.manager._activity.team_for(session),
                self.manager._activity.require_agent(session.agent_id), self.manager).execute(
                    name, args, kwargs, call_id=call_id, tools=tools)
        if not tool.execution_contract.background_allowed:
            return await self.execute_coordinated(session, tool, args, kwargs, call_id=call_id)
        from ai_team_team.core.response import ToolResultStatus
        from ai_team_team.core.exceptions import ToolBusinessError
        try:
            context = ExecutionContext(session.agent_id, session.invocation_id, session.generation, session.scope)
            job = await self.admit(context, tool, args, kwargs, call_id=call_id)
            return await self.observe(job)
        except ToolArgumentError as error:
            return ToolResult(call_id, name, str(error), status=ToolResultStatus.INVALID_ARGUMENTS,
                              error_kind=error.error_kind or "argument_validation")
        except PermissionError as error:
            return ToolResult(call_id, name, str(error), status=ToolResultStatus.DENIED,
                              error_kind="permission_denied")
        except ToolBusinessError as error:
            return ToolResult(call_id, name, str(error), status=ToolResultStatus.BUSINESS_ERROR,
                              error_kind=error.error_kind or "business_error")

    async def execute_coordinated(self, session, tool, args, kwargs, *, call_id):
        """Keep the personal Session without bypassing the registered contract."""
        from ai_team_team.core.tool_runtime import ToolExecutor
        from ai_team_team.core.exceptions import ToolBusinessError
        context = ExecutionContext(session.agent_id, session.invocation_id, session.generation, session.scope)
        try:
            job = await self.admit(context, tool, args, kwargs, call_id=call_id, enqueue=False)
        except (ToolArgumentError, ToolPermissionError, PermissionError, ToolBusinessError) as error:
            return ToolExecutor.failure_result(error, call_id=call_id, tool_name=tool.name)
        job.task = asyncio.current_task()
        try:
            await self.run(job, coordinated=True)
            if job.error is not None:
                raise job.error
            result = job.result
            if not result.failed:
                result._chat_read_acknowledgement = session.prepared_chat_reads.get(job.execution_id)
                if tool._builtin and tool.name == "start_background_task":
                    result._background_handle = True
            return result
        finally:
            session.prepared_chat_reads.pop(job.execution_id, None)
            self.release_job(job)

    def validate_bindings(self, job, *, library=None, method=None, paths=()):
        """Validate aliases and the actual physical footprint at one resource boundary."""
        owner = self.manager._agents_by_id.get(job.context.agent_id)
        if owner is None or owner.lifecycle_state != "active":
            raise PermissionError("The captured execution owner is no longer active.")
        from ai_team_team.core.exceptions import ToolBusinessError
        try:
            claims, sources = self.resolve_resources(job.context, job.tool, job.args, job.kwargs, owner=owner)
        except (PermissionError, ToolPermissionError, ToolBusinessError, FileNotFoundError, KeyError, ValueError) as error:
            raise PermissionError("The captured resource binding is no longer authorized.") from error
        if claims != job.claims or sources != job.sources:
            raise PermissionError("Resource bindings changed after admission; no new target is authorized.")
        if library is None:
            return
        from ai_team_team.doc_library import DocumentLibrary
        import os
        write = method in {"write_file", "write_file_atomic", "delete_file", "move_file", "replace_all_files"}
        for path in paths:
            clean = os.path.normcase(DocumentLibrary._normalize_path(path, allow_root=True)).replace("\\", "/")
            if not any((claim.namespace == "global" or claim.namespace == "library"
                        and claim.resource_id == library.lib_id
                        and (claim.path == clean or claim.subtree and (not claim.path or clean.startswith(claim.path + "/"))))
                       and (not write or claim.access == "write") for claim in job.claims):
                raise PermissionError("The actual managed resource is outside this execution's reservation.")

    def assert_restore_ready(self):
        if any(not job.finished.is_set() or job.pending_threads for job in self.jobs.values()) or self.tasks or self.finalizers:
            raise StateRestoreError("Cannot restore while local executors or their outcome commits are live.")

    def reset_after_restore(self):
        self.jobs.clear()
        self.cursors.clear()

    def scrub_transient_results(self, owner, invocation_id):
        if invocation_id is None:
            return
        for job in self.jobs.values():
            if (job.context.agent_id == owner and job.tool.result_storage == "transient"
                    and job.finished.is_set() and (job.context.invocation_id == invocation_id
                    or job.transient_delivery_invocation == invocation_id)):
                job.result = None
                job.thread_outcome = None
                job.outcome_task = None

    def enqueue(self, job):
        self.ready.append(job)
        self.wakeup.set()
        if self.scheduler is None or self.scheduler.done():
            self.scheduler = asyncio.create_task(self.schedule(), context=contextvars.Context(), name="att-execution-scheduler")

    async def schedule(self):
        while not self.closing:
            self.wakeup.clear()
            blocked = []
            for job in tuple(self.ready):
                if job.cancellation_requested:
                    self.ready.remove(job)
                    continue
                if len(self.active_jobs) >= self.manager.config.executions.max_concurrent_executions:
                    break
                if any(conflict(claim, previous) for claim in job.claims for previous in blocked):
                    blocked.extend(job.claims)
                    continue
                if not self.resources.try_claim(job.execution_id, job.claims):
                    blocked.extend(job.claims)
                    continue
                self.ready.remove(job)
                self.active_jobs.add(job.execution_id)
                job.task = asyncio.create_task(self.run(job), context=contextvars.Context(), name=f"att-executor-{job.execution_id}")
                self.tasks.add(job.task)
                self.task_jobs[job.task] = job
                job.task.add_done_callback(self.worker_finished)
            await self.wakeup.wait()

    def release_job(self, job):
        if job.pending_threads:
            for thread in tuple(job.pending_threads):
                thread.add_done_callback(lambda _done, job=job: self.release_job(job))
            return
        self.resources.release(job.execution_id)
        self.active_jobs.discard(job.execution_id)
        self.wakeup.set()
        if (job.awaiting_thread_result and job.thread_outcome is not None and not job.late_settlement_started
                and not self.manager._closed and not self.sealed
                and (self.closing or job.context.generation == self.manager._resources.generation)):
            job.late_settlement_started = True
            task = asyncio.create_task(self.settle_thread_result(job), context=contextvars.Context(), name="att-late-executor-result")
            self.finalizers.add(task)
            task.add_done_callback(self.finalizer_finished)
        elif not job.late_settlement_started:
            self.clear_inputs(job)

    def finalizer_finished(self, task):
        self.finalizers.discard(task)
        if not task.cancelled() and task.exception() is not None:
            self.remember_error(task.exception())

    def remember_error(self, error):
        if not any(previous is error for previous in self.errors):
            self.errors.append(error)

    async def settle_thread_result(self, job):
        from ai_team_team.core.tool_runtime import ToolExecutor
        try:
            success, value = job.thread_outcome
            result = (ToolResult(job.call_id, job.tool.name, job.tool.serialize_result(value), attempts=job.attempts)
                if success else ToolExecutor.failure_result(value, call_id=job.call_id,
                    tool_name=job.tool.name, attempts=job.attempts))
            job.result, job.error = await self.finish_result(job, result), None
        except BaseException as error:
            job.error = error
            raise
        finally:
            self.clear_inputs(job)

    @staticmethod
    def clear_inputs(job):
        job.args, job.kwargs = (), freeze({})

    @staticmethod
    def immutable_arguments(args, kwargs):
        try:
            return freeze(tuple(args)), freeze(kwargs)
        except ValueError as error:
            raise ToolArgumentError("Execution inputs must contain finite JSON values.") from error
