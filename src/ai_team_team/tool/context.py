"""Invocation-scoped Agent and AgentTeam resolution for built-in tools."""

from typing import Any, Tuple


def _resolve_actual_team(caller_node: Any, att_manager: Any) -> Any:
    from ..core import Agent, AgentTeam
    if att_manager is not None and hasattr(att_manager, "_active_team"):
        active_team = att_manager._active_team.get()
        if active_team is not None:
            return active_team
    if isinstance(caller_node, AgentTeam):
        return caller_node
    elif isinstance(caller_node, Agent):
        return att_manager.get_agent_team(caller_node)
    return None

def _resolve_actual_agent(caller_node: Any, att_manager: Any) -> Any:
    from ..core import Agent

    if att_manager is not None and hasattr(att_manager, "_active_tool_agent"):
        active_agent = att_manager._active_tool_agent.get()
        if active_agent is not None:
            return active_agent
    if isinstance(caller_node, Agent):
        return caller_node
    return None


def _resolve_communication_context(att_manager: Any) -> Tuple[Any, Any]:
    """Resolves a fail-closed invocation-scoped AgentTeam and actor Agent."""
    if att_manager is None:
        raise RuntimeError("ATTManager is not available.")
    team = att_manager._active_team.get()
    agent = att_manager._active_tool_agent.get()
    if team is None or agent is None:
        raise RuntimeError(
            "Peer communication requires an active AgentTeam invocation context."
        )
    if att_manager.teams.get(team.team_id) is not team:
        raise RuntimeError("The active AgentTeam is not registered.")
    if (
        att_manager._agents_by_id.get(agent.agent_id) is not agent
        or agent.lifecycle_state != "active"
        or all(member.agent_id != agent.agent_id for member in team.members)
    ):
        raise RuntimeError(
            "The active Agent is not an active member of the current AgentTeam."
        )
    return team, agent

