"""AgentTeam creation workflow for TeamCreationStagingMixin."""

import os
from typing import Any, Dict, List, Optional, Tuple

from ai_team_team.doc_library import DocumentLibrary

from ...adapters import HandlerClientAdapter, ManagerDefaultClientAdapter
from ...agent import Agent
from ...team import AgentTeam


class TeamCreationStagingMixin:
    def unique_agent_name(self, base_name: str, team: AgentTeam) -> str:
        """Returns a registry-safe agent name for a team."""
        manager = self.manager
        if base_name not in manager.agents:
            return base_name
        suffix = team.team_id.split("-", 1)[-1]
        candidate = f"{base_name}_{suffix}"
        counter = 2
        while candidate in manager.agents:
            candidate = f"{base_name}_{suffix}_{counter}"
            counter += 1
        return candidate

    def _create_agent_team(
        self,
        creator: Any,
        member_count: int = 3,
        roles_and_presets: List[Tuple[str, str]] = None,
        preset_name: str = "custom",
        system_instructions: str = "",
        team_purpose: str = "Unspecified team purpose",
        roles_and_models: Optional[Dict[str, str]] = None,
        member_configs: Optional[Dict[str, Dict[str, Any]]] = None,
        is_public_visible: bool = False,
        initial_docs: Optional[Dict[str, str]] = None,
        *,
        staging_root: str,
    ) -> Dict[str, Any]:
        """Builds a complete AgentTeam transaction without live registration."""
        manager = self.manager
        if member_configs:
            member_count = len(member_configs)
        team = AgentTeam(
            creator=creator,
            preset_name=preset_name,
            team_purpose=team_purpose,
        )
        team.manager = manager
        parent = creator if isinstance(creator, AgentTeam) else manager.get_agent_team(creator)
        team._parent_team = parent
        if isinstance(creator, AgentTeam):
            team.chapter_num = creator.chapter_num
        elif parent is not None:
            team.chapter_num = parent.chapter_num

        def client_by_alias(alias: Optional[str]) -> Any:
            if alias and alias != "default":
                if alias in manager.llm_clients:
                    return manager.llm_clients[alias]
                if alias in manager.model_configs and manager.generator_handler:
                    adapter = HandlerClientAdapter(alias, manager.generator_handler)
                    adapter._supports_native = (
                        manager.model_configs.get(alias, {}).get("supports_native_tool_calling")
                        is True
                    )
                    return adapter
                raise ValueError(f"Model {alias!r} is not registered.")
            if "default" in manager.llm_clients:
                return manager.llm_clients["default"]
            if manager.root_ai.llm_client:
                return manager.root_ai.llm_client
            return ManagerDefaultClientAdapter(manager)

        def client_for_role(role: str, name: str) -> Any:
            alias = None
            if roles_and_models:
                alias = roles_and_models.get(role) or roles_and_models.get(name)
            return client_by_alias(alias)

        members: List[Agent] = []
        role_updates: List[Tuple[Agent, str, str]] = []
        if member_configs:
            for role_name, config in member_configs.items():
                if isinstance(config, Agent):
                    agent = config
                    role_updates.append((agent, role_name, agent.role))
                elif config.get("hire_agent") in manager.agents:
                    agent = manager.agents[config["hire_agent"]]
                elif config.get("model") in manager.agents:
                    agent = manager.agents[config["model"]]
                else:
                    agent = Agent(
                        name=(f"Dynamic_{role_name}_{team.team_id.split('-', 1)[1]}"),
                        role=role_name,
                        llm_client=client_by_alias(config.get("model")),
                        role_description=config.get("role_description", ""),
                        system_instructions=config.get("system_instructions", ""),
                    )
                members.append(agent)
        elif roles_and_presets:
            for name, role in roles_and_presets:
                members.append(
                    Agent(
                        name=manager.unique_agent_name(name, team),
                        role=role,
                        llm_client=client_for_role(role, name),
                    )
                )
        else:
            roles = manager.get_preset(preset_name).get("roles", [])
            if len(roles) >= member_count:
                for name, role in roles[:member_count]:
                    members.append(
                        Agent(
                            name=manager.unique_agent_name(name, team),
                            role=role,
                            llm_client=client_for_role(role, name),
                        )
                    )
            else:
                for index in range(member_count):
                    name = f"{team.team_id}_member_{index + 1}"
                    members.append(
                        Agent(
                            name=name,
                            role="Specialist",
                            llm_client=client_for_role("Specialist", name),
                        )
                    )
        if len({agent.agent_id for agent in members}) != len(members):
            raise ValueError("An AgentTeam cannot contain duplicate Agent identities.")
        if len({agent.name for agent in members}) != len(members):
            raise ValueError("An AgentTeam cannot contain duplicate Agent names.")
        team.members = members
        team.system_instructions = system_instructions or manager.get_preset(preset_name).get(
            "system_instructions", ""
        )

        from ai_team_team.tool import get_default_tools

        team.tools.update(get_default_tools(manager.tools_context, team))
        team.tools.update(manager.global_tools)

        registered_agents: List[Agent] = []
        for agent in [creator, *members]:
            if not isinstance(agent, Agent):
                continue
            if all(existing is not agent for existing in registered_agents):
                registered_agents.append(agent)
        new_agents = [
            agent
            for agent in registered_agents
            if manager._agents_by_id.get(agent.agent_id) is not agent
        ]

        libraries: Dict[str, DocumentLibrary] = {}
        library_files: Dict[str, Dict[str, str]] = {}
        for agent in new_agents:
            expected_id = f"PDL-{agent.agent_id}"
            if (
                agent.private_doc_library_id is not None
                and agent.private_doc_library_id != expected_id
            ):
                raise ValueError(f"Private DocLib ID must be {expected_id!r}.")
            if expected_id in manager.libraries:
                raise ValueError(f"Private DocLib {expected_id!r} is already registered.")
            library = manager._build_document_library(
                lib_id=expected_id,
                name=f"{agent.name} Private Library",
                owner_agent_id=agent.agent_id,
                library_kind="agent_private",
                lifecycle_state="active",
                description=(f"Persistent private workspace for agent {agent.name}."),
                is_public_visible=False,
                storage_dir=os.path.join(staging_root, expected_id),
            )
            libraries[expected_id] = library
            library_files[expected_id] = {}

        team_lib_id = f"DL-{team.team_id}"
        team_library = manager._build_document_library(
            lib_id=team_lib_id,
            name=f"{team.team_id} Built-in Library",
            owner_team_id=team.team_id,
            description=f"Default document library for team {team.team_id}.",
            is_public_visible=is_public_visible,
            storage_dir=os.path.join(staging_root, team_lib_id),
        )
        libraries[team_lib_id] = team_library
        library_files[team_lib_id] = {}
        team.doc_library = team_library
        if initial_docs:
            for path, content in initial_docs.items():
                clean_path = team_library._write_staged_file(path, content)
                library_files[team_lib_id][clean_path] = content

        return {
            "team": team,
            "parent": parent,
            "new_agents": new_agents,
            "registered_agents": registered_agents,
            "role_updates": role_updates,
            "libraries": libraries,
            "library_files": library_files,
        }
