"""AgentTeam creation workflow for TeamCreationValidationMixin."""

from typing import Any, Dict, List, Optional, Tuple

from ai_team_team.doc_library import DocumentLibrary

from ...agent import Agent
from ...team import AgentTeam


class TeamCreationValidationMixin:
    def _resolve_existing_team_members(
        self,
        existing_members: Optional[List[Agent]],
        existing_member_ids: Optional[List[str]],
    ) -> List[Agent]:
        """Resolve active registered Agents without assigning team-specific identity."""
        manager = self.manager
        if existing_members is not None and not isinstance(existing_members, list):
            raise TypeError("existing_members must be a list of Agent instances.")
        if existing_member_ids is not None and not isinstance(existing_member_ids, list):
            raise TypeError("existing_member_ids must be a list of Agent IDs.")

        resolved: List[Agent] = []
        for agent in existing_members or []:
            if not isinstance(agent, Agent):
                raise TypeError("existing_members must contain only Agent instances.")
            if (
                manager._agents_by_id.get(agent.agent_id) is not agent
                or manager.agents.get(agent.name) is not agent
                or agent.lifecycle_state != "active"
            ):
                raise ValueError(
                    f"Existing Agent {agent.name!r} must be actively registered with this manager."
                )
            resolved.append(agent)

        for agent_id in existing_member_ids or []:
            if not isinstance(agent_id, str) or not agent_id:
                raise ValueError("existing_member_ids must contain non-empty strings.")
            agent = manager._agents_by_id.get(agent_id)
            if (
                agent is None
                or manager.agents.get(agent.name) is not agent
                or agent.lifecycle_state != "active"
            ):
                raise ValueError(f"Existing Agent ID {agent_id!r} is not actively registered.")
            resolved.append(agent)

        resolved_ids = [agent.agent_id for agent in resolved]
        if len(resolved_ids) != len(set(resolved_ids)):
            raise ValueError("An AgentTeam cannot contain duplicate existing Agent identities.")
        return resolved

    def _validate_team_creation_inputs(
        self,
        *,
        creator: Any,
        member_count: int,
        roles_and_presets: Optional[List[Tuple[str, str]]],
        roles_and_models: Optional[Dict[str, str]],
        member_configs: Optional[Dict[str, Dict[str, Any]]],
        existing_members: Optional[List[Agent]],
        existing_member_ids: Optional[List[str]],
        initial_docs: Optional[Dict[str, str]],
        preset_name: str,
        system_instructions: str,
        team_purpose: str,
        is_public_visible: bool,
    ) -> None:
        manager = self.manager
        if not isinstance(creator, (Agent, AgentTeam)):
            raise TypeError("creator must be an Agent or AgentTeam.")
        if isinstance(creator, AgentTeam) and manager.teams.get(creator.team_id) is not creator:
            raise ValueError("The creator AgentTeam must be registered.")
        if isinstance(creator, Agent) and creator.lifecycle_state != "active":
            raise ValueError("The creator Agent must be active.")
        for name, value in {
            "preset_name": preset_name,
            "system_instructions": system_instructions,
            "team_purpose": team_purpose,
        }.items():
            if not isinstance(value, str):
                raise TypeError(f"{name} must be a string.")
        if not preset_name:
            raise ValueError("preset_name must be non-empty.")
        if not isinstance(is_public_visible, bool):
            raise TypeError("is_public_visible must be a boolean.")
        if member_configs is not None and not isinstance(member_configs, dict):
            raise TypeError("member_configs must be a dictionary.")
        if member_configs and roles_and_presets:
            raise ValueError("member_configs and roles_and_presets are mutually exclusive.")
        existing = self._resolve_existing_team_members(
            existing_members,
            existing_member_ids,
        )
        explicit_new_count = (
            len(member_configs)
            if member_configs
            else len(roles_and_presets)
            if roles_and_presets
            else 0
        )
        effective_count = (
            len(existing) + explicit_new_count
            if existing or explicit_new_count
            else member_count
        )
        if (
            not isinstance(effective_count, int)
            or isinstance(effective_count, bool)
            or effective_count < manager.config.min_subagent_team_size
        ):
            raise ValueError(
                f"An AgentTeam requires at least {manager.config.min_subagent_team_size} members."
            )
        available_models = set(manager.llm_clients) | set(manager.model_configs)
        if roles_and_models is not None:
            if not isinstance(roles_and_models, dict):
                raise TypeError("roles_and_models must be a dictionary.")
            for role, alias in roles_and_models.items():
                if not isinstance(role, str) or not role:
                    raise ValueError("roles_and_models keys must be non-empty strings.")
                if not isinstance(alias, str) or not alias:
                    raise ValueError("roles_and_models aliases must be non-empty strings.")
                if alias != "default" and alias not in available_models:
                    raise ValueError(f"Model {alias!r} is not registered.")
        if roles_and_presets is not None:
            if not isinstance(roles_and_presets, list) or any(
                not isinstance(item, tuple)
                or len(item) != 2
                or not all(isinstance(value, str) and bool(value) for value in item)
                for item in roles_and_presets
            ):
                raise TypeError(
                    "roles_and_presets must contain non-empty (name, role) string tuples."
                )
        for role, config in (member_configs or {}).items():
            if not isinstance(role, str) or not role:
                raise ValueError("Member role names must be non-empty strings.")
            if isinstance(config, Agent):
                raise TypeError(
                    "member_configs creates new Agents and cannot contain existing Agent objects; "
                    "use existing_members instead."
                )
            if not isinstance(config, dict):
                raise TypeError(f"Member configuration for {role!r} must be a mapping.")
            allowed = {
                "model",
                "role_description",
                "system_instructions",
            }
            unknown = set(config) - allowed
            if unknown:
                raise ValueError(
                    f"Unknown member configuration fields for {role!r}: {sorted(unknown)}."
                )
            alias = config.get("model")
            if alias and alias != "default" and alias not in available_models:
                raise ValueError(f"Model {alias!r} is not registered.")
            for field in {"role_description", "system_instructions"}:
                if field in config and not isinstance(config[field], str):
                    raise TypeError(f"{field} for {role!r} must be a string.")
        if initial_docs is not None:
            if not isinstance(initial_docs, dict):
                raise TypeError("initial_docs must be a dictionary.")
            for path, content in initial_docs.items():
                if not isinstance(path, str) or not path.strip():
                    raise ValueError("Initial document paths must be non-empty strings.")
                try:
                    DocumentLibrary._normalize_path(path, allow_root=False)
                except PermissionError as exc:
                    raise ValueError(f"Invalid initial document path {path!r}.") from exc
                if not isinstance(content, str):
                    raise TypeError(f"Initial document content for {path!r} must be a string.")

    def _validate_team_creation_commit(self, stage: Dict[str, Any]) -> None:
        """Revalidates all live references immediately before publication."""
        manager = self.manager
        if manager._closing:
            raise RuntimeError("ATTManager is closing and rejects new teams.")
        team = stage["team"]
        creator = team.creator
        if isinstance(creator, AgentTeam):
            if manager.teams.get(creator.team_id) is not creator:
                raise ValueError("The creator AgentTeam changed during team staging.")
            current_parent = creator
        else:
            if creator.lifecycle_state != "active":
                raise ValueError("The creator Agent is no longer active.")
            current_parent = manager.get_agent_team(creator)
        if current_parent is not stage["parent"]:
            raise ValueError("The proposed parent changed during team staging.")
        if team.team_id in manager.teams:
            raise ValueError(f"AgentTeam ID {team.team_id!r} is already registered.")
        for lib_id in stage["libraries"]:
            if lib_id in manager.libraries:
                raise ValueError(f"Document library {lib_id!r} is already registered.")
        for agent in stage["new_agents"]:
            existing_id = manager._agents_by_id.get(agent.agent_id)
            existing_name = manager.agents.get(agent.name)
            if existing_id is not None or existing_name is not None:
                raise ValueError(f"Agent identity {agent.name!r} changed during team staging.")
        for agent in stage["existing_agents"]:
            if (
                manager._agents_by_id.get(agent.agent_id) is not agent
                or manager.agents.get(agent.name) is not agent
                or agent.lifecycle_state != "active"
            ):
                raise ValueError(
                    f"Existing Agent {agent.name!r} changed during team staging."
                )
