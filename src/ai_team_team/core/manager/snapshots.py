"""Builds immutable persistence snapshots from versioned runtime state."""

import time
from typing import TYPE_CHECKING, Any, Dict, List

from ai_team_team.database.persistence import STATE_SCHEMA_VERSION

from ..agent import Agent
from ..team import AgentTeam

if TYPE_CHECKING:
    from .facade import ATTManager


class SnapshotBuilder:
    """Builds immutable persistence snapshots from versioned runtime state."""

    def __init__(self, manager: "ATTManager") -> None:
        self.manager = manager

    def _capture_state_snapshot(self, dirty: Dict[str, Any]) -> Dict[str, Any]:
        manager = self.manager
        full = dirty["full"]
        now = time.time()
        configs = None
        if full or dirty["configs"]:
            configs = {
                "schema_version": STATE_SCHEMA_VERSION,
                "att_config": manager.config.to_dict(),
                "root_ai_id": manager.root_ai.agent_id,
                "model_configs": {
                    alias: dict(config) for alias, config in manager.model_configs.items()
                },
                "presets": {
                    name: {
                        **preset,
                        "roles": tuple(tuple(role) for role in preset.get("roles", ())),
                    }
                    for name, preset in manager.presets.items()
                },
                "model_token_usage": dict(manager.model_token_usage),
            }

        agent_lookup = dict(manager._agents_by_id)
        relevant_teams = (
            manager.teams.values()
            if full
            else (manager.teams[team_id] for team_id in dirty["teams"] if team_id in manager.teams)
        )
        for relevant_team in relevant_teams:
            for member in relevant_team.members:
                agent_lookup.setdefault(member.agent_id, member)
        agent_ids = set(agent_lookup) if full else set()
        if not full:
            for identifier in dirty["agents"]:
                if identifier in agent_lookup:
                    agent_ids.add(identifier)
                elif identifier in manager.agents:
                    agent_ids.add(manager.agents[identifier].agent_id)
        if not full:
            for team_id in dirty["teams"]:
                team = manager.teams.get(team_id)
                if team is not None:
                    agent_ids.update(member.agent_id for member in team.members)
        agents = []
        unresolved_agents: List[str] = []
        for agent_id in sorted(agent_ids):
            agent = agent_lookup.get(agent_id)
            if agent is None:
                continue
            try:
                if agent.lifecycle_state == "active":
                    model_alias = manager.resolve_model_alias(agent.llm_client)
                else:
                    model_alias = agent._model_alias
                    if model_alias is None and agent.llm_client is not None:
                        model_alias = manager.resolve_model_alias(agent.llm_client)
            except ValueError:
                unresolved_agents.append(agent.name)
                continue
            if agent.lifecycle_state == "active" and model_alias is None:
                unresolved_agents.append(agent.name)
                continue
            agents.append(
                {
                    "agent_id": agent.agent_id,
                    "name": agent.name,
                    "role": agent.role,
                    "role_description": getattr(agent, "role_description", ""),
                    "system_instructions": getattr(agent, "system_instructions", ""),
                    "model_alias": model_alias,
                    "lifecycle_state": agent.lifecycle_state,
                    "last_context": (dict(agent.last_context) if agent.last_context else None),
                    "messages": tuple(dict(message) for message in manager._agent_history(agent)),
                    "message_timestamp": now,
                }
            )
        if unresolved_agents:
            raise ValueError(
                "Cannot persist agents whose LLM clients have no stable, "
                "unique registered alias: " + ", ".join(unresolved_agents)
            )

        team_ids = set(manager.teams) if full else set(dirty["teams"])
        teams = []
        for team_id in sorted(team_ids):
            team = manager.teams.get(team_id)
            if team is None:
                continue
            creator_type = None
            creator_id = None
            if isinstance(team.creator, Agent):
                creator_type = "agent"
                creator_id = team.creator.agent_id
            elif isinstance(team.creator, AgentTeam):
                creator_type = "team"
                creator_id = team.creator.team_id
            teams.append(
                {
                    "team_id": team.team_id,
                    "preset_name": team.preset_name,
                    "team_purpose": team.team_purpose,
                    "team_progress": team.team_progress,
                    "depth": team.depth,
                    "chapter_num": team.chapter_num,
                    "parent_team_id": (team.parent_team.team_id if team.parent_team else None),
                    "migration_count": team.migration_count,
                    "creator_type": creator_type,
                    "creator_id": creator_id,
                    "status_map": team.status_snapshot(),
                    "system_instructions": getattr(team, "system_instructions", ""),
                    "members": [member.agent_id for member in team.members],
                    "message_timestamp": now,
                }
            )

        inbox_ids = set(manager.teams) if full else set(dirty["inboxes"])
        inboxes = {}
        for team_id in sorted(inbox_ids):
            team = manager.teams.get(team_id)
            if team is None:
                continue
            with team.inbox_lock:
                messages = tuple(dict(message) for message in team.message_inbox)
            inboxes[team_id] = {
                "messages": messages,
                "message_timestamp": now,
            }
        proposal_ids = set(manager.teams) if full else set(dirty["proposals"])
        proposals = {
            team_id: [
                {
                    "proposal_id": proposal_id,
                    **{
                        key: dict(value) if isinstance(value, dict) else value
                        for key, value in proposal.items()
                    },
                }
                for proposal_id, proposal in manager.teams[team_id].proposals.items()
            ]
            for team_id in sorted(proposal_ids)
            if team_id in manager.teams
        }

        library_ids = set(manager.libraries) if full else set(dirty["libraries"])
        libraries = []
        for lib_id in sorted(library_ids):
            library = manager.libraries.get(lib_id)
            if library is None:
                continue
            libraries.append(
                {
                    "lib_id": library.lib_id,
                    "name": library.name,
                    "owner_team_id": library.owner_team_id,
                    "owner_agent_id": library.owner_agent_id,
                    "library_kind": library.library_kind,
                    "lifecycle_state": library.lifecycle_state,
                    "description": library.description,
                    "is_public_visible": library.is_public_visible,
                }
            )

        permission_ids = set(manager.libraries) if full else set(dirty["permissions"])
        permissions = {
            lib_id: {
                path: dict(team_map)
                for path, team_map in manager.library_permissions.get(lib_id, {}).items()
            }
            for lib_id in permission_ids
        }
        link_ids = set(manager.libraries) if full else set(dirty["links"])
        links = {
            lib_id: {
                path: dict(target) for path, target in manager.library_links.get(lib_id, {}).items()
            }
            for lib_id in link_ids
        }

        file_changes = {lib_id: dict(changes) for lib_id, changes in dirty["file_changes"].items()}
        if full:
            for lib_id in manager.libraries:
                file_changes[lib_id] = dict(manager._library_files.get(lib_id, {}))

        request_ids = (
            set(manager.broker.communication_requests)
            if full
            else set(dirty["communication_requests"])
        )
        approval_request_ids = (
            set(manager.broker.communication_requests)
            if full
            else set(dirty["communication_approvals"])
        )
        agreement_ids = (
            set(manager.broker.agreements) if full else set(dirty["communication_agreements"])
        )
        peer_message_ids = (
            set(manager.broker.peer_messages) if full else set(dirty["peer_messages"])
        )
        communication_requests = [
            manager.broker.communication_requests[request_id].model_dump(mode="json")
            for request_id in sorted(request_ids)
            if request_id in manager.broker.communication_requests
        ]
        communication_approvals = [
            approval.model_dump(mode="json")
            for request_id in sorted(approval_request_ids)
            for approval in manager.broker.approvals_for_request(request_id)
        ]
        communication_ballots = [
            ballot.model_dump(mode="json")
            for request_id in sorted(approval_request_ids)
            for ballot in manager.broker.ballots.get(request_id, [])
        ]
        communication_agreements = [
            manager.broker.agreements[agreement_id].model_dump(mode="json")
            for agreement_id in sorted(agreement_ids)
            if agreement_id in manager.broker.agreements
        ]
        peer_messages = [
            manager.broker.peer_messages[message_id].model_dump(mode="json")
            for message_id in sorted(peer_message_ids)
            if message_id in manager.broker.peer_messages
        ]

        return {
            "state_version": manager._state_version,
            "full": full,
            "configs": configs,
            "agents": agents,
            "teams": teams,
            "inboxes": inboxes,
            "proposals": proposals,
            "communication_requests": communication_requests,
            "communication_approvals": communication_approvals,
            "communication_ballots": communication_ballots,
            "communication_agreements": communication_agreements,
            "peer_messages": peer_messages,
            "libraries": libraries,
            "permissions": permissions,
            "links": links,
            "file_changes": file_changes,
            "deleted_agents": tuple(dirty["deleted_agents"]),
            "deleted_libraries": tuple(dirty["deleted_libraries"]),
        }
