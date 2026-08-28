"""Topology lookup and rendering for an ATT manager."""

import threading
from typing import TYPE_CHECKING, Optional

from ..agent import Agent
from ..exceptions import AmbiguousTeamContextError
from ..team import AgentTeam

if TYPE_CHECKING:
    from ..manager import ATTManager


class TopologyService:
    """Owns the parent index and topology-level synchronization lock."""

    def __init__(self, manager: "ATTManager") -> None:
        self.manager = manager
        self.parent_map: dict[str, str] = {}
        self.lock = threading.RLock()

    def find_parent_team(self, target: AgentTeam) -> Optional[AgentTeam]:
        if target._parent_team is not None:
            return target._parent_team

        parent_id = self.parent_map.get(target.team_id)
        if parent_id and parent_id in self.manager.teams:
            target._parent_team = self.manager.teams[parent_id]
            return target._parent_team

        if isinstance(target.creator, AgentTeam):
            target._parent_team = target.creator
            self.parent_map[target.team_id] = target.creator.team_id
            return target.creator

        if isinstance(target.creator, Agent):
            parent = self.get_agent_team(target.creator)
            if parent:
                target._parent_team = parent
                self.parent_map[target.team_id] = parent.team_id
                return parent

        return None

    def get_agent_team(self, agent: Agent) -> Optional[AgentTeam]:
        active_team = self.manager._active_team.get()
        if active_team is not None and agent in active_team.members:
            return active_team
        memberships = [team for team in self.manager.teams.values() if agent in team.members]
        if len(memberships) == 1:
            return memberships[0]
        if len(memberships) > 1:
            raise AmbiguousTeamContextError(
                f"Agent {agent.name!r} belongs to multiple teams and no "
                "invocation-scoped team context is active: "
                + ", ".join(sorted(team.team_id for team in memberships))
            )
        return None

    def render_tree(self) -> str:
        lines = [f"- [Root AI: {self.manager.root_ai.name}] (Level 0)"]
        level_one = [team for team in self.manager.teams.values() if team.parent_team is None]

        def traverse(team: AgentTeam, depth: int = 1, is_last: bool = True) -> None:
            indent = "  " * depth
            prefix = "└── " if is_last else "├── "
            lines.append(
                f"{indent}{prefix}{team.team_id} "
                f"(Purpose: {team.team_purpose} | "
                f"Progress: {team.team_progress}) [Level {team.depth}]"
            )
            for index, child in enumerate(team.child_teams):
                traverse(
                    child,
                    depth + 1,
                    is_last=index == len(team.child_teams) - 1,
                )

        for index, team in enumerate(level_one):
            traverse(team, 1, is_last=index == len(level_one) - 1)
        return "\n".join(lines)
