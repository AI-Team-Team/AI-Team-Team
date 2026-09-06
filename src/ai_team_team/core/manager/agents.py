"""Stable Agent identity registration and lifecycle transitions."""

import os
import shutil
import uuid
from typing import TYPE_CHECKING, Dict, Optional, Tuple

from ai_team_team.doc_library import DocumentLibrary

from ..adapters import HandlerClientAdapter, ManagerDefaultClientAdapter
from ..agent import Agent

if TYPE_CHECKING:
    from ..manager import ATTManager


class AgentRegistry:
    """Owns active/all Agent indexes and private-workspace lifecycle."""

    def __init__(self, manager: "ATTManager") -> None:
        self.manager = manager
        self.active_by_name: Dict[str, Agent] = {}
        self.by_id: Dict[str, Agent] = {}

    def replace_indexes(
        self,
        active_by_name: Dict[str, Agent],
        by_id: Dict[str, Agent],
    ) -> None:
        """Atomically rebinds every public and internal Agent index alias."""
        self.active_by_name = active_by_name
        self.by_id = by_id
        self.manager.agents = active_by_name
        self.manager._agents_by_id = by_id

    def register(self, agent: Agent, *, auto_save: bool = True) -> Agent:
        manager = self.manager
        if not isinstance(agent, Agent):
            raise TypeError("agent must be an Agent instance.")
        if agent.lifecycle_state != "active":
            raise ValueError(
                "Only a new active Agent can be registered; inactive "
                "identities require reactivate_agent()."
            )
        existing_by_id = self.by_id.get(agent.agent_id)
        if existing_by_id is not None and existing_by_id is not agent:
            raise ValueError(f"Agent ID {agent.agent_id!r} is already registered.")
        existing_by_name = self.active_by_name.get(agent.name)
        if existing_by_name is not None and existing_by_name is not agent:
            raise ValueError(f"Agent name {agent.name!r} is already registered.")
        for known in self.by_id.values():
            if known is not agent and known.name == agent.name:
                raise ValueError(f"Agent name {agent.name!r} is already reserved.")

        agent.lifecycle_state = "active"
        lib_id = agent.private_doc_library_id or f"PDL-{agent.agent_id}"
        expected = f"PDL-{agent.agent_id}"
        if lib_id != expected:
            raise ValueError(f"Private DocLib ID must be {expected!r} for this agent.")
        library = manager.libraries.get(lib_id)
        if library is None:
            library = manager._new_document_library(
                lib_id=lib_id,
                name=f"{agent.name} Private Library",
                owner_agent_id=agent.agent_id,
                library_kind="agent_private",
                lifecycle_state="active",
                description=(f"Persistent private workspace for agent {agent.name}."),
                is_public_visible=False,
            )
            manager.libraries[lib_id] = library
        elif library.library_kind != "agent_private" or library.owner_agent_id != agent.agent_id:
            raise ValueError("Private DocLib ownership is inconsistent.")
        agent._private_doc_library_id = lib_id
        agent._manager = manager
        self.by_id[agent.agent_id] = agent
        self.active_by_name[agent.name] = agent
        if auto_save:
            manager._auto_save(agents={agent.agent_id}, libraries={lib_id})
            manager._memory.record_event(
                "agent_registered",
                agent=agent,
                payload={"lifecycle_state": "active"},
                inherit_context=False,
            )
        return agent

    def get_private_library_id(self, agent_id: str) -> str:
        agent = self.by_id.get(agent_id)
        if agent is None or agent.private_doc_library_id is None:
            raise KeyError(f"Unknown agent ID {agent_id!r}.")
        return agent.private_doc_library_id

    def require_private_context(self) -> Tuple[Agent, DocumentLibrary]:
        manager = self.manager
        agent = manager._active_tool_agent.get()
        if agent is None:
            raise PermissionError("Private DocLib access requires an active agent invocation.")
        registered = self.by_id.get(agent.agent_id)
        if (
            registered is not agent
            or agent.lifecycle_state != "active"
            or self.active_by_name.get(agent.name) is not agent
        ):
            raise PermissionError("The active agent identity is not active.")
        lib_id = agent.private_doc_library_id
        library = manager.libraries.get(lib_id or "")
        if (
            library is None
            or library.library_kind != "agent_private"
            or library.owner_agent_id != agent.agent_id
        ):
            raise PermissionError("Private DocLib ownership is unavailable.")
        return agent, library

    async def retire(
        self,
        agent_id: str,
        policy: Optional[str] = None,
        confirm_delete: bool = False,
    ) -> None:
        agent = self.by_id.get(agent_id)
        if agent is None:
            raise KeyError(f"Unknown agent ID {agent_id!r}.")
        async with agent.lifecycle_lock:
            await self.retire_locked(
                agent_id,
                policy=policy,
                confirm_delete=confirm_delete,
            )

    async def retire_locked(
        self,
        agent_id: str,
        policy: Optional[str] = None,
        confirm_delete: bool = False,
    ) -> None:
        manager = self.manager
        selected = policy or manager.config.agent_private_data_policy
        if selected not in {"retain", "archive", "delete"}:
            raise ValueError("policy must be retain, archive, or delete.")
        agent = self.by_id.get(agent_id)
        if agent is None:
            raise KeyError(f"Unknown agent ID {agent_id!r}.")
        if agent.lifecycle_state != "active":
            raise ValueError("Agent is already inactive.")
        if agent is manager.root_ai:
            raise ValueError("The root agent cannot be retired.")
        if selected == "delete" and not confirm_delete:
            raise ValueError("Permanent deletion requires confirm_delete=True.")
        if selected == "delete":
            await manager.flush_state()

        memberships = [team.team_id for team in manager.teams.values() if agent in team.members]
        if memberships:
            raise ValueError("Agent still belongs to teams: " + ", ".join(sorted(memberships)))
        creator_teams = [team.team_id for team in manager.teams.values() if team.creator is agent]
        if creator_teams:
            raise ValueError("Agent still creates teams: " + ", ".join(sorted(creator_teams)))
        if agent.lock.locked():
            raise ValueError("Agent has an active model invocation.")

        if selected == "delete":
            governance_refs = [
                f"{team.team_id}:{proposal_id}"
                for team in manager.teams.values()
                for proposal_id, proposal in team.proposals.items()
                if proposal.get("initiator_agent_id") == agent_id
                or agent_id in proposal.get("votes", {})
            ]
            governance_refs.extend(
                f"communication-request:{request.request_id}"
                for request in manager.broker.communication_requests.values()
                if request.initiated_by_agent_id == agent_id
            )
            governance_refs.extend(
                f"communication-ballot:{request_id}"
                for request_id, ballots in manager.broker.ballots.items()
                if any(ballot.voter_agent_id == agent_id for ballot in ballots)
            )
            governance_refs.extend(
                f"peer-message:{message.message_id}"
                for message in manager.broker.peer_messages.values()
                if message.initiated_by_agent_id == agent_id
            )
            if governance_refs:
                raise ValueError(
                    "Agent still has governance records: " + ", ".join(sorted(governance_refs))
                )

        lib_id = self.get_private_library_id(agent_id)
        library = manager.libraries[lib_id]
        if selected in {"retain", "archive"}:
            alias = manager.resolve_model_alias(agent.llm_client)
            old_alias = agent._model_alias
            agent._model_alias = alias
            state = "retained" if selected == "retain" else "archived"
            old_client = agent.llm_client
            agent.lifecycle_state = state
            with library._lock:
                library.lifecycle_state = state
            self.active_by_name.pop(agent.name, None)
            agent.llm_client = None
            lifecycle_event = None
            try:
                lifecycle_event = manager._memory.record_event(
                    "agent_lifecycle_changed",
                    agent=agent,
                    payload={"lifecycle_state": state},
                    persist=False,
                    inherit_context=False,
                )
                manager._auto_save(
                    agents={agent_id},
                    libraries={lib_id},
                    memory_events={lifecycle_event.event_id},
                )
                await manager.flush_state()
            except Exception:
                if lifecycle_event is not None:
                    manager._memory.discard_unpersisted_event(
                        lifecycle_event.event_id
                    )
                agent.lifecycle_state = "active"
                with library._lock:
                    library.lifecycle_state = "active"
                agent.llm_client = old_client
                agent._model_alias = old_alias
                self.active_by_name[agent.name] = agent
                raise
            manager._emit_callback(
                "on_system_event",
                "agent_lifecycle_changed",
                {
                    "agent_id": agent_id,
                    "state": state,
                    "library_id": lib_id,
                },
            )
            return

        parent_dir = os.path.dirname(library.root_dir)
        trash_path = os.path.join(parent_dir, f".{lib_id}-delete-{uuid.uuid4().hex}")
        old_files = manager._library_files.get(lib_id, {})
        old_links = manager.library_links.get(lib_id)
        old_permissions = manager.library_permissions.get(lib_id)
        old_memory = manager._memory.snapshot()
        moved = False
        committed = False
        try:
            agent.lifecycle_state = "deleting"
            with library._lock:
                library.lifecycle_state = "archived"
                if os.path.exists(library.root_dir):
                    os.replace(library.root_dir, trash_path)
                    moved = True
            self.active_by_name.pop(agent.name, None)
            self.by_id.pop(agent_id, None)
            manager.libraries.pop(lib_id, None)
            manager._library_files.pop(lib_id, None)
            manager.library_links.pop(lib_id, None)
            manager.library_permissions.pop(lib_id, None)
            manager._memory.remove_agent_derived_state(agent_id)
            lifecycle_event = manager._memory.record_event(
                "agent_lifecycle_changed",
                agent=agent,
                payload={"lifecycle_state": "deleted"},
                persist=False,
                inherit_context=False,
            )
            manager._auto_save(
                deleted_agents={agent_id},
                deleted_libraries={lib_id},
                memory_events={lifecycle_event.event_id},
            )
            await manager.flush_state()
            committed = True
        except Exception:
            self.by_id[agent_id] = agent
            self.active_by_name[agent.name] = agent
            manager.libraries[lib_id] = library
            manager._library_files[lib_id] = old_files
            if old_links is not None:
                manager.library_links[lib_id] = old_links
            if old_permissions is not None:
                manager.library_permissions[lib_id] = old_permissions
            if moved and os.path.exists(trash_path):
                os.replace(trash_path, library.root_dir)
            with library._lock:
                library.lifecycle_state = "active"
            agent.lifecycle_state = "active"
            manager._memory.restore(
                old_memory["memory_events"],
                old_memory["memory_segments"],
                old_memory["memory_cards"],
                old_memory["memory_references"],
            )
            raise
        finally:
            if committed and os.path.exists(trash_path):
                shutil.rmtree(trash_path, ignore_errors=True)
        manager._emit_callback(
            "on_system_event",
            "agent_lifecycle_changed",
            {
                "agent_id": agent_id,
                "state": "deleted",
                "library_id": lib_id,
            },
        )
        agent.lifecycle_state = "deleted"
        agent.llm_client = None
        agent._private_doc_library_id = None
        agent.messages.clear()
        agent.message_history.clear()
        agent._history_seen_ids.clear()
        agent._manager = None

    async def reactivate(self, agent_id: str, model_alias: str) -> Agent:
        agent = self.by_id.get(agent_id)
        if agent is None:
            raise KeyError(f"Unknown agent ID {agent_id!r}.")
        async with agent.lifecycle_lock:
            return await self.reactivate_locked(agent_id, model_alias)

    async def reactivate_locked(self, agent_id: str, model_alias: str) -> Agent:
        manager = self.manager
        agent = self.by_id.get(agent_id)
        if agent is None:
            raise KeyError(f"Unknown agent ID {agent_id!r}.")
        if agent.lifecycle_state == "active":
            raise ValueError("Agent is already active.")
        if self.active_by_name.get(agent.name) not in {None, agent}:
            raise ValueError(f"Agent name {agent.name!r} is already active.")
        if model_alias == "default":
            if "default" in manager.llm_clients:
                client = manager.llm_clients["default"]
            elif manager.generator_handler is not None:
                client = ManagerDefaultClientAdapter(manager)
            else:
                raise ValueError("The default model alias has no runtime binding.")
        elif model_alias in manager.llm_clients:
            client = manager.llm_clients[model_alias]
        elif model_alias in manager.model_configs and manager.generator_handler:
            client = HandlerClientAdapter(model_alias, manager.generator_handler)
            client._supports_native = (
                manager.model_configs.get(model_alias, {}).get("supports_native_tool_calling")
                is True
            )
        else:
            raise ValueError(f"Model alias {model_alias!r} has no runtime binding.")
        lib_id = self.get_private_library_id(agent_id)
        library = manager.libraries[lib_id]
        old_state = agent.lifecycle_state
        old_library_state = library.lifecycle_state
        old_alias = agent._model_alias
        agent.llm_client = client
        agent._model_alias = model_alias
        agent.lifecycle_state = "active"
        with library._lock:
            library.lifecycle_state = "active"
        self.active_by_name[agent.name] = agent
        lifecycle_event = None
        try:
            lifecycle_event = manager._memory.record_event(
                "agent_lifecycle_changed",
                agent=agent,
                payload={"lifecycle_state": "active"},
                persist=False,
                inherit_context=False,
            )
            manager._auto_save(
                agents={agent_id},
                libraries={lib_id},
                memory_events={lifecycle_event.event_id},
            )
            await manager.flush_state()
        except Exception:
            if lifecycle_event is not None:
                manager._memory.discard_unpersisted_event(
                    lifecycle_event.event_id
                )
            self.active_by_name.pop(agent.name, None)
            agent.llm_client = None
            agent._model_alias = old_alias
            agent.lifecycle_state = old_state
            with library._lock:
                library.lifecycle_state = old_library_state
            raise
        manager._emit_callback(
            "on_system_event",
            "agent_lifecycle_changed",
            {
                "agent_id": agent_id,
                "state": "active",
                "library_id": lib_id,
            },
        )
        manager._memory.resume_pending()
        return agent
