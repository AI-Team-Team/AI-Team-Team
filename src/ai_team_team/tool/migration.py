"""AgentTeam topology migration tool."""

from typing import Any, Dict, Optional

from ..core.exceptions import ToolBusinessError, ToolPermissionError
from ..core.governance import MigrationOperationResult, MigrationRequest
from ..core.communication import ApprovalPrincipal
from .context import _resolve_actual_team
from .contract import Tool


def build_migration_tools(att_manager: Any, caller_node: Any) -> Dict[str, Tool]:
    async def request_migration(target_parent: Optional[ApprovalPrincipal], rationale: str) -> MigrationOperationResult:
        """Choose an explicit Agent/AT parent, or null for voluntary independence."""
        if not att_manager:
            raise ToolBusinessError("ATTManager is not available in tools context.")
        team = _resolve_actual_team(caller_node, att_manager)
        if team is None:
            raise ToolPermissionError("Changing a team's position requires its current active scope.")
        try:
            parent = att_manager._topology.resolve_parent(target_parent)
        except (ValueError, TypeError) as error:
            raise ToolBusinessError(str(error)) from error
        return await att_manager.negotiate_and_execute_migration(team, parent, rationale)

    async def inspect_migration_request(request_id: str) -> MigrationRequest:
        """Inspects a durable migration request involving the current AgentTeam."""
        team = _resolve_actual_team(caller_node, att_manager)
        if att_manager is None:
            raise ToolBusinessError("ATTManager is not available in tools context.")
        try:
            item = att_manager.inspect_migration_request(request_id)
        except KeyError as exc:
            raise ToolBusinessError("The migration request was not found.") from exc
        actor = att_manager._active_tool_agent.get()
        team_visible = team is not None and team.team_id in {item.team_id, item.target_parent_id, item.original_parent_id}
        agent_visible = actor is not None and actor.agent_id in {item.target_parent_agent_id, item.original_parent_agent_id}
        if not (team_visible or agent_visible):
            raise ToolPermissionError("The migration request is outside this AgentTeam's scope.")
        return item

    return {
        "request_migration": Tool(
            "request_migration",
            "Request a position change. target_parent is an explicit {kind: agent or agent_team, principal_id: stable ID}, or null for voluntary detachment. Target acceptance, Host settings, cycle checks, and cooldowns remain mandatory.",
            request_migration,
        ),
        "inspect_migration_request": Tool(
            "inspect_migration_request",
            inspect_migration_request.__doc__,
            inspect_migration_request,
        ),
    }
