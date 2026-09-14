"""Public ATTManager delegation methods for TeamAPI."""

from typing import Any, Dict, List, Optional, Tuple, Union


from ...agent import Agent
from ...formation import TeamFormationRequest
from ...team import AgentTeam


class TeamAPI:
    def unique_agent_name(self, base_name: str, team: AgentTeam) -> str:
        return self._team_creation.unique_agent_name(base_name, team)

    def create_agent_team(
        self,
        creator: Any,
        member_count: int = 3,
        roles_and_presets: List[Tuple[str, str]] = None,
        preset_name: str = "custom",
        system_instructions: str = "",
        team_purpose: str = "Unspecified team purpose",
        roles_and_models: Optional[Dict[str, str]] = None,
        member_configs: Optional[Dict[str, Dict[str, Any]]] = None,
        existing_members: Optional[List[Agent]] = None,
        existing_member_ids: Optional[List[str]] = None,
        is_public_visible: bool = False,
        initial_docs: Optional[Dict[str, str]] = None,
        initiating_agent: Optional[Agent] = None,
        initiator_joins: bool = False,
        unanimous_acceptance_action: str = "require_confirmation",
        late_join_policy: str = "disabled",
        task: Optional[str] = None,
    ) -> Union[AgentTeam, TeamFormationRequest]:
        return self._team_creation.create_agent_team(
            creator=creator,
            member_count=member_count,
            roles_and_presets=roles_and_presets,
            preset_name=preset_name,
            system_instructions=system_instructions,
            team_purpose=team_purpose,
            roles_and_models=roles_and_models,
            member_configs=member_configs,
            existing_members=existing_members,
            existing_member_ids=existing_member_ids,
            is_public_visible=is_public_visible,
            initial_docs=initial_docs,
            initiating_agent=initiating_agent,
            initiator_joins=initiator_joins,
            unanimous_acceptance_action=unanimous_acceptance_action,
            late_join_policy=late_join_policy,
            task=task,
        )

    def bootstrap_agent_team(self, creator: Any, **kwargs: Any) -> AgentTeam:
        """Explicit trusted-host topology initialization; never exposed as an Agent tool."""
        return self._team_creation.bootstrap_agent_team(creator, **kwargs)

    def _validate_team_creation_inputs(self, *args: Any, **kwargs: Any) -> Any:
        return self._team_creation._validate_team_creation_inputs(*args, **kwargs)

    def _resolve_existing_team_members(self, *args: Any, **kwargs: Any) -> Any:
        return self._team_creation._resolve_existing_team_members(*args, **kwargs)

    def _team_creation_snapshot(self) -> Dict[str, Any]:
        return self._team_creation._team_creation_snapshot()

    def _rollback_team_creation(self, snapshot: Dict[str, Any]) -> None:
        return self._team_creation._rollback_team_creation(snapshot)

    def _create_agent_team(self, *args: Any, **kwargs: Any) -> Any:
        return self._team_creation._create_agent_team(*args, **kwargs)

    def _validate_team_creation_commit(self, *args: Any, **kwargs: Any) -> Any:
        return self._team_creation._validate_team_creation_commit(*args, **kwargs)

    def find_parent_team(self, target: AgentTeam) -> Optional[AgentTeam]:
        return self._topology.find_parent_team(target)

    def get_agent_team(self, agent: Agent) -> Optional[AgentTeam]:
        return self._topology.get_agent_team(agent)

    def render_topology_tree(self) -> str:
        """Renders the active hierarchical AgentTeam lineage."""
        return self._topology.render_tree()

    async def negotiate_and_execute_migration(
        self, team: AgentTeam, target_parent: AgentTeam, rationale: str
    ) -> Tuple[bool, str]:
        return await self._migration.negotiate_and_execute_migration(team, target_parent, rationale)

    async def _apply_deferred_membership_changes(self, team: AgentTeam) -> None:
        return await self._membership._apply_deferred_membership_changes(team)
