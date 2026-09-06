"""AgentTeam creation workflow for TeamCreationTransactionMixin."""

import os
import shutil
import tempfile
from typing import Any, Dict, List, Optional, Tuple


from ...agent import Agent
from ...team import AgentTeam


class TeamCreationTransactionMixin:
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
    ) -> AgentTeam:
        """Stages off-registry objects and atomically publishes one AgentTeam."""
        manager = self.manager
        if manager._closing:
            raise RuntimeError("ATTManager is closing and rejects new teams.")
        manager._validate_team_creation_inputs(
            creator=creator,
            member_count=member_count,
            roles_and_presets=roles_and_presets,
            roles_and_models=roles_and_models,
            member_configs=member_configs,
            existing_members=existing_members,
            existing_member_ids=existing_member_ids,
            initial_docs=initial_docs,
            preset_name=preset_name,
            system_instructions=system_instructions,
            team_purpose=team_purpose,
            is_public_visible=is_public_visible,
        )
        managed_root = os.path.join(
            os.path.realpath(os.path.abspath(manager.config.workspace_root)),
            ".att_doc_libs",
        )
        if os.path.lexists(managed_root) and os.path.islink(managed_root):
            raise PermissionError("The managed DocLib root cannot be a symlink.")
        os.makedirs(managed_root, exist_ok=True)
        staging_root = tempfile.mkdtemp(prefix=".att-team-stage-", dir=managed_root)
        published: List[Tuple[str, Optional[str]]] = []
        snapshot: Optional[Dict[str, Any]] = None
        stage: Optional[Dict[str, Any]] = None
        try:
            stage = manager._create_agent_team(
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
                staging_root=staging_root,
            )
            with manager._topology_lock:
                manager._validate_team_creation_commit(stage)
                snapshot = manager._team_creation_snapshot()
                published = manager._publish_new_staged_libraries(stage["libraries"], managed_root)
                manager.libraries.update(stage["libraries"])
                manager._library_files.update(stage["library_files"])
                for agent in stage["new_agents"]:
                    manager.register_agent(agent, auto_save=False)
                team = stage["team"]
                manager.teams[team.team_id] = team
                parent = stage["parent"]
                if parent is not None:
                    manager._team_parent_map[team.team_id] = parent.team_id
                    parent.add_child_team(team)
            manager._discard_library_backups(published)
        except Exception:
            if published:
                manager._rollback_published_libraries(published)
            if snapshot is not None:
                with manager._topology_lock:
                    manager._rollback_team_creation(snapshot)
            raise
        finally:
            shutil.rmtree(staging_root, ignore_errors=True)

        manager.logger.info(
            "Successfully spawned AgentTeam %s with %s members.",
            team.team_id,
            len(team.members),
        )
        registration_event_ids = {
            manager._memory.record_event(
                "agent_registered",
                agent=agent,
                payload={"lifecycle_state": "active"},
                persist=False,
                inherit_context=False,
            ).event_id
            for agent in stage["new_agents"]
        }
        manager._auto_save(
            configs=True,
            agents={agent.agent_id for agent in stage["new_agents"]},
            teams={team.team_id} | ({team.parent_team.team_id} if team.parent_team else set()),
            libraries=set(stage["libraries"]),
            memory_events=registration_event_ids,
        )
        return team

    def _team_creation_snapshot(self) -> Dict[str, Any]:
        manager = self.manager
        return {
            "agents": dict(manager.agents),
            "agents_by_id": dict(manager._agents_by_id),
            "teams": dict(manager.teams),
            "libraries": dict(manager.libraries),
            "library_files": dict(manager._library_files),
            "parent_map": dict(manager._team_parent_map),
            "children": {
                team_id: list(team.child_teams) for team_id, team in manager.teams.items()
            },
            "private_ids": {
                id(agent): agent.private_doc_library_id for agent in manager._agents_by_id.values()
            },
        }

    def _rollback_team_creation(self, snapshot: Dict[str, Any]) -> None:
        manager = self.manager
        prior_library_ids = set(snapshot["libraries"])
        for lib_id, library in list(manager.libraries.items()):
            if lib_id not in prior_library_ids:
                shutil.rmtree(library.root_dir, ignore_errors=True)
        for agent in manager._agents_by_id.values():
            if id(agent) not in snapshot["private_ids"]:
                agent._private_doc_library_id = None
                agent._manager = None
        manager._agent_registry.replace_indexes(
            snapshot["agents"],
            snapshot["agents_by_id"],
        )
        manager.teams = snapshot["teams"]
        manager.libraries = snapshot["libraries"]
        manager._library_files = snapshot["library_files"]
        manager._team_parent_map = snapshot["parent_map"]
        for team_id, children in snapshot["children"].items():
            manager.teams[team_id].child_teams = children
