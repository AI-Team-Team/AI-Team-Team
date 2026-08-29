"""AgentTeam topology migration tool."""

from typing import Any, Dict

from ..core.exceptions import ToolBusinessError, ToolPermissionError
from .context import _resolve_actual_team
from .contract import Tool


def build_migration_tools(att_manager: Any, caller_node: Any) -> Dict[str, Tool]:
    async def request_migration(target_parent_id: str, rationale: str) -> str:
        """Requests to migrate the caller's team to a new parent team. Arguments: target_parent_id (str), rationale (str)"""
        if not att_manager:
            raise ToolBusinessError("ATTManager is not available in tools context.")
            
        actual_team = _resolve_actual_team(caller_node, att_manager)
        if not actual_team:
            raise ToolPermissionError("The active AgentTeam could not be resolved.")
            
        if target_parent_id not in att_manager.teams:
            raise ToolBusinessError(
                f"Target parent AgentTeam {target_parent_id!r} was not found."
            )
            
        target_parent = att_manager.teams[target_parent_id]
        if target_parent_id == actual_team.team_id:
            raise ToolBusinessError("An AgentTeam cannot become its own parent.")
            
        def is_descendant(t, target_id):
            for child in t.child_teams:
                if child.team_id == target_id or is_descendant(child, target_id):
                    return True
            return False
            
        if is_descendant(actual_team, target_parent_id):
            raise ToolBusinessError(
                "An AgentTeam cannot migrate under its own descendant because that would create a cycle."
            )
            
        success, message = await att_manager.negotiate_and_execute_migration(actual_team, target_parent, rationale)
        if success:
            return f"Success: {message}"
        raise ToolBusinessError(f"Migration was rejected: {message}")

    return {
        "request_migration": Tool(
            "request_migration",
            "Requests to migrate the caller's team to a new parent team in the hierarchy. Arguments: target_parent_id (str), rationale (str)",
            request_migration,
        )
    }

