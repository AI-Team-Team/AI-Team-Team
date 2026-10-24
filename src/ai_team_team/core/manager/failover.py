"""Bounded personal resource decisions, independent of issuing call stacks."""

import asyncio
import contextvars

from pydantic import BaseModel, ConfigDict
from typing import Literal

from ..adapters import HandlerClientAdapter, ManagerDefaultClientAdapter
from ..communication import ApprovalPrincipal
from ..exceptions import RuntimeAdmissionClosedError
from .activity.values import capture, identifier
from .timing import wait_until


class ResourceDecisionResult(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    status: Literal["PENDING", "APPLIED", "UNAVAILABLE"]
    attempt_id: str | None = None
    model_alias: str | None = None
    reason: str = ""


class FailoverService:
    def __init__(self, manager):
        self.manager = manager
        self.lock = asyncio.Lock()
        self.tasks = {}

    def binding(self, alias):
        manager = self.manager
        if alias in manager.llm_clients:
            return manager.llm_clients[alias]
        if alias in manager.model_configs and manager.generator_handler:
            client = HandlerClientAdapter(alias, manager.generator_handler)
            client._supports_native = manager.model_configs[alias].get("supports_native_tool_calling") is True
            return client
        if alias == "default" and manager.generator_handler:
            return ManagerDefaultClientAdapter(manager)
        return None

    def candidates(self, old, required):
        aliases = sorted(set(self.manager.llm_clients) | set(self.manager.model_configs))
        result = []
        for alias in aliases:
            remaining = self.manager.token_budget.available(alias)
            if alias != old and self.binding(alias) is not None and (remaining is None or remaining >= required):
                result.append(alias)
        return result

    def track(self, key, coroutine):
        current = self.tasks.get(key)
        if self.manager._closing or current is not None and not current.done():
            coroutine.close()
            return
        task = asyncio.create_task(coroutine, context=contextvars.Context(), name=f"att-resource-{key}")
        self.tasks[key] = task
        self.manager._institutional_tasks.add(task)
        def finished(done):
            if self.tasks.get(key) is done:
                self.tasks.pop(key, None)
            self.manager._institutional_tasks.discard(done)
            if done.cancelled():
                return
            error = done.exception()
            if isinstance(error, RuntimeAdmissionClosedError):
                self.manager._emit_callback("on_system_event", "resource_decision_admission_deferred",
                    {"operation_key": key, "reason": "runtime_admission_closed"})
            elif error is not None:
                self.manager.logger.error("Resource decision failed (%s).", type(error).__name__)
        task.add_done_callback(finished)

    async def request(self, agent, team, error):
        manager = self.manager
        current = manager._active_tool_agent.get()
        if current is not None and current is not agent:
            raise PermissionError("A tool cannot change another person's model binding.")
        if manager._agents_by_id.get(agent.agent_id) is not agent or agent.lifecycle_state != "active":
            raise PermissionError("Resource remedies require this manager's active person.")
        if team is not None and (manager.teams.get(team.team_id) is not team or agent not in team.members
                or getattr(team, "_lifecycle_state", "active") != "active"):
            raise PermissionError("A resource scope must be a current active membership.")
        old = manager.resolve_runtime_model_alias(agent.llm_client)
        required = max(1, getattr(error, "required_tokens", 1))
        candidates = self.candidates(old, required)
        if not candidates or manager.config.failover_policy == "none":
            return ResourceDecisionResult(status="UNAVAILABLE", reason="No configured resource remedy is available.")
        if manager.config.failover_policy == "auto":
            from contextlib import AsyncExitStack
            async with AsyncExitStack() as gates:
                session = manager._activity.current.get()
                if session is None or session.agent_id != agent.agent_id:
                    await gates.enter_async_context(agent.invocation_guard())
                await gates.enter_async_context(agent.lifecycle_lock)
                await gates.enter_async_context(manager._activity.lock)
                candidates = self.candidates(old, required)
                if not candidates or agent.lifecycle_state != "active":
                    return ResourceDecisionResult(status="UNAVAILABLE", reason="No eligible live resource remains.")
                alias = candidates[0]
                dirty = manager._new_dirty_state()
                dirty["agents"].add(agent.agent_id)
                def authorized():
                    if (alias not in self.candidates(old, required)
                            or manager.resolve_runtime_model_alias(agent.llm_client) != old):
                        raise RuntimeError("The model or atomic quota changed before resource acceptance.")
                await manager._records.commit((), dirty=dirty, agent_models={agent.agent_id: (alias, self.binding(alias))},
                    authority_check=authorized)
            manager._emit_callback("on_system_event", "model_binding_changed",
                {"agent_id": agent.agent_id, "old_model": old, "model_alias": alias, "policy": "auto"})
            return ResourceDecisionResult(status="APPLIED", model_alias=alias)
        principal = team.organizational_parent if team is not None else None
        if principal is None:
            return ResourceDecisionResult(status="UNAVAILABLE", reason="No explicit organizational parent supplies resources.")
        electorate = manager._governance.electorate(principal)
        if not electorate or any(voter.agent_id == agent.agent_id for voter in electorate):
            return ResourceDecisionResult(status="UNAVAILABLE", reason="The required parent electorate cannot decide without self-reentry.")
        async with self.lock:
            existing = next((row for row in manager._records.snapshot() if row.table_name == "resource_decisions"
                and row.values["agent_id"] == agent.agent_id and row.values["status"] == "pending"), None)
            if existing is not None:
                return ResourceDecisionResult(status="PENDING", attempt_id=existing.values["attempt_id"])
            now = manager._activity.clock.wall_time()
            attempt_id = identifier("FAILOVER")
            row = capture(manager, "resource_decisions", attempt_id=attempt_id, agent_id=agent.agent_id,
                scope_team_id=team.team_id if team else None, exhausted_alias=old,
                scope_position_revision=team._position_revision,
                principal_agent_id=principal.principal_id if principal.kind == "agent" else None,
                principal_team_id=principal.principal_id if principal.kind == "agent_team" else None,
                candidates=candidates, required_tokens=required, created_at=now,
                deadline=now + manager.config.parent_failover_timeout_seconds, status="pending")

            def authorized():
                if (agent.lifecycle_state != "active" or agent not in team.members
                        or team.organizational_parent != principal
                        or team._position_revision != row.values["scope_position_revision"]
                        or manager.resolve_runtime_model_alias(agent.llm_client) != old
                        or any(voter.agent_id == agent.agent_id for voter in manager._governance.electorate(principal))):
                    raise PermissionError("The resource requester or explicit parent changed before admission.")

            try:
                await manager._records.commit((row,), operation_id=f"RESOURCE-{attempt_id}", authority_check=authorized)
            finally:
                if row.identity in manager._records.index:
                    self.arm_deadline(row)
                    self.track(f"prepare:{attempt_id}", self.prepare(attempt_id))
        return ResourceDecisionResult(status="PENDING", attempt_id=attempt_id)

    def arm_deadline(self, row):
        clock = self.manager._activity.clock
        deadline = clock.monotonic() + max(0.0, row.values["deadline"] - clock.wall_time())
        self.track(f"deadline:{row.values['attempt_id']}", self.expire_at(row.values["attempt_id"], deadline))

    async def prepare(self, attempt_id):
        row = self.manager._records.index[("resource_decisions", (attempt_id,))]
        if row.values["status"] != "pending":
            return
        principal = ApprovalPrincipal(kind="agent" if row.values["principal_agent_id"] else "agent_team",
            principal_id=row.values["principal_agent_id"] or row.values["principal_team_id"])
        await self.manager.broker.decision_provider.request_model_choice(principal, attempt_id,
            "Explicitly choose an eligible replacement model for resource request " + attempt_id,
            list(row.values["candidates"]), expires_at=row.values["deadline"])
        await self.resolve(attempt_id)

    async def expire_at(self, attempt_id, deadline):
        await wait_until(self.manager._activity.clock, deadline)
        await self.finish(attempt_id, "expired")

    async def finish(self, attempt_id, status):
        async with self.lock:
            row = self.manager._records.index[("resource_decisions", (attempt_id,))]
            if row.values["status"] != "pending":
                return
            await self.manager._records.commit((capture(self.manager, "resource_decisions", attempt_id=attempt_id,
                status=status, resolved_at=max(self.manager._activity.clock.wall_time(), row.values["created_at"])),), allow_closing=True)
        self.cancel_deadline(attempt_id)
        for stage in ("prepare", "apply"):
            task = self.tasks.get(f"{stage}:{attempt_id}")
            if task is not None and task is not asyncio.current_task() and not task.done():
                task.cancel()
        for case in tuple(self.manager._governance.cases.values()):
            if case.business_kind == "failover" and case.business_id == attempt_id and case.status == "PENDING":
                await self.manager._governance.expire(case.case_id, f"Resource attempt {status}.")

    def cancel_deadline(self, attempt_id):
        task = self.tasks.get(f"deadline:{attempt_id}")
        if task is not None and task is not asyncio.current_task() and not task.done():
            task.cancel()

    async def resolve(self, attempt_id):
        row = self.manager._records.index.get(("resource_decisions", (attempt_id,)))
        if row is None or row.values["status"] != "pending":
            return
        principal = ApprovalPrincipal(kind="agent" if row.values["principal_agent_id"] else "agent_team",
            principal_id=row.values["principal_agent_id"] or row.values["principal_team_id"])
        case = self.manager._governance.latest("failover", attempt_id, principal)
        if case is None or not self.manager._governance.electorate_valid(case):
            return
        if case.status == "DENIED":
            await self.finish(attempt_id, "denied")
        elif case.status == "APPROVED":
            self.track(f"apply:{attempt_id}", self.apply(attempt_id, case))

    async def apply(self, attempt_id, case):
        manager = self.manager
        row = manager._records.index[("resource_decisions", (attempt_id,))]
        agent = manager._agents_by_id.get(row.values["agent_id"])
        if agent is None:
            await self.finish(attempt_id, "cancelled")
            return
        async with agent.invocation_guard(), agent.lifecycle_lock, self.lock, manager._activity.lock:
            row = manager._records.index[("resource_decisions", (attempt_id,))]
            if row.values["status"] != "pending":
                return
            alias = manager.broker.decision_provider.outcome(case).selected_value
            team = manager.teams.get(row.values["scope_team_id"])
            expected = ApprovalPrincipal(kind="agent" if row.values["principal_agent_id"] else "agent_team",
                principal_id=row.values["principal_agent_id"] or row.values["principal_team_id"])
            live = manager._activity.models.live.get(agent.agent_id)
            def eligible():
                return (not manager._closing and agent.lifecycle_state == "active" and team is not None
                    and getattr(team, "_lifecycle_state", "active") == "active"
                    and agent in team.members and team.organizational_parent == expected
                    and team._position_revision == row.values["scope_position_revision"]
                    and manager.resolve_runtime_model_alias(agent.llm_client) == row.values["exhausted_alias"]
                    and manager._governance.latest("failover", attempt_id, expected) is case
                    and row.values["decision_case_id"] == case.case_id
                    and manager._governance.electorate_valid(case) and (live is None or live.done())
                    and alias in self.candidates(row.values["exhausted_alias"], row.values["required_tokens"]))
            now = manager._activity.clock.wall_time()
            status = "expired" if now >= row.values["deadline"] else "applied" if eligible() else "cancelled"
            dirty = manager._new_dirty_state()
            if status == "applied":
                dirty["agents"].add(agent.agent_id)
            def authorized():
                if status == "applied" and (not eligible() or manager._activity.clock.wall_time() >= row.values["deadline"]):
                    raise PermissionError("The resource authority, deadline, or atomic quota changed before model publication.")

            operation_id = f"RESOURCE-APPLY-{attempt_id}"
            try:
                await manager._records.commit((capture(manager, "resource_decisions", attempt_id=attempt_id,
                    status=status, selected_alias=alias if status == "applied" else None, resolved_at=now),),
                    dirty=dirty, agent_models={agent.agent_id: (alias, self.binding(alias))} if status == "applied" else None,
                    operation_id=operation_id, authority_check=authorized)
            finally:
                if operation_id in manager._records.receipts:
                    if status == "applied":
                        manager._activity.schedule_activation(agent.agent_id)
                    self.cancel_deadline(attempt_id)
                    manager._emit_callback("on_system_event", "resource_decision_resolved",
                        {"attempt_id": attempt_id, "agent_id": agent.agent_id, "status": status})

    async def interrupt_pending(self):
        tasks = [task for task in tuple(self.tasks.values()) if task is not asyncio.current_task() and not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for row in self.manager._records.snapshot():
            if row.table_name == "resource_decisions" and row.values["status"] == "pending":
                await self.finish(row.values["attempt_id"], "interrupted")
