"""State restore workflow for RestoreHydrationMixin."""

import asyncio
import json
import logging
import time
from typing import Any, Dict

from ...adapters import HandlerClientAdapter, ManagerDefaultClientAdapter
from ...agent import Agent
from ...config import ATTConfig
from ...exceptions import StateRestoreError
from ...team import AgentTeam


class RestoreHydrationMixin:
    async def _apply_state_snapshot_unvalidated(self, state: Dict[str, Any]) -> None:
        manager = self.manager
        configs = state["configs"]
        config_data = json.loads(configs["att_config"])
        manager.config = ATTConfig(**config_data)
        manager.model_configs = json.loads(configs.get("model_configs", "{}"))
        manager.presets = json.loads(configs.get("presets", "{}"))
        manager.model_token_usage = json.loads(configs.get("model_token_usage", "{}"))

        required_aliases = {
            row["model_alias"]
            for row in state["agents"]
            if row.get("lifecycle_state", "active") == "active"
            and row.get("model_alias") != "default"
        }
        missing_aliases = sorted(
            alias
            for alias in required_aliases
            if alias not in manager.llm_clients
            and not (manager.generator_handler and alias in manager.model_configs)
        )
        if missing_aliases:
            raise StateRestoreError(
                "Missing runtime bindings for model aliases: " + ", ".join(missing_aliases)
            )

        manager.agents.clear()
        manager._agents_by_id.clear()
        for row in state["agents"]:
            alias = row.get("model_alias")
            lifecycle_state = row.get("lifecycle_state", "active")
            if lifecycle_state != "active":
                client = None
            elif alias in manager.llm_clients:
                client = manager.llm_clients[alias]
            elif (
                alias != "default" and alias in manager.model_configs and manager.generator_handler
            ):
                client = HandlerClientAdapter(alias, manager.generator_handler)
                client._supports_native = manager.model_configs.get(alias, {}).get(
                    "supports_native_tool_calling", False
                )
            elif alias == "default" and manager.generator_handler:
                client = ManagerDefaultClientAdapter(manager)
            else:
                raise StateRestoreError(
                    f"No runtime binding is available for agent {row['name']!r}."
                )
            agent = Agent(
                name=row["name"],
                role=row["role"],
                llm_client=client,
                role_description=row["role_description"] or "",
                system_instructions=row["system_instructions"] or "",
                agent_id=row["agent_id"],
            )
            agent.lifecycle_state = lifecycle_state
            agent._model_alias = alias
            agent._private_doc_library_id = f"PDL-{agent.agent_id}"
            agent._manager = manager
            agent.last_context = json.loads(row["last_context"]) if row["last_context"] else None
            agent.messages = []
            agent.message_history = []
            agent._history_seen_ids = set()
            for message in row["messages"]:
                restored = {key: value for key, value in message.items() if value is not None}
                agent.messages.append(restored)
                agent._history_seen_ids.add(id(restored))
            manager._agents_by_id[agent.agent_id] = agent
            if lifecycle_state == "active":
                manager.agents[agent.name] = agent

        root_id = configs["root_ai_id"]
        if root_id not in manager._agents_by_id:
            raise StateRestoreError(f"Persisted root agent {root_id!r} was not found.")
        manager.root_ai = manager._agents_by_id[root_id]
        manager.supervisor.root_ai = manager.root_ai

        manager.libraries.clear()
        manager._library_files.clear()
        for row in state["libraries"]:
            library = manager._new_document_library(
                lib_id=row["lib_id"],
                name=row["name"],
                owner_team_id=row["owner_team_id"],
                owner_agent_id=row.get("owner_agent_id"),
                library_kind=row.get("library_kind", "team"),
                lifecycle_state=row.get("lifecycle_state", "active"),
                description=row["description"] or "",
                is_public_visible=row["is_public_visible"],
            )
            await asyncio.to_thread(library._restore_all_files, row["files"])
            manager.libraries[library.lib_id] = library
            manager._library_files[library.lib_id] = dict(row["files"])
        manager.library_permissions = state["permissions"]
        manager.library_links = state.get("links", {})

        manager.teams.clear()
        manager._team_parent_map.clear()
        team_map: Dict[str, AgentTeam] = {}
        for row in state["teams"]:
            creator = (
                manager._agents_by_id.get(row["creator_id"])
                if row["creator_type"] == "agent"
                else None
            )
            team = AgentTeam(
                creator=creator,
                preset_name=row["preset_name"],
                team_purpose=row["team_purpose"],
            )
            team.team_id = row["team_id"]
            team.logger = logging.getLogger(f"AgentTeam:{team.team_id}")
            team.team_progress = row["team_progress"]
            team.chapter_num = row["chapter_num"]
            team.migration_count = row["migration_count"] or 0
            team.status_map = json.loads(row["status_map"] or "{}")
            team.system_instructions = row["system_instructions"] or ""
            team._cached_depth = None
            team.manager = manager
            team.message_inbox = row["inbox"]
            for message in team.message_inbox:
                if message.get("type") == "audit_unknown_escalation":
                    message.setdefault(
                        "fingerprint",
                        manager._unknown_alert_fingerprint(message),
                    )
                    message.setdefault("occurrence_count", 1)
                    message.setdefault("first_seen", time.time())
                    message.setdefault("last_seen", message["first_seen"])
                    if message.get("state") == "processing":
                        message["state"] = "pending"
                    else:
                        message.setdefault("state", "pending")
                    message.pop("processing_count", None)
            team.proposals = {
                proposal["proposal_id"]: {
                    key: value for key, value in proposal.items() if key != "proposal_id"
                }
                for proposal in row["proposals"]
            }
            team.members = [manager._agents_by_id[agent_id] for agent_id in row["members"]]
            team_map[team.team_id] = team

        for row in state["teams"]:
            team = team_map[row["team_id"]]
            parent_id = row["parent_team_id"]
            if parent_id:
                parent = team_map[parent_id]
                team._parent_team = parent
                parent.child_teams.append(team)
                manager._team_parent_map[team.team_id] = parent_id
            if row["creator_type"] == "team":
                team.creator = team_map.get(row["creator_id"])
        manager.teams = team_map

        from ai_team_team.tool import get_default_tools

        for team in manager.teams.values():
            team.doc_library = manager.libraries.get(f"DL-{team.team_id}")
            team.tools = get_default_tools(manager.tools_context, team)
            team.tools.update(manager.global_tools)

        manager.broker.restore(
            state.get("communication_requests", []),
            state.get("communication_approvals", []),
            state.get("communication_ballots", []),
            state.get("communication_agreements", []),
            state.get("peer_messages", []),
        )
        manager._memory.restore(
            state.get("memory_events", []),
            state.get("memory_segments", []),
            state.get("memory_cards", []),
            state.get("memory_references", []),
        )
        for agent in manager._agents_by_id.values():
            agent.message_history = [
                dict(event.payload)
                for event in sorted(
                    manager._memory.events.values(),
                    key=lambda item: item.sequence,
                )
                if event.agent_id == agent.agent_id
                and event.event_type == "message"
            ]
