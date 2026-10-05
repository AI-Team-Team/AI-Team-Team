"""ATT governance policies backed by explicit AgentTeam or Agent principals."""

from __future__ import annotations

import logging
from typing import Any, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, StrictBool, ValidationError

from .communication import ApprovalPrincipal
from .governance import MigrationOperationResult

logger = logging.getLogger("ATT.Policies")


class GovernanceDecision(BaseModel):
    """Strict fail-closed schema for boolean governance decisions."""

    model_config = ConfigDict(strict=True, extra="forbid")

    approved: StrictBool
    reason: str = "No reason provided."


def parse_governance_decision(
    response: str, manager: Any, context: str
) -> Tuple[bool, str]:
    cleaned = response.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[len("```json") :]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    try:
        decision = GovernanceDecision.model_validate_json(
            cleaned.strip(), strict=True
        )
    except (ValidationError, ValueError, TypeError) as exc:
        reason = f"Invalid governance decision format: {exc}"
        logger.warning("%s rejected: %s", context, reason)
        if manager is not None:
            manager._emit_callback(
                "on_system_event",
                "governance_authorization_format_error",
                {"context": context, "reason": reason},
            )
        return False, reason
    return decision.approved, decision.reason


def get_ancestry_chain(team: Any) -> List[Any]:
    chain = []
    current = team
    while current is not None:
        chain.append(current)
        current = current.parent_team
    return chain


def find_lca(first: Any, second: Any) -> Any:
    if first is None or second is None:
        return None
    second_ids = {team.team_id for team in get_ancestry_chain(second)}
    return next(
        (
            team
            for team in get_ancestry_chain(first)
            if team.team_id in second_ids
        ),
        None,
    )


def get_path_to_ancestor(start: Any, ancestor: Any) -> List[Any]:
    path = []
    current = start
    while current is not None:
        path.append(current)
        if current is ancestor:
            break
        current = current.parent_team

    return path


class BaseMigrationPolicy:
    async def authorize_migration(self, team: Any, target_parent: Any, manager: Any, rationale: str) -> MigrationOperationResult:
        """Returns the durable operation; missing personal choices are pending."""
        return await manager.negotiate_and_execute_migration(team, target_parent, rationale)


class PermissiveMigrationPolicy(BaseMigrationPolicy):
    pass


def _principal_for_team(team: Any, manager: Any) -> ApprovalPrincipal:
    if team is None:
        return ApprovalPrincipal(kind="agent", principal_id=manager.root_ai.agent_id)
    return ApprovalPrincipal(kind="agent_team", principal_id=team.team_id)


def _deduplicate(principals: List[ApprovalPrincipal]) -> List[ApprovalPrincipal]:
    result = []
    seen = set()
    for principal in principals:
        if principal.key not in seen:
            seen.add(principal.key)
            result.append(principal)
    return result


def migration_approval_principals(
    policy_name: str,
    team: Any,
    target_parent: Any,
    manager: Any,
) -> List[ApprovalPrincipal]:
    """Resolves the exact migration authorities for validation and approval."""
    if policy_name == "permissive":
        return []
    current_parent = team.parent_team
    lca = find_lca(current_parent, target_parent)
    if policy_name == "ancestor_approval":
        return _deduplicate(
            [
                _principal_for_team(current_parent, manager),
                _principal_for_team(target_parent, manager),
                _principal_for_team(lca, manager),
            ]
        )
    if policy_name == "lineage_path":
        path = get_path_to_ancestor(current_parent, lca)
        path.extend(get_path_to_ancestor(target_parent, lca))
        principals = [_principal_for_team(item, manager) for item in path]
        if lca is None:
            principals.append(_principal_for_team(None, manager))
        return _deduplicate(principals)
    raise ValueError(f"Unknown migration policy: {policy_name!r}.")


class AncestorApprovalMigrationPolicy(BaseMigrationPolicy):
    pass


class LineagePathMigrationPolicy(BaseMigrationPolicy):
    pass


def resolve_migration_policy(policy_name: str) -> BaseMigrationPolicy:
    policies = {
        "permissive": PermissiveMigrationPolicy(),
        "ancestor_approval": AncestorApprovalMigrationPolicy(),
        "lineage_path": LineagePathMigrationPolicy(),
    }
    try:
        return policies[policy_name.lower()]
    except (AttributeError, KeyError) as exc:
        raise ValueError(f"Unknown migration policy: {policy_name!r}.") from exc
