"""AgentTeam creation workflow for TeamCreationTransactionMixin."""

import os
import shutil
import tempfile
from typing import Any, Dict, List, Optional, Tuple, Union


from ...agent import Agent
from ...team import AgentTeam
from ...formation import TeamFormationRequest


class TeamCreationTransactionMixin:
    def create_supervisory_team(self) -> AgentTeam:
        """Provision one audit-scoped AgentTeam through the normal staged transaction."""
        roles = [
            ("Auditor_Integrity_01", "Integrity_Auditor"),
            ("Auditor_Continuity_02", "Continuity_Auditor"),
            ("Auditor_Deadlock_03", "Deadlock_Auditor"),
        ]
        for index in range(len(roles), self.manager.config.min_subagent_team_size):
            roles.append((f"Auditor_Review_{index + 1:02d}", "Review_Auditor"))
        return self.create_immediate(
            creator=self.manager.root_ai,
            roles_and_presets=roles,
            preset_name="supervisor_audit",
            team_purpose="Audit one AgentTeam discussion for content and operational health.",
            system_instructions=(
                "You are an objective supervisory audit team. Review the supplied "
                "discussion for reasoning continuity, deadlocks, and role alignment. "
                "Do not perform ordinary team operations or request tools."
            ),
            team_kind="supervisory",
            parent_override=None,
            parent_override_provided=True,
        )

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
        """Creates an all-new team or opens consent for any existing identity."""
        if existing_members or existing_member_ids or initiator_joins:
            return self.manager._formations.propose_team_formation(
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
        return self.create_immediate(
            creator=creator,
            member_count=member_count,
            roles_and_presets=roles_and_presets,
            preset_name=preset_name,
            system_instructions=system_instructions,
            team_purpose=team_purpose,
            roles_and_models=roles_and_models,
            member_configs=member_configs,
            is_public_visible=is_public_visible,
            initial_docs=initial_docs,
        )

    def bootstrap_agent_team(self, creator: Any, **kwargs: Any) -> AgentTeam:
        """Trusted host-only topology bootstrap that bypasses interactive consent explicitly."""
        reserved = {
            "authorized_existing",
            "parent_override",
            "parent_override_provided",
            "required_creator_member_agent_id",
            "record_registration_events",
        }.intersection(kwargs)
        if reserved:
            raise TypeError(
                "Trusted bootstrap does not accept internal transaction controls: "
                + ", ".join(sorted(reserved))
            )
        team = self.create_immediate(
            creator=creator,
            authorized_existing=True,
            **kwargs,
        )
        manager = self.manager
        creator_kind = "agent_team" if isinstance(creator, AgentTeam) else "agent"
        creator_id = creator.team_id if isinstance(creator, AgentTeam) else creator.agent_id
        event = manager._memory.record_event(
            "trusted_team_bootstrap",
            agent=None,
            team=team,
            payload={
                "team_id": team.team_id,
                "member_count": len(team.members),
                "creator_kind": creator_kind,
                "creator_id": creator_id,
            },
            persist=False,
            inherit_context=False,
        )
        manager._auto_save(memory_events={event.event_id})
        manager._emit_callback(
            "on_system_event",
            "trusted_team_bootstrap",
            {
                "team_id": team.team_id,
                "member_count": len(team.members),
                "creator_kind": creator_kind,
                "creator_id": creator_id,
            },
        )
        return team

    def create_immediate(
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
        *,
        authorized_existing: bool = False,
        parent_override: Optional[AgentTeam] = None,
        parent_override_provided: bool = False,
        required_creator_member_agent_id: Optional[str] = None,
        record_registration_events: bool = True,
        team_kind: str = "ordinary",
    ) -> AgentTeam:
        """Stages off-registry objects and atomically publishes one AgentTeam."""
        manager = self.manager
        if manager._restore_in_progress:
            raise RuntimeError("ATTManager is restoring state and rejects new teams.")
        if (existing_members or existing_member_ids) and not authorized_existing:
            raise PermissionError(
                "Existing Agents require a formation invitation or the explicit trusted bootstrap API."
            )
        if manager._closing:
            raise RuntimeError("ATTManager is closing and rejects new teams.")
        if team_kind not in {"ordinary", "supervisory"}:
            raise ValueError("team_kind must be ordinary or supervisory.")
        if team_kind == "supervisory" and (
            creator is not manager.root_ai
            or not parent_override_provided
            or parent_override is not None
            or existing_members
            or existing_member_ids
            or is_public_visible
        ):
            raise ValueError("A supervisory team must be a private, root-created system leaf.")
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
                parent_override=parent_override,
                parent_override_provided=parent_override_provided,
                required_creator_member_agent_id=required_creator_member_agent_id,
                staging_root=staging_root,
                team_kind=team_kind,
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
        if team_kind == "supervisory":
            # Audit-scoped identities never enter state snapshots. The audit
            # completion event records their IDs and work before teardown.
            return team
        registration_event_ids = set()
        if record_registration_events:
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
