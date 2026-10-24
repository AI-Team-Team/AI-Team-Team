"""Topology lookup and rendering for an ATT manager."""

import asyncio
import threading
from contextlib import contextmanager
from typing import TYPE_CHECKING, Mapping, Optional

from ..agent import Agent
from ..exceptions import AmbiguousTeamContextError
from ..team import AgentTeam
from ..communication import ApprovalPrincipal

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

    def is_agent_pending(self, agent_id):
        """Staging membership never grants a new person's runtime authority."""
        return any(getattr(team, "_publication_pending", False)
            and agent_id in getattr(team, "_provisional_agent_ids", ())
            for team in self.manager.teams.values())

    def require_available(self, team: AgentTeam, *, reservation=None) -> None:
        """Validate a topology participant inside the shared publication lock."""
        with self.lock:
            if (team is None or self.manager.teams.get(team.team_id) is not team
                    or team.team_kind != "ordinary"
                    or getattr(team, "_lifecycle_state", "active") != "active"
                    or getattr(team, "_publication_pending", False)):
                raise ValueError("Topology changes require active published registered ordinary AgentTeams.")
            if team.team_id in self._reserved and self._reserved[team.team_id] is not reservation:
                raise ValueError("An AgentTeam topology transition is awaiting commit.")

    def resolve_parent(self, parent):
        """Resolve an explicitly supplied authority without consulting memberships."""
        if isinstance(parent, ApprovalPrincipal):
            parent = (self.manager.teams if parent.kind == "agent_team" else self.manager._agents_by_id).get(parent.principal_id)
            if parent is None:
                raise ValueError("The explicit organizational parent is missing.")
        if isinstance(parent, AgentTeam):
            self.require_available(parent)
        elif isinstance(parent, Agent):
            if (self.manager._agents_by_id.get(parent.agent_id) is not parent
                    or parent.lifecycle_state != "active"
                    or self.is_agent_pending(parent.agent_id)
                    or self.manager.supervisor.is_supervisory_agent(parent.agent_id)):
                raise ValueError("An Agent parent must be an active registered ordinary identity.")
            if f"agent:{parent.agent_id}" in self._reserved:
                raise ValueError("The Agent parent is awaiting an organizational transition.")
        elif parent is not None:
            raise TypeError("parent must be an Agent, AgentTeam, ApprovalPrincipal, or None.")
        return parent

    def parent_object(self, team):
        principal = team.organizational_parent
        return self.resolve_parent(principal) if principal is not None else None

    def publish_parent(self, team, parent):
        """Caller owns the topology publication lock and accepted transition."""
        previous = team.parent_team
        if previous is not None and team in previous.child_teams:
            previous.child_teams.remove(team)
        self.parent_map.pop(team.team_id, None)
        team._parent_team = parent if isinstance(parent, AgentTeam) else None
        team._parent_agent_id = parent.agent_id if isinstance(parent, Agent) else None
        team._position_revision += 1
        if isinstance(parent, AgentTeam):
            self.parent_map[team.team_id] = parent.team_id
            if team not in parent.child_teams:
                parent.child_teams.append(team)
        team.invalidate_depth_cache(recursive=True)

    def affected_people(self, team):
        owners, pending = set(), [team]
        while pending:
            node = pending.pop()
            owners.update(member.agent_id for member in node.members)
            pending.extend(child for child in node.child_teams if getattr(child, "_lifecycle_state", "active") == "active")
        return sorted(owners)

    def parent_loss_records(self, parent, source_id):
        """Detach surviving direct children only; caller commits parent loss atomically."""
        from .activity.values import capture
        from ..organization import principal_for

        principal = principal_for(parent)
        records, changes = [], {}
        for child in self.manager.teams.values():
            if (child.team_kind != "ordinary" or getattr(child, "_lifecycle_state", "active") != "active"
                    or child.organizational_parent != principal):
                continue
            changes[child.team_id] = {"parent_agent_id": None, "parent_team_id": None}
            records.append(capture(self.manager, "team_topology_events", event_id=f"LOSS-{source_id}-{child.team_id}",
                team_id=child.team_id, old_parent_agent_id=principal.principal_id if principal.kind == "agent" else None,
                old_parent_team_id=principal.principal_id if principal.kind == "agent_team" else None,
                creator_agent_id=child.creator.agent_id if isinstance(child.creator, Agent) else None,
                creator_team_id=child.creator.team_id if isinstance(child.creator, AgentTeam) else None,
                transition="parent_loss", created_at=self.manager._activity.clock.wall_time(),
                position_revision=child._position_revision + 1,
                notice_recipients=self.affected_people(child)))
        return records, changes

    def schedule_notices(self, records=None):
        """The retained position event is the outbox; dispatch never runs business work."""
        records = self.manager._records.snapshot() if records is None else records
        for row in records:
            if row.table_name != "team_topology_events" or row.values["transition"] == "creation":
                continue
            for owner in row.values["notice_recipients"] or ():
                agent = self.manager._agents_by_id.get(owner)
                message_id = f"POSITION-NOTICE-{row.values['event_id']}-{owner}"
                if (agent is None or agent.lifecycle_state != "active"
                        or any(mail["message_id"] == message_id for mail in agent.agent_inbox)):
                    continue
                self.manager._governance.track(message_id, self.manager._activity.deliver_mail(owner,
                    message_type="organizational_position_changed",
                    payload={"event_id": row.values["event_id"], "team_id": row.values["team_id"],
                             "transition": row.values["transition"]},
                    _message_id=message_id, _classification="membership"))

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
            pending, identifiers = [team], []
            while pending:
                node = pending.pop()
                self.require_available(node)
                identifiers.append(node.team_id)
                pending.extend(child for child in node.child_teams if getattr(child, "_lifecycle_state", "active") == "active")
            self._reserved.update({owner: token for owner in identifiers})
        try:
            yield token
        finally:
            with self.lock:
                for owner in identifiers:
                    if self._reserved.get(owner) is token:
                        del self._reserved[owner]

    @contextmanager
    def reserve_agent_parent(self, agent):
        from contextlib import ExitStack
        token, key = object(), f"agent:{agent.agent_id}"
        with ExitStack() as reservations:
            with self.lock:
                if key in self._reserved:
                    raise ValueError("The Agent parent already has a pending transition.")
                self._reserved[key] = token
                children = [team for team in self.manager.teams.values()
                            if getattr(team, "_parent_agent_id", None) == agent.agent_id
                            and getattr(team, "_lifecycle_state", "active") == "active"]
            try:
                for child in children:
                    reservations.enter_context(self.reserve_transition(child))
                yield
            finally:
                with self.lock:
                    if self._reserved.get(key) is token:
                        del self._reserved[key]

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
        memberships = [team for team in self.manager.teams.values() if agent in team.members
            and team.team_kind == "ordinary" and getattr(team, "_lifecycle_state", "active") == "active"
            and not getattr(team, "_publication_pending", False)]
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
        """Render actual organizational forests without an invented Root edge."""
        with self.lock:
            active = {key: team for key, team in self.manager.teams.items()
                if team.team_kind == "ordinary" and getattr(team, "_lifecycle_state", "active") == "active"}
            lines = ["Organizational forest"]
            def traverse(team, indent):
                lines.append(f"{indent}- {team.team_id} (Purpose: {team.team_purpose} | Progress: {team.team_progress}) [Depth {team.depth}]")
                for child in sorted(team.child_teams, key=lambda item: item.team_id):
                    if child.team_id in active:
                        traverse(child, indent + "  ")
            parent_ids = {team.organizational_parent.principal_id for team in active.values()
                if team.organizational_parent is not None and team.organizational_parent.kind == "agent"}
            parent_ids.add(self.manager.root_ai.agent_id)
            for parent_id in sorted(parent_ids):
                parent = self.manager._agents_by_id[parent_id]
                lines.append(f"- Agent: {parent.name} ({parent.agent_id})")
                for team in sorted(active.values(), key=lambda item: item.team_id):
                    if getattr(team, "_parent_agent_id", None) == parent_id:
                        traverse(team, "  ")
            independent = sorted((team for team in active.values() if team.is_independent), key=lambda item: item.team_id)
            if independent:
                lines.append("- Independent AgentTeams")
                for team in independent:
                    traverse(team, "  ")
            return "\n".join(lines)
