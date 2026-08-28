"""AgentTeam creation workflow for TeamCreationValidationMixin."""

from typing import Any, Dict, List, Optional, Tuple

from ai_team_team.doc_library import DocumentLibrary

from ...agent import Agent
from ...team import AgentTeam


class TeamCreationValidationMixin:
    def _validate_team_creation_inputs(
        self,
        *,
        creator: Any,
        member_count: int,
        roles_and_presets: Optional[List[Tuple[str, str]]],
        roles_and_models: Optional[Dict[str, str]],
        member_configs: Optional[Dict[str, Dict[str, Any]]],
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
        effective_count = len(member_configs) if member_configs else member_count
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
            if len(roles_and_presets) < manager.config.min_subagent_team_size:
                raise ValueError(
                    f"roles_and_presets must define at least {manager.config.min_subagent_team_size} members."
                )
        for role, config in (member_configs or {}).items():
            if not isinstance(role, str) or not role:
                raise ValueError("Member role names must be non-empty strings.")
            if isinstance(config, Agent):
                continue
            if not isinstance(config, dict):
                raise TypeError(f"Member configuration for {role!r} must be a mapping or Agent.")
            allowed = {
                "model",
                "hire_agent",
                "role_description",
                "system_instructions",
            }
            unknown = set(config) - allowed
            if unknown:
                raise ValueError(
                    f"Unknown member configuration fields for {role!r}: {sorted(unknown)}."
                )
            if config.get("model") and config.get("hire_agent"):
                raise ValueError("model and hire_agent are mutually exclusive.")
            hired = config.get("hire_agent")
            if hired is not None and hired not in manager.agents:
                raise ValueError(f"Agent {hired!r} is not registered.")
            alias = config.get("model")
            if (
                alias
                and alias != "default"
                and alias not in available_models
                and alias not in manager.agents
            ):
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
