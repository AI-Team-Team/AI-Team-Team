"""One admitted continuing person, independent of memberships and observers."""

import asyncio
import contextvars

from pydantic import TypeAdapter

from ai_team_team.core.activity.contracts import (
    ActivityAdmission,
    ActivityView,
    OperationScope,
    PersonalScope,
)
from ai_team_team.core.exceptions import StateRestoreError

from .checkpoints import CheckpointMixin
from .context import ContextMixin
from .controls import ControlMixin
from .dependencies import InteractionDependencyMixin, WorkerResume
from .models import ModelRequestService
from .notifications import NotificationMixin
from .recovery import ActivityRecoveryMixin
from .runner import RunnerMixin
from .sleep import SleepMixin
from .values import ModelUnavailable, Session, SystemClock, capture, identifier, scope_fields


class PersonalActivityService(
    CheckpointMixin,
    ContextMixin,
    ControlMixin,
    InteractionDependencyMixin,
    NotificationMixin,
    RunnerMixin,
    SleepMixin,
    ActivityRecoveryMixin,
):
    """Runtime queues are disposable indexes over committed personal evidence."""

    def __init__(self, manager):
        self.manager = manager
        self.clock = SystemClock()
        self.current = contextvars.ContextVar(f"att_personal_activity_{id(manager)}", default=None)
        self.lock = asyncio.Lock()
        self.ready = asyncio.Queue()
        self.capacity = asyncio.Event()
        self.capacity.set()
        self.sessions = {}
        self.admissions = {}
        self.checkpoints = {}
        self.waiters = {}
        self.workers = set()
        self.suspended_workers = {}
        self.dispatch_tasks = set()
        self.tool_tasks = set()
        self.activating = {}
        self.timers = {}
        self.cooldown_deadlines = {}
        self.scheduler = None
        self.closing = False
        self.recovery_required = False
        self.fatal_errors = []
        self.models = ModelRequestService(self)

    @property
    def generation(self):
        return self.manager._resources.generation

    def check_open(self):
        self.manager._resources.check_authority()
        if (
            self.closing
            or self.manager._closing
            or self.manager._restore_in_progress
            or self.recovery_required
        ):
            raise RuntimeError("Personal activity admission is closed.")

    def require_agent(self, agent_id):
        agent = self.manager._agents_by_id.get(agent_id)
        if agent is None or agent.lifecycle_state != "active":
            raise PermissionError("Personal activity requires an active registered Agent.")
        if self.manager.supervisor.is_supervisory_agent(agent_id):
            raise PermissionError(
                "Audit-scoped activity requires its registered audit evidence profile."
            )
        return agent

    def validate_scope(self, agent_id, scope):
        scope = TypeAdapter(OperationScope).validate_python(scope)
        agent = self.require_agent(agent_id)
        if scope.kind == "agent_team":
            team = self.manager.teams.get(scope.team_id)
            if (
                team is None
                or team.team_kind != "ordinary"
                or agent not in team.members
                or getattr(team, "_lifecycle_state", "active") != "active"
            ):
                raise PermissionError(
                    "The selected activity scope requires current active team membership."
                )
        return scope

    def check_generation(self, session):
        self.manager._resources.check_authority()
        if self.closing or self.manager._closing or session.generation != self.generation:
            raise asyncio.CancelledError("The personal runtime generation is no longer active.")
        self.validate_scope(session.agent_id, session.scope)

    def team_for(self, session):
        return (
            self.manager.teams.get(session.scope.team_id)
            if session.scope.kind == "agent_team"
            else None
        )

    def register_clock(self, clock):
        if self.sessions or self.workers or self.timers or self.models.tasks:
            raise RuntimeError("Bind the runtime clock before activity or timers are admitted.")
        for name in ("monotonic", "wall_time", "sleep"):
            if not callable(getattr(clock, name, None)):
                raise TypeError("A runtime clock must implement monotonic, wall_time, and sleep.")
        self.clock = clock

    async def activate(self, agent_id, *, scope=None):
        async with self.lock:
            return await self._activate_locked(agent_id, scope=scope)

    async def _activate_locked(self, agent_id, *, scope=None):
        """Admission and arrival eligibility share the same mutation lock."""
        self.check_open()
        agent = self.require_agent(agent_id)
        scope = self.validate_scope(agent_id, scope if scope is not None else PersonalScope())
        previous = self.sessions.get(agent_id)
        if previous is not None and previous.active:
            return ActivityAdmission(
                admission_id=previous.admission_id,
                agent_id=agent_id,
                status="COALESCED",
                durability=self.manager.persistence_mode,
            )
        alias = self.manager.resolve_model_alias(agent.llm_client)
        unavailable = self.manager._records.index.get(("model_availability", (agent_id, alias)))
        if unavailable is not None and unavailable.values["status"] != "available":
            values = unavailable.values
            if values["status"] == "remediation_required":
                raise ModelUnavailable("The model requires Host remediation before admission.")
            earliest = values["earliest_admission_at"]
            if earliest is not None and earliest > self.clock.wall_time():
                raise ModelUnavailable(
                    "The provider recovery boundary has not elapsed.",
                    recoverable=True,
                    earliest=earliest,
                )
        live = self.models.live.get(agent_id)
        if live is not None and not live.done():
            raise ModelUnavailable(
                "A previous local model request has not stopped.", recoverable=True
            )
        marker = self.manager._records.index.get(("agent_activities", (agent_id,)))
        session = Session(
            agent_id,
            identifier("ADMISSION"),
            self.generation,
            scope=scope,
            context_version=marker.values["context_version"] if marker else 0,
        )
        if previous is not None:
            # Observers address accepted personal instructions, not a single
            # admission that may stop before that instruction is presented.
            session.interaction_waiters = previous.interaction_waiters
        records = [
            capture(
                self.manager,
                "activity_admissions",
                admission_id=session.admission_id,
                agent_id=agent_id,
                runtime_generation=session.generation,
                **scope_fields(scope),
                disposition="admitted",
                accepted_at=self.clock.wall_time(),
            ),
            self.marker(session),
        ]
        if previous is not None and previous.sleep_id:
            records.append(
                capture(
                    self.manager,
                    "sleep_plans",
                    sleep_id=previous.sleep_id,
                    status="expired"
                    if previous.sleep_deadline <= self.clock.monotonic()
                    else "cancelled",
                )
            )
        if unavailable is not None:
            records.append(
                capture(
                    self.manager,
                    "model_availability",
                    agent_id=agent_id,
                    model_alias=alias,
                    status="available",
                    reason="recovery_admitted",
                    earliest_admission_at=None,
                )
            )
        try:
            await self.commit(session, records, allow_closing=False)
        finally:
            if ("activity_admissions", (session.admission_id,)) in self.manager._records.index:
                self.sessions[agent_id] = session
                self.admissions[session.admission_id] = session
                timer = self.timers.pop(agent_id, None)
                if timer is not None and timer is not asyncio.current_task():
                    timer.cancel()
                self.enqueue(session)
        return ActivityAdmission(
            admission_id=session.admission_id,
            agent_id=agent_id,
            status="QUEUED",
            durability=self.manager.persistence_mode,
        )

    def inspect(self, agent_id):
        self.require_agent(agent_id)
        session = self.sessions.get(agent_id)
        if session is None:
            marker = self.manager._records.index.get(("agent_activities", (agent_id,)))
            return ActivityView(
                agent_id=agent_id,
                admission_id=None,
                scope=None,
                intent=marker.values["intent"] if marker else "idle",
                availability=marker.values["availability"] if marker else "ready",
            )
        return ActivityView(
            agent_id=agent_id,
            admission_id=session.admission_id,
            scope=session.scope,
            intent=self.manager._records.index[("agent_activities", (agent_id,))].values["intent"],
            availability=session.availability,
        )

    async def clear_model_unavailability(self, agent_id):
        """Host remediation clears a resource block, never usage or provider time."""
        if self.current.get() is not None or self.manager._active_tool_agent.get() is not None:
            raise PermissionError("Only the Host may clear model unavailability.")
        async with self.lock:
            self.check_open()
            agent = self.require_agent(agent_id)
            alias = self.manager.resolve_model_alias(agent.llm_client)
            live = self.models.live.get(agent_id)
            if live is not None and not live.done():
                raise ModelUnavailable(
                    "The previous local provider request is still live.", recoverable=True
                )
            row = self.manager._records.index.get(("model_availability", (agent_id, alias)))
            if row is None or row.values["status"] == "available":
                return
            earliest = row.values["earliest_admission_at"]
            if earliest is not None and earliest > self.clock.wall_time():
                raise ModelUnavailable(
                    "Host remediation cannot bypass a provider recovery boundary.",
                    recoverable=True,
                    earliest=earliest,
                )
            await self.manager._records.commit(
                (
                    capture(
                        self.manager,
                        "model_availability",
                        agent_id=agent_id,
                        model_alias=alias,
                        status="available",
                        reason="host_remediation",
                        earliest_admission_at=None,
                    ),
                )
            )
            self.manager._emit_callback(
                "on_system_event",
                "model_availability_cleared",
                {"agent_id": agent_id, "model_alias": alias},
            )
            session = self.sessions.get(agent_id)
            if session is not None and session.intent == "continuing":
                self.schedule_activation(agent_id)
            else:
                for notice in self.pending_notices(agent_id):
                    self.schedule_notice(notice.values["notification_id"])

    async def wait(self, admission_id, *, intent=None):
        if intent not in {None, "continuing", "idle", "sleep"}:
            raise ValueError("Unknown activity checkpoint intent.")
        if admission_id not in self.admissions:
            raise KeyError("Unknown activity admission.")
        checkpoint = self.checkpoints.get(admission_id)
        if checkpoint is not None and (intent is None or checkpoint.intent == intent):
            return checkpoint
        session = self.admissions[admission_id]
        if session.failure is not None:
            raise session.failure
        if self.closing:
            raise RuntimeError("The activity runtime is closed.")
        future = asyncio.get_running_loop().create_future()
        waiter = future, intent
        self.waiters.setdefault(admission_id, []).append(waiter)
        try:
            return await future
        finally:
            self.waiters[admission_id].remove(waiter)
            if not self.waiters[admission_id]:
                self.waiters.pop(admission_id)

    async def interact(self, agent, prompt, *, scope=None):
        """Observe a personal answer without stopping its continuing activity."""
        async with self.interaction_dependency(agent.agent_id):
            return await self._interact(agent, prompt, scope=scope)

    async def _interact(self, agent, prompt, *, scope=None):
        from ai_team_team.core.response import AgentTurnResult, AgentTurnStatus

        if self.require_agent(agent.agent_id) is not agent or not isinstance(prompt, str):
            raise PermissionError(
                "Personal interaction requires this manager's Agent and a text prompt."
            )
        scope = self.validate_scope(agent.agent_id, scope if scope is not None else PersonalScope())
        future = asyncio.get_running_loop().create_future()
        session, waiter = None, None

        def accepted(receipt):
            async def admit():
                nonlocal session, waiter
                try:
                    admission = await self.activate(agent.agent_id, scope=scope)
                    session = self.admissions[admission.admission_id]
                    if not future.done():
                        waiter = receipt.message_id, future
                        session.interaction_waiters.append(waiter)
                        if session.failure is not None:
                            future.set_exception(session.failure)
                except asyncio.CancelledError:
                    future.cancel()
                    raise
                except Exception as error:
                    if not future.done():
                        future.set_exception(error)
                    self.manager._emit_callback(
                        "on_system_event",
                        "activity_admission_deferred",
                        {"agent_id": agent.agent_id, "error_type": type(error).__name__},
                    )

            # Only local admission is detached from the observer, never its
            # model wait. Preserve the requested scope rather than letting a
            # generic arrival race admit the person in personal scope.
            task = asyncio.create_task(
                admit(), context=contextvars.Context(), name=f"att-interact-{agent.agent_id}"
            )
            self.dispatch_tasks.add(task)
            task.add_done_callback(self.dispatch_tasks.discard)

        try:
            await self.deliver_mail(
                agent.agent_id,
                message_type="personal_instruction",
                payload={"text": prompt},
                schedule=False,
                _on_commit=accepted,
            )
            answer, answer_team_id = await future
            return AgentTurnResult(
                agent_id=agent.agent_id,
                team_id=answer_team_id,
                status=AgentTurnStatus.COMPLETED,
                answer=answer,
            )
        finally:
            future.cancel()
            if not future.cancelled():
                future.exception()
            if waiter is not None:
                session.interaction_waiters.remove(waiter)

    def enqueue(self, session):
        if self.closing or session.queued or session.running or not session.active:
            return
        session.queued = True
        self.ready.put_nowait(session)
        if self.scheduler is None or self.scheduler.done():
            self.scheduler = asyncio.create_task(
                self.schedule(), context=contextvars.Context(), name="att-personal-scheduler"
            )

    async def schedule(self):
        while not self.closing:
            while (
                len(self.workers) - len(self.suspended_workers)
                >= self.manager.config.activity.max_concurrent_activities
            ):
                self.capacity.clear()
                await self.capacity.wait()
            session = await self.ready.get()
            session.queued = False
            self.ready.task_done()
            if isinstance(session, WorkerResume):
                self.resume_worker(session)
                continue
            if not session.active or self.sessions.get(session.agent_id) is not session:
                continue
            session.running = True
            task = asyncio.create_task(
                self.run(session),
                context=contextvars.Context(),
                name=f"att-person-{session.agent_id}",
            )
            self.workers.add(task)
            session.worker = task
            task.add_done_callback(self.worker_finished)

    def worker_finished(self, task):
        self.workers.discard(task)
        resume = self.suspended_workers.pop(task, None)
        if resume is not None:
            resume.future.cancel()
        self.capacity.set()
        if not task.cancelled():
            error = task.exception()
            if error is not None:
                self.manager.logger.error(
                    "Personal activity worker failed (%s).", type(error).__name__
                )
                from ai_team_team.core.exceptions import (
                    StatePersistenceError,
                    StateRestoreError,
                    DatabaseOwnershipError,
                )

                if isinstance(
                    error, (StatePersistenceError, StateRestoreError, DatabaseOwnershipError)
                ):
                    self.fatal_errors.append(error)

    def assert_restore_ready(self):
        if (
            self.workers
            or self.dispatch_tasks
            or self.models.tasks
            or self.tool_tasks
            or any(session.active for session in self.sessions.values())
        ):
            raise StateRestoreError(
                "Cannot restore while personal activity or its external waits are live."
            )

    async def close(self):
        self.closing = True
        if self.scheduler:
            self.scheduler.cancel()
        for task in tuple(self.timers.values()) + tuple(self.dispatch_tasks):
            task.cancel()
        self.models.close()
        for task in tuple(self.workers):
            task.cancel()
        if self.workers:
            # Runners do not retain unbounded provider waits, but their accepted
            # local transactions must finish without an arbitrary flush timeout.
            await asyncio.gather(*tuple(self.workers), return_exceptions=True)
        async with self.lock:
            uncertain = [
                capture(
                    self.manager,
                    "executions",
                    execution_id=row.values["execution_id"],
                    outcome_unconfirmed=1,
                    attention="required",
                )
                for row in self.manager._records.snapshot()
                if row.table_name == "executions"
                and row.values["status"] in {"queued", "running"}
                and row.values["agent_id"] in self.sessions
                and row.values["runtime_generation"]
                == self.sessions[row.values["agent_id"]].generation
            ]
            if uncertain:
                await self.manager._records.commit(uncertain, allow_closing=True)
            await self.sample_cooldowns()
        for session in self.sessions.values():
            if session.intent == "sleep":
                await self.sample_sleep(session)
            for _mail_id, future in tuple(session.interaction_waiters):
                if not future.done():
                    future.set_exception(RuntimeError("ATTManager closed before a personal response."))
        for values in self.waiters.values():
            for future, _intent in values:
                if not future.done():
                    future.set_exception(
                        RuntimeError("ATTManager closed before the requested checkpoint.")
                    )
        await asyncio.gather(
            *(
                task
                for task in (self.scheduler, *self.timers.values(), *self.dispatch_tasks)
                if task is not None
            ),
            return_exceptions=True,
        )
        if self.fatal_errors:
            raise self.fatal_errors[0]
