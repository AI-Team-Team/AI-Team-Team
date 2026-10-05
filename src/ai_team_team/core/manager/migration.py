"""Durable asynchronous migration decisions and revalidated topology commits."""

import asyncio
import time
from typing import Any

from ..governance import MigrationOperationResult, MigrationRequest
from ..policies import migration_approval_principals


class MigrationService:
    def __init__(self, manager: Any) -> None:
        self.manager = manager
        self.requests: dict[str, MigrationRequest] = {}
        self.lock = asyncio.Lock()

    def restore(self, rows) -> None:
        self.requests = {
            item.request_id: item
            for item in (MigrationRequest.model_validate(row, strict=False) for row in rows)
        }

    @staticmethod
    def result(item) -> MigrationOperationResult:
        return MigrationOperationResult(
            status=item.status, request_id=item.request_id, reason=item.reason
        )

    def validate(self, team, target, original_parent, policy_name, principals):
        manager = self.manager
        if (
            team is None
            or target is None
            or manager.teams.get(team.team_id) is not team
            or manager.teams.get(target.team_id) is not target
        ):
            return "Migration requires two registered AgentTeams."
        if team.team_kind != "ordinary" or target.team_kind != "ordinary":
            return "System AgentTeams cannot migrate."
        if team.parent_team is not original_parent:
            return "The current parent changed while approval was pending."
        if original_parent is not None and team not in original_parent.child_teams:
            return "The parent/child topology is inconsistent."
        if team.migration_count >= manager.config.max_migrations_per_team_discussion:
            return "The migration limit for the discussion has been reached."
        cursor = target
        seen = set()
        while cursor is not None:
            if cursor is team or cursor.team_id in seen:
                return "Migration would create a topology cycle."
            seen.add(cursor.team_id)
            cursor = cursor.parent_team
        if migration_approval_principals(policy_name, team, target, manager) != principals:
            return "The migration approval path changed."
        return None

    async def negotiate_and_execute_migration(
        self, team, target_parent, rationale
    ) -> MigrationOperationResult:
        manager = self.manager
        if manager._closing or manager._restore_in_progress:
            raise RuntimeError(
                "ATTManager rejects migration requests during shutdown or restore."
            )
        if not isinstance(rationale, str):
            raise ValueError("Migration rationale must be a string.")
        if (
            manager.teams.get(getattr(team, "team_id", None)) is not team
            or manager.teams.get(getattr(target_parent, "team_id", None)) is not target_parent
            or team is None
            or target_parent is None
        ):
            return MigrationOperationResult(
                status="DENIED", reason="Migration requires two registered AgentTeams."
            )
        async with self.lock:
            if manager._closing or manager._restore_in_progress:
                raise RuntimeError(
                    "ATTManager rejects migration requests during shutdown or restore."
                )
            with manager._topology_lock:
                policy_name = manager.config.migration_policy
                principals = migration_approval_principals(
                    policy_name, team, target_parent, manager
                )
                invalid = self.validate(
                    team, target_parent, team.parent_team, policy_name, principals
                )
                if invalid:
                    return MigrationOperationResult(status="DENIED", reason=invalid)
                if team.parent_team is target_parent:
                    return MigrationOperationResult(
                        status="EXECUTED", reason="This AgentTeam already has the requested parent."
                    )
                item = next(
                    (
                        item
                        for item in self.requests.values()
                        if item.status == "PENDING"
                        and item.team_id == team.team_id
                        and item.target_parent_id == target_parent.team_id
                        and item.policy_name == policy_name
                    ),
                    None,
                )
                if item is None:
                    item = MigrationRequest(
                        team_id=team.team_id,
                        target_parent_id=target_parent.team_id,
                        original_parent_id=team.parent_team.team_id if team.parent_team else None,
                        policy_name=policy_name,
                        principals=principals,
                        rationale=rationale,
                    )
                    self.requests[item.request_id] = item
                    dirty = manager._new_dirty_state()
                    dirty["configs"] = True
                    dirty["migration_requests"].add(item.request_id)
                else:
                    dirty = None
            if dirty is not None:
                try:
                    await manager._commit_dirty_state(dirty)
                except asyncio.CancelledError:
                    self.schedule(item)
                    raise
                except Exception:
                    self.requests.pop(item.request_id, None)
                    raise
        if not item.principals:
            await self.complete_request(item.request_id)
        else:
            self.schedule(item)
        return self.result(item)

    def schedule(self, item):
        if not item.principals:
            self.manager._governance.track(
                f"migration:resolve:{item.request_id}", self.complete_request(item.request_id)
            )
            return
        for principal in item.principals:
            self.manager._governance.track(
                f"migration:{item.request_id}:{principal.key}",
                self.prepare(item.request_id, principal),
            )

    async def prepare(self, request_id, principal):
        item = self.requests.get(request_id)
        if item is None or item.status != "PENDING":
            return
        prompt = (
            "Consider whether your designated principal approves this topology migration.\n"
            f"Request: {item.request_id}\nMoving AgentTeam: {item.team_id}\n"
            f"Current parent: {item.original_parent_id or 'Root Agent'}\n"
            f"Target parent: {item.target_parent_id}\nRationale: {item.rationale}"
        )
        await self.manager.broker.decision_provider.decide_principal_boolean(
            principal, item.request_id, prompt, business_kind="migration"
        )
        await self.complete_request(request_id)

    async def complete_request(self, request_id):
        manager = self.manager
        async with self.lock, manager._governance.lock:
            if manager._restore_in_progress:
                raise RuntimeError("ATTManager cannot resolve migration during restore.")
            item = self.requests.get(request_id)
            if item is None or item.status != "PENDING":
                return
            rounds = [
                manager._governance.latest("migration", request_id, principal)
                for principal in item.principals
            ]
            if any(
                round is not None
                and round.status == "DENIED"
                and manager._governance.electorate_valid(round)
                for round in rounds
            ):
                final_status, reason = (
                    "DENIED",
                    "A designated governance principal explicitly denied migration.",
                )
            elif all(
                round is not None
                and round.status == "APPROVED"
                and manager._governance.electorate_valid(round)
                for round in rounds
            ):
                final_status, reason = (
                    "EXECUTED",
                    "Every designated principal explicitly approved migration.",
                )
            else:
                return
            before = item.model_copy(deep=True)
            with manager._topology_lock:
                team = manager.teams.get(item.team_id)
                target = manager.teams.get(item.target_parent_id)
                parent = (
                    manager.teams.get(item.original_parent_id) if item.original_parent_id else None
                )
                invalid = self.validate(team, target, parent, item.policy_name, item.principals)
                if invalid:
                    final_status, reason = "STALE", invalid
                changed = set()
                changed_inboxes = set()
                old_count = team.migration_count if team else None
                original_position = None
                if final_status == "EXECUTED":
                    if parent is not None:
                        original_position = parent.child_teams.index(team)
                        parent.child_teams.remove(team)
                        changed.add(parent.team_id)
                    target.child_teams.append(team)
                    team._parent_team = target
                    manager._team_parent_map[team.team_id] = target.team_id
                    team.migration_count += 1
                    team.invalidate_depth_cache(recursive=True)
                    changed.update((team.team_id, target.team_id))
                    pending = list(team.child_teams)
                    while pending:
                        child = pending.pop()
                        changed.add(child.team_id)
                        pending.extend(child.child_teams)
                    for node in (parent, target, team):
                        if node is not None:
                            with node.inbox_lock:
                                node.message_inbox.append(
                                    {
                                        "type": "migration_alert",
                                        "from": "System/Migration",
                                        "request_id": request_id,
                                        "reason": f"AgentTeam {team.team_id} migrated from {item.original_parent_id or 'Root Agent'} to {target.team_id}.",
                                    }
                                )
                            changed_inboxes.add(node.team_id)
                item.status = final_status
                item.reason = reason
                item.resolved_at = time.time()
            rounds_before = {}
            for voting_round in manager._governance.rounds.values():
                if (
                    voting_round.business_kind == "migration"
                    and voting_round.business_id == request_id
                    and voting_round.status == "PENDING"
                ):
                    rounds_before[voting_round.round_id] = voting_round.model_copy(deep=True)
                    voting_round.status = "CANCELLED"
                    voting_round.reason = (
                        "The originating migration request no longer accepts choices."
                    )
                    voting_round.resolved_at = time.time()
            dirty = manager._new_dirty_state()
            dirty["migration_requests"].add(request_id)
            dirty["teams"].update(changed)
            dirty["inboxes"].update(changed_inboxes)
            dirty["governance_rounds"].update(rounds_before)
            try:
                await manager._commit_dirty_state(dirty)
            except Exception:
                self.requests[request_id] = before
                manager._governance.rounds.update(rounds_before)
                if changed:
                    with manager._topology_lock:
                        target.child_teams.remove(team)
                        if parent is not None:
                            parent.child_teams.insert(original_position, team)
                            manager._team_parent_map[team.team_id] = parent.team_id
                        else:
                            manager._team_parent_map.pop(team.team_id, None)
                        team._parent_team = parent
                        team.migration_count = old_count
                        team.invalidate_depth_cache(recursive=True)
                        for identifier in changed_inboxes:
                            node = manager.teams[identifier]
                            with node.inbox_lock:
                                node.message_inbox = [
                                    message
                                    for message in node.message_inbox
                                    if not (
                                        message.get("type") == "migration_alert"
                                        and message.get("request_id") == request_id
                                    )
                                ]
                raise
        if final_status == "EXECUTED":
            manager._emit_callback(
                "on_team_migration", item.team_id, item.original_parent_id, item.target_parent_id
            )
        manager._emit_callback(
            "on_system_event",
            "migration_request_resolved",
            {
                "request_id": request_id,
                "team_id": item.team_id,
                "target_parent_id": item.target_parent_id,
                "status": item.status,
            },
        )

    def resume(self):
        for item in self.requests.values():
            if item.status == "PENDING":
                self.schedule(item)
