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


class BaseMigrationPolicy:
    async def authorize_migration(self, team: Any, target_parent: Any, manager: Any, rationale: str) -> MigrationOperationResult:
        """Returns the durable operation; missing personal choices are pending."""
        return await manager.negotiate_and_execute_migration(team, target_parent, rationale)


class PermissiveMigrationPolicy(BaseMigrationPolicy):
    pass


def migration_approval_principals(policy_name, team, target_parent, manager):
    """Use the same explicit-parent route as the authoritative migration service."""
    operation = "voluntary_detachment" if target_parent is None else "reattachment" if team.is_independent else "migration"
    return manager._migration.route(team, target_parent, policy_name, operation)[0]


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
