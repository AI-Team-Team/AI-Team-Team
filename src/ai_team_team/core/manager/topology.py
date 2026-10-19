"""Topology lookup and rendering for an ATT manager."""

import asyncio
import threading
from contextlib import contextmanager
from typing import TYPE_CHECKING, Mapping, Optional

from ..agent import Agent
from ..exceptions import AmbiguousTeamContextError
from ..team import AgentTeam

if TYPE_CHECKING:
    from ..manager import ATTManager


class TopologyService:
    """Owns the parent index and shared topology/directory publication lock."""

    def __init__(self, manager: "ATTManager") -> None:
        self.manager = manager
        self.parent_map: dict[str, str] = {}
        self.lock = threading.RLock()
        self.transition_lock = asyncio.Lock()
        self._reserved: dict[str, object] = {}

    def require_available(self, team: AgentTeam) -> None:
        """Validate a topology participant inside the shared publication lock."""
        with self.lock:
            if (self.manager.teams.get(team.team_id) is not team
                    or team.team_kind != "ordinary"
                    or getattr(team, "_lifecycle_state", "active") != "active"
                    or getattr(team, "_publication_pending", False)):
                raise ValueError("Topology changes require active published registered ordinary AgentTeams.")
            if team.team_id in self._reserved:
                raise ValueError("An AgentTeam topology transition is awaiting commit.")

    @property
    def transition_pending(self) -> bool:
        with self.lock:
            return self.transition_lock.locked() or bool(self._reserved)

    @contextmanager
    def reserve_transition(self, team: AgentTeam):
        """Fence new topology edges until receipt settlement, without an IO-held lock.

        Async transitions also own transition_lock; synchronous team creation
        checks the same reservation under the short topology publication lock.
        The reservation is runtime coordination, not a published lifecycle.
        """
        token = object()
        with self.manager._resources.topology_mutation():
            self.require_available(team)
            self._reserved[team.team_id] = token
        try:
            yield
        finally:
            with self.lock:
                if self._reserved.get(team.team_id) is token:
                    del self._reserved[team.team_id]

    def replace_parent_map(self, parent_map: Mapping[str, str]) -> None:
        """Replace index contents without breaking the Manager's shared reference."""
        with self.lock:
            # Copy before clearing: restore/rollback inputs may be this index.
            replacement = dict(parent_map)
            self.parent_map.clear()
            self.parent_map.update(replacement)

    def find_parent_team(self, target: AgentTeam) -> Optional[AgentTeam]:
        # Resolving a missing cache also publishes a parent pointer.
        with self.lock:
            return self._find_parent_team_locked(target)

    def _find_parent_team_locked(self, target: AgentTeam) -> Optional[AgentTeam]:
        if target.team_kind == "supervisory":
            return None
        if target._parent_team is not None:
            return target._parent_team

        parent_id = self.parent_map.get(target.team_id)
        if parent_id and parent_id in self.manager.teams:
            target._parent_team = self.manager.teams[parent_id]
            return target._parent_team

        # Creation and migration publish the actual parent relationship. A
        # missing team parent is an intentional boundary, not permission to
        # infer ancestry from the creator's current invocation or memberships.
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
        level_one = [
            team for team in self.manager.teams.values()
            if team.team_kind == "ordinary" and team.parent_team is None
            and getattr(team, "_lifecycle_state", "active") == "active"
        ]

        def traverse(team: AgentTeam, depth: int = 1, is_last: bool = True) -> None:
            indent = "  " * depth
            prefix = "└── " if is_last else "├── "
            lines.append(
                f"{indent}{prefix}{team.team_id} "
                f"(Purpose: {team.team_purpose} | "
                f"Progress: {team.team_progress}) [Level {team.depth}]"
            )
            for index, child in enumerate(team.child_teams):
                if getattr(child, "_lifecycle_state", "active") != "active":
                    continue
                traverse(
                    child,
                    depth + 1,
                    is_last=index == len(team.child_teams) - 1,
                )

        for index, team in enumerate(level_one):
            traverse(team, 1, is_last=index == len(level_one) - 1)
        return "\n".join(lines)
