"""Explicit-parent requests and receipt-owned organizational publication."""

import asyncio
import contextvars
from contextlib import asynccontextmanager
import hashlib
import json

from ..agent import Agent
from ..team import AgentTeam
from ..communication import ApprovalPrincipal
from ..governance import MigrationOperationResult, MigrationRequest
from ..organization import ancestry, principal_for
from .activity.values import capture, identifier


class MigrationService:
    def __init__(self, manager):
        self.manager = manager
        self._published_requests = {}
        self._candidate_requests = contextvars.ContextVar(f"att-migration-candidate-{id(self)}", default=None)
        self.lock = asyncio.Lock()
        self.cooldown_deadlines = {}

    @property
    def requests(self):
        candidate = self._candidate_requests.get()
        return candidate if candidate is not None else self._published_requests

    def publish(self, candidate):
        self._published_requests = candidate

    @asynccontextmanager
    async def stage(self):
        if self._candidate_requests.get() is not None:
            raise RuntimeError("Topology request transactions cannot be nested.")
        candidate = dict(self._published_requests)
        token = self._candidate_requests.set(candidate)
        try:
            yield candidate
        finally:
            self._candidate_requests.reset(token)

    def restore(self, rows):
        self._published_requests = {item.request_id: item for item in
            (MigrationRequest.model_validate(row, strict=False) for row in rows)}
        self.cooldown_deadlines.clear()

    @staticmethod
    def result(item):
        return MigrationOperationResult(status=item.status, request_id=item.request_id, reason=item.reason)

    def actor_check(self, team):
        actor = self.manager._active_tool_agent.get()
        if actor is not None and (self.manager._active_team.get() is not team
                or self.manager._agents_by_id.get(actor.agent_id) is not actor
                or actor.lifecycle_state != "active" or actor not in team.members):
            raise PermissionError("Only a current member acting for this AgentTeam may change its position.")

    def route(self, team, target, policy, operation):
        from ..organization import migration_route
        return migration_route(team.team_id, principal_for(target),
            {owner: node.organizational_parent for owner, node in self.manager.teams.items()},
            {owner: node._position_revision for owner, node in self.manager.teams.items()}, policy, operation)

    @staticmethod
    def fingerprint(evidence):
        return hashlib.sha256(json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def remaining_cooldown(self, team_id):
        row = self.manager._records.index.get(("team_position_cooldowns", (team_id,)))
        if row is None:
            return 0.0
        clock = self.manager._activity.clock
        if row.values["accounting_mode"] == "wall_time":
            return max(0.0, row.values["deadline"] - clock.wall_time())
        deadline = self.cooldown_deadlines.setdefault(team_id, clock.monotonic() + row.values["remaining_seconds"])
        return max(0.0, deadline - clock.monotonic())

    async def sample_cooldowns(self):
        rows = [capture(self.manager, "team_position_cooldowns", team_id=row.values["team_id"],
                    remaining_seconds=self.remaining_cooldown(row.values["team_id"]), sampled_at=self.manager._activity.clock.wall_time())
                for row in self.manager._records.snapshot() if row.table_name == "team_position_cooldowns"
                and row.values["accounting_mode"] == "remaining"]
        if rows:
            await self.manager._records.commit(rows, allow_closing=True)

    def validate(self, team, target, original, *, operation, reservation=None):
        manager = self.manager
        if team is None:
            return "The moving AgentTeam is missing."
        try:
            manager._topology.require_available(team, reservation=reservation)
            if target is not None:
                manager._topology.resolve_parent(target)
        except (ValueError, TypeError) as error:
            return str(error)
        if team.organizational_parent != original:
            return "The original organizational parent changed."
        if operation == "voluntary_detachment" and not manager.config.allow_unilateral_detachment:
            return "The Host has disabled unilateral detachment."
        if operation == "migration" and not manager.config.enable_migration:
            return "The Host has disabled parent-to-parent migration."
        if operation != "parent_loss" and self.remaining_cooldown(team.team_id) > 0:
            return "This AgentTeam's ten-minute own-position cooldown has not elapsed."
        if isinstance(target, AgentTeam):
            try:
                if principal_for(team) in ancestry(target.team_id,
                        {key: node.organizational_parent for key, node in manager.teams.items()}):
                    return "The requested parent would create a topology cycle."
            except ValueError as error:
                return str(error)
        return None

    async def negotiate_and_execute_migration(self, team, target_parent, rationale):
        manager = self.manager
        if manager._closing or manager._restore_in_progress:
            raise RuntimeError("Topology request admission is closed.")
        if not isinstance(rationale, str):
            raise TypeError("Migration rationale must be text.")
        if manager.teams.get(getattr(team, "team_id", None)) is not team:
            return MigrationOperationResult(status="DENIED", reason="A registered moving AgentTeam is required.")
        self.actor_check(team)
        with manager._topology_lock:
            try:
                manager._topology.require_available(team)
                target = manager._topology.resolve_parent(target_parent)
            except ValueError as error:
                return MigrationOperationResult(status="DENIED", reason=str(error))
        original = team.organizational_parent
        if original == principal_for(target):
            return MigrationOperationResult(status="EXECUTED", reason="The explicit parent is already unchanged.")
        operation = "voluntary_detachment" if target is None else "reattachment" if original is None else "migration"
        async with self.lock, self.stage() as candidate:
            with manager._topology_lock:
                invalid = self.validate(team, target, original, operation=operation)
                if invalid:
                    return MigrationOperationResult(status="DENIED", reason=invalid)
                policy = manager.config.migration_policy
                principals, evidence = self.route(team, target, policy, operation)
                item = next((item for item in self.requests.values() if item.status == "PENDING"
                    and item.team_id == team.team_id and item.path_evidence == evidence), None)
                if item is None:
                    item = MigrationRequest(team_id=team.team_id,
                        target_parent_id=target.team_id if isinstance(target, AgentTeam) else None,
                        target_parent_agent_id=target.agent_id if isinstance(target, Agent) else None,
                        original_parent_id=original.principal_id if original and original.kind == "agent_team" else None,
                        original_parent_agent_id=original.principal_id if original and original.kind == "agent" else None,
                        operation=operation, detachment_kind="voluntary_departure" if target is None else None,
                        policy_name=policy, principals=principals, path_evidence=evidence, rationale=rationale,
                        created_at=manager._activity.clock.wall_time())
                    self.requests[item.request_id] = item
                    dirty = manager._new_dirty_state()
                    dirty["configs"] = True
                    dirty["migration_requests"].add(item.request_id)
                else:
                    dirty = None
            if dirty is not None:
                operation_id = f"MIGRATION-{item.request_id}"
                try:
                    await manager._records.commit((), dirty=dirty, migration_state=candidate, operation_id=operation_id)
                finally:
                    if operation_id in manager._records.receipts:
                        self.schedule(item)

        if item.principals:
            self.schedule(item)
        else:
            await self.complete_request(item.request_id)
        return self.result(self.requests[item.request_id])

    def schedule(self, item):
        for principal in item.principals:
            self.manager._governance.track(f"migration:{item.request_id}:{principal.key}",
                self.prepare(item.request_id, principal))
        if not item.principals:
            self.manager._governance.track(f"migration:resolve:{item.request_id}", self.complete_request(item.request_id))

    async def prepare(self, request_id, principal):
        item = self.requests.get(request_id)
        if item is None or item.status != "PENDING":
            return
        prompt = (f"Decide whether your explicitly designated principal accepts topology request {request_id}. "
            f"Moving AgentTeam: {item.team_id}. Proposed parent: {item.target_parent_id or item.target_parent_agent_id}. "
            f"Rationale: {item.rationale}. Only an explicit tool ballot supplies authority.")
        await self.manager.broker.decision_provider.decide_principal_boolean(
            principal, request_id, prompt, business_kind="migration")
        await self.complete_request(request_id)

    async def complete_request(self, request_id):
        manager = self.manager
        async with self.lock, self.stage() as candidate, manager._governance.lock, manager._topology.transition_lock, manager._activity.lock:
            item = self.requests.get(request_id)
            if item is None or item.status != "PENDING" or manager._restore_in_progress:
                return
            team = manager.teams.get(item.team_id)
            target = (manager.teams.get(item.target_parent_id) if item.target_parent_id
                else manager._agents_by_id.get(item.target_parent_agent_id) if item.target_parent_agent_id else None)
            original = (ApprovalPrincipal(kind="agent_team", principal_id=item.original_parent_id) if item.original_parent_id
                else ApprovalPrincipal(kind="agent", principal_id=item.original_parent_agent_id) if item.original_parent_agent_id else None)
            invalid = self.validate(team, target, original, operation=item.operation)
            if target is None and (item.target_parent_id or item.target_parent_agent_id):
                invalid = "The prospective parent disappeared."
            if not invalid and self.route(team, target, item.policy_name, item.operation) != (item.principals, item.path_evidence):
                invalid = "The relevant organizational approval path changed."
            cases = [manager._governance.latest("migration", request_id, principal) for principal in item.principals]
            valid = lambda case: case is not None and manager._governance.electorate_valid(case)
            if invalid:
                status, reason = "STALE", invalid
            elif any(valid(case) and case.status == "DENIED" for case in cases):
                status, reason = "DENIED", "A designated principal explicitly denied the topology request."
            elif not all(valid(case) and case.status == "APPROVED" for case in cases):
                return
            else:
                status, reason = "EXECUTED", "All required authority and live topology checks succeeded."
            from contextlib import nullcontext
            reservation = manager._topology.reserve_transition(team) if status == "EXECUTED" else nullcontext()
            with reservation as reservation_token:
                before = item
                item = item.model_copy(deep=True)
                self.requests[request_id] = item
                item.status, item.reason = status, reason
                dirty = manager._new_dirty_state()
                dirty["migration_requests"].add(request_id)
                relation = None
                operation_id = f"TOPOLOGY-{request_id}"
                if status == "EXECUTED":
                    relation = {team.team_id: {"parent_team_id": item.target_parent_id, "parent_agent_id": item.target_parent_agent_id}}
                    dirty["teams"].add(team.team_id)

                def authorized():
                    if status != "EXECUTED":
                        return
                    invalid = self.validate(team, target, original, operation=item.operation, reservation=reservation_token)
                    if invalid:
                        from ..exceptions import ToolBusinessError
                        raise ToolBusinessError(invalid)
                    if (self.route(team, target, item.policy_name, item.operation) != (item.principals, item.path_evidence)
                            or any(not valid(case) or case.status != "APPROVED" for case in cases)):
                        raise ValueError("The topology path or explicit electorate changed before migration acceptance.")

                def records_at_admission():
                    authorized()
                    item.resolved_at = manager._activity.clock.wall_time()
                    return self.position_records(item, team, target, cases) if status == "EXECUTED" else ()

                accepted_deadline = None

                def bind_time(timestamp, monotonic):
                    nonlocal accepted_deadline
                    item.resolved_at = timestamp
                    accepted_deadline = monotonic + 600

                try:
                    await manager._records.commit((), dirty=dirty, operation_id=operation_id,
                        team_parents=relation, migration_state=candidate,
                        record_factory=records_at_admission, authority_check=authorized,
                        bind_acceptance_time=bind_time)
                except BaseException:
                    if operation_id not in manager._records.receipts:
                        self.requests[request_id] = before
                    raise
                finally:
                    if operation_id in manager._records.receipts:
                        for case in tuple(manager._governance.cases.values()):
                            if case.business_kind == "migration" and case.business_id == request_id and case.status == "PENDING":
                                manager._governance.track(f"expire:{case.case_id}",
                                    manager._governance.expire(case.case_id, "The originating topology request is resolved or stale."))
                        if status == "EXECUTED":
                            self.cooldown_deadlines[item.team_id] = accepted_deadline
                manager._emit_callback("on_system_event", "migration_request_resolved",
                    {"request_id": request_id, "team_id": item.team_id, "status": status})

    def position_records(self, item, team, target, cases):
        """Capture one admitted position change and its exact cooldown together."""
        manager = self.manager
        event_id = f"POSITION-{item.request_id}"
        records = []
        if target is not None:
            target_case = next(case for case in cases if case.principal == principal_for(target))
            item.acceptance_id = f"ACCEPT-{item.request_id}"
            records.append(capture(manager, "parent_acceptances", acceptance_id=item.acceptance_id,
                attaching_team_id=team.team_id, parent_agent_id=item.target_parent_agent_id,
                parent_team_id=item.target_parent_id, case_id=target_case.case_id, approved=1,
                topology_fingerprint=self.fingerprint(item.path_evidence), created_at=item.resolved_at))
        affected = {team.team_id, item.original_parent_id, item.target_parent_id} - {None}
        owners = set(manager._topology.affected_people(team))
        owners.update(member.agent_id for owner in affected if owner in manager.teams for member in manager.teams[owner].members)
        owners.update(owner for owner in (item.original_parent_agent_id, item.target_parent_agent_id) if owner)
        records.append(capture(manager, "team_topology_events", event_id=event_id, team_id=team.team_id,
            old_parent_agent_id=item.original_parent_agent_id, old_parent_team_id=item.original_parent_id,
            new_parent_agent_id=item.target_parent_agent_id, new_parent_team_id=item.target_parent_id,
            creator_agent_id=team.creator.agent_id if isinstance(team.creator, Agent) else None,
            creator_team_id=team.creator.team_id if isinstance(team.creator, AgentTeam) else None,
            acceptance_id=item.acceptance_id, transition="attachment" if item.operation == "reattachment"
            else item.operation if item.operation in {"voluntary_detachment", "parent_loss"} else "migration",
            created_at=item.resolved_at, position_revision=team._position_revision + 1,
            notice_recipients=sorted(owners)))
        mode = manager.config.migration_cooldown_downtime
        records.append(capture(manager, "team_position_cooldowns", team_id=team.team_id, event_id=event_id,
            accounting_mode="wall_time" if mode == "include" else "remaining", duration_seconds=600.0,
            deadline=item.resolved_at + 600 if mode == "include" else None,
            remaining_seconds=600.0 if mode == "exclude" else None, sampled_at=item.resolved_at))
        return records

    def resume(self):
        for item in self.requests.values():
            if item.status == "PENDING":
                self.schedule(item)
