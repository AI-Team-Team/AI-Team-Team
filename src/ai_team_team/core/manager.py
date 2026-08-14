import asyncio
import contextvars
import inspect
import os
import logging
import json
import time
import threading
import shutil
import tempfile
import uuid
import hashlib
from contextlib import asynccontextmanager
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, List, Dict, Optional, Tuple, Any, Callable

from ai_team_team.doc_library import DocumentLibrary
from ai_team_team.tool import Tool

# Modular sub-module imports
from .agent import Agent
from .team import AgentTeam
from .broker import NegotiationBroker
from .config import ATTConfig
from .exceptions import (
    AgentTurnIncompleteError,
    AmbiguousTeamContextError,
    ATTException,
    TokenLimitExceededError,
    StatePersistenceError,
    StateRestoreError,
)
from .utils import generate_with_retry
from .adapters import ManagerDefaultClientAdapter, HandlerClientAdapter
from .token_budget import TokenBudgetLedger

if TYPE_CHECKING:
    from .response import DiscussionResult

from ai_team_team.database.persistence import (
    PersistenceCoordinator,
    STATE_SCHEMA_VERSION,
)

class ATTManager:
    """Master controller managing the overall ATT (AI Team Team) topology."""
    def __init__(
        self,
        root_ai: Agent,
        config: Optional[ATTConfig] = None,
        db_path: Optional[str] = None,
        *,
        _restore_mode: bool = False,
    ) -> None:
        self.root_ai = root_ai
        self.config = config or ATTConfig()
        self.db_path = db_path
        self.agents: Dict[str, Agent] = {}
        self._agents_by_id: Dict[str, Agent] = {}
        self.teams: Dict[str, AgentTeam] = {}
        self.broker = NegotiationBroker(self)
        self.llm_clients: Dict[str, Any] = {}
        self.model_token_usage: Dict[str, int] = {}
        self.token_budget = TokenBudgetLedger(self)
        
        self.model_configs: Dict[str, Dict[str, Any]] = {}
        self.generator_handler: Optional[Callable[..., str]] = None
        
        from ai_team_team.supervision import SupervisoryTeam
        self.supervisor = SupervisoryTeam(root_ai, ManagerDefaultClientAdapter(self), manager=self)
        self.logger = logging.getLogger("ATTManager")
        self.tools_context: Dict[str, Any] = {"att_manager": self}
        self.libraries: Dict[str, DocumentLibrary] = {}
        self.library_permissions: Dict[str, Dict[str, Dict[str, str]]] = {} # lib_id -> path -> team_id -> permission
        self.library_links: Dict[
            str, Dict[str, Dict[str, str]]
        ] = {}
        self._library_files: Dict[str, Dict[str, str]] = {}
 
        # Public Tool registries
        self.global_tools: Dict[str, Tool] = {}
        
        # O(1) tracking structures
        self._team_parent_map: Dict[str, str] = {}
        self._topology_lock = threading.RLock()
        self._snapshot_lock = threading.RLock()
        self._runtime_gate = asyncio.Lock()
        self._starting_invocations = 0
        self._active_invocations = 0
        self._state_version = 0
        self._persistence = PersistenceCoordinator(db_path)
        self._persistence_batch: contextvars.ContextVar[Optional[Dict[str, Any]]] = (
            contextvars.ContextVar(
                f"att_persistence_batch_{id(self)}", default=None
            )
        )
        self._active_tool_agent: contextvars.ContextVar[Optional[Agent]] = (
            contextvars.ContextVar(
                f"att_active_tool_agent_{id(self)}", default=None
            )
        )
        self._active_team: contextvars.ContextVar[Optional[AgentTeam]] = (
            contextvars.ContextVar(f"att_active_team_{id(self)}", default=None)
        )
        self._active_discussion_id: contextvars.ContextVar[Optional[str]] = (
            contextvars.ContextVar(
                f"att_active_discussion_{id(self)}", default=None
            )
        )
        self._active_tool_invocation_id: contextvars.ContextVar[
            Optional[str]
        ] = contextvars.ContextVar(
            f"att_active_tool_invocation_{id(self)}", default=None
        )
        self._unknown_audit_wakeups: set[str] = set()
        self._emergency_tasks: set[asyncio.Task[Any]] = set()
        self._llm_tasks: set[asyncio.Task[Any]] = set()
        self._closing = False
        self._closed = False
        self._callback_queue: Optional[asyncio.Queue[Any]] = None
        self._callback_worker: Optional[asyncio.Task[Any]] = None
        self._deferred_callbacks: List[Tuple[Callable[..., Any], tuple]] = []
        self._callback_lock = threading.RLock()
        
        # Async tasks deferred bridging
        import queue
        self.deferred_emergency_tasks = queue.Queue()
        self.tool_auditors: Dict[str, Callable[..., Tuple[bool, str]]] = {}
        
        # Event callbacks
        self.on_status_change: Optional[Callable[[str, str], None]] = None
        self.on_activity_added: Optional[Callable[[str, str, str], None]] = None
        self.on_log_append: Optional[Callable[[str, str, str, Optional[int]], None]] = None
        self.on_team_migration: Optional[Callable[[str, Optional[str], str], None]] = None
        self.on_emergency_escalation: Optional[Callable[[str, str, str], None]] = None
        self.on_system_event: Optional[Callable[[str, Dict[str, Any]], None]] = None

        # Base preset configurations
        self.presets: Dict[str, dict] = {
            "generic": {
                "description": "Default Generic AT",
                "system_instructions": "Cooperate to solve the task.",
                "roles": [
                    ("Specialist_A", "Contributes key analytical viewpoints."),
                    ("Specialist_B", "Contributes creative and structural solutions."),
                    ("Arbitrator", "Synthesizes the final decision.")
                ]
            }
        }
        if _restore_mode:
            self.agents[root_ai.name] = root_ai
            self._agents_by_id[root_ai.agent_id] = root_ai
        else:
            self.register_agent(root_ai, auto_save=False)

    async def __aenter__(self) -> "ATTManager":
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.close()

    @staticmethod
    def _new_dirty_state(full: bool = False) -> Dict[str, Any]:
        return {
            "full": full,
            "configs": full,
            "agents": set(),
            "teams": set(),
            "inboxes": set(),
            "proposals": set(),
            "communication_requests": set(),
            "communication_approvals": set(),
            "communication_agreements": set(),
            "peer_messages": set(),
            "libraries": set(),
            "permissions": set(),
            "links": set(),
            "file_changes": {},
            "deleted_agents": set(),
            "deleted_libraries": set(),
        }

    @staticmethod
    def _merge_dirty_state(target: Dict[str, Any], source: Dict[str, Any]) -> None:
        target["full"] = target["full"] or source["full"]
        target["configs"] = target["configs"] or source["configs"]
        for key in (
            "agents",
            "teams",
            "inboxes",
            "proposals",
            "libraries",
            "permissions",
            "links",
            "communication_requests",
            "communication_approvals",
            "communication_agreements",
            "peer_messages",
        ):
            target[key].update(source[key])
        for lib_id, changes in source["file_changes"].items():
            target["file_changes"].setdefault(lib_id, {}).update(changes)
        target["deleted_agents"].update(source["deleted_agents"])
        target["deleted_libraries"].update(source["deleted_libraries"])

    @asynccontextmanager
    async def suppress_auto_save(self):
        """Batches auto-save deltas across nested and concurrent child tasks."""
        parent_batch = self._persistence_batch.get()
        is_root = parent_batch is None
        token = None
        if is_root:
            parent_batch = self._new_dirty_state()
            token = self._persistence_batch.set(parent_batch)
        try:
            yield
        finally:
            if is_root:
                self._persistence_batch.reset(token)
                if self.db_path and self._dirty_state_has_changes(parent_batch):
                    self._submit_dirty_state(parent_batch)

    @staticmethod
    def _dirty_state_has_changes(dirty: Dict[str, Any]) -> bool:
        return bool(
            dirty["full"]
            or dirty["configs"]
            or dirty["communication_requests"]
            or dirty["communication_approvals"]
            or dirty["communication_agreements"]
            or dirty["peer_messages"]
            or dirty["agents"]
            or dirty["teams"]
            or dirty["inboxes"]
            or dirty["proposals"]
            or dirty["libraries"]
            or dirty["permissions"]
            or dirty["links"]
            or dirty["file_changes"]
            or dirty["deleted_agents"]
            or dirty["deleted_libraries"]
        )

    def _auto_save(
        self,
        *,
        configs: bool = False,
        agents: Optional[set[str]] = None,
        teams: Optional[set[str]] = None,
        inboxes: Optional[set[str]] = None,
        proposals: Optional[set[str]] = None,
        communication_requests: Optional[set[str]] = None,
        communication_approvals: Optional[set[str]] = None,
        communication_agreements: Optional[set[str]] = None,
        peer_messages: Optional[set[str]] = None,
        libraries: Optional[set[str]] = None,
        permissions: Optional[set[str]] = None,
        links: Optional[set[str]] = None,
        file_changes: Optional[
            Dict[str, Dict[str, Optional[str]]]
        ] = None,
        full: bool = False,
        deleted_agents: Optional[set[str]] = None,
        deleted_libraries: Optional[set[str]] = None,
    ) -> None:
        """Records an immutable incremental state delta for the single writer."""
        if not self.db_path:
            return
        dirty = self._new_dirty_state(full=full)
        dirty["configs"] = configs or full
        dirty["agents"].update(agents or set())
        dirty["teams"].update(teams or set())
        dirty["inboxes"].update(inboxes or set())
        dirty["proposals"].update(proposals or set())
        dirty["communication_requests"].update(
            communication_requests or set()
        )
        dirty["communication_approvals"].update(
            communication_approvals or set()
        )
        dirty["communication_agreements"].update(
            communication_agreements or set()
        )
        dirty["peer_messages"].update(peer_messages or set())
        dirty["libraries"].update(libraries or set())
        dirty["permissions"].update(permissions or set())
        dirty["links"].update(links or set())
        dirty["deleted_agents"].update(deleted_agents or set())
        dirty["deleted_libraries"].update(deleted_libraries or set())
        for lib_id, changes in (file_changes or {}).items():
            dirty["file_changes"].setdefault(lib_id, {}).update(changes)

        if not self._dirty_state_has_changes(dirty):
            return
        with self._snapshot_lock:
            self._state_version += 1
        batch = self._persistence_batch.get()
        if batch is not None:
            self._merge_dirty_state(batch, dirty)
            return
        self._submit_dirty_state(dirty)

    async def _commit_dirty_state(self, dirty: Dict[str, Any]) -> None:
        """Commits one authoritative domain delta and propagates write errors."""
        if not self.db_path or not self._dirty_state_has_changes(dirty):
            return
        with self._snapshot_lock:
            self._state_version += 1
            snapshot = self._capture_state_snapshot(dirty)
            future = self._persistence.submit(self.db_path, snapshot)
        wrapped = asyncio.wrap_future(future)
        try:
            await asyncio.shield(wrapped)
        except asyncio.CancelledError:
            # Once an authoritative domain commit is accepted, keep its
            # transaction lock until the exact delta finishes. Cancellation
            # is delivered to the caller only after durability is known.
            await asyncio.shield(wrapped)
            raise
        except ATTException:
            raise
        except Exception as exc:
            raise StatePersistenceError(
                "The authoritative state delta could not be committed."
            ) from exc

    def _submit_dirty_state(self, dirty: Dict[str, Any]) -> None:
        with self._snapshot_lock:
            try:
                snapshot = self._capture_state_snapshot(dirty)
            except Exception as exc:
                snapshot = {"_capture_error": exc}
            self._persistence.submit(self.db_path, snapshot)

    async def save_state(
        self, path: Optional[str] = None, full: bool = True
    ) -> None:
        """Persists state asynchronously and waits for the write to commit."""
        if self._closing:
            raise RuntimeError("ATTManager is closing and cannot accept saves.")
        target_path = path or self.db_path
        if not target_path:
            return
        await self.flush_state()
        dirty = self._new_dirty_state(full=full)
        if not full:
            dirty["configs"] = True
        with self._snapshot_lock:
            snapshot = self._capture_state_snapshot(dirty)
            future = self._persistence.submit(target_path, snapshot)
        await asyncio.shield(asyncio.wrap_future(future))

    async def flush_state(self) -> None:
        """Waits until every queued state delta has committed."""
        await self._persistence.flush()

    async def close(self) -> None:
        """Cancels external waits, commits accepted state, and releases resources."""
        if self._closed:
            return
        self._closing = True
        current = asyncio.current_task()
        active_tasks = {
            task
            for task in self._llm_tasks | self._emergency_tasks
            if not task.done() and task is not current
        }
        for task in active_tasks:
            task.cancel()
        if active_tasks:
            # Deliver cancellation without waiting on providers that suppress it.
            await asyncio.sleep(0)
            for task in active_tasks:
                if task.done():
                    try:
                        task.result()
                    except BaseException:
                        pass

        callback_worker = self._callback_worker
        if callback_worker is not None and not callback_worker.done():
            callback_worker.cancel()
            await asyncio.sleep(0)
        reset_error: Optional[BaseException] = None
        try:
            await self.broker.reset_processing_for_shutdown()
        except BaseException as exc:
            reset_error = exc
        try:
            await self._persistence.close()
        finally:
            self._closed = True
        if reset_error is not None:
            raise reset_error

    async def load_state(self, path: str) -> None:
        """Restores a versioned state snapshot without blocking the event loop."""
        async with self._runtime_gate:
            if self._closing:
                raise RuntimeError("ATTManager is closing and cannot restore state.")
            if not os.path.exists(path):
                raise FileNotFoundError(f"State database file '{path}' not found.")
            state = await self._persistence.read(path)
            await self._apply_state_snapshot(state)
            self.db_path = path
            self.broker.resume_pending_requests()

    @asynccontextmanager
    async def agent_invocation(
        self, agent: Agent, *, allow_runtime: bool = False
    ):
        """Starts a model invocation atomically against restore and retirement."""
        async with self._runtime_gate:
            if self._closing:
                raise RuntimeError(
                    "ATTManager is closing and rejects new agent invocations."
                )
            registered = self._agents_by_id.get(agent.agent_id) is agent
            if (not registered and not allow_runtime) or (
                agent.lifecycle_state != "active"
            ):
                raise RuntimeError(
                    "Agent is not an active identity in this manager."
                )
            self._starting_invocations += 1
        invocation = agent.invocation_guard()
        try:
            await invocation.__aenter__()
        except BaseException:
            async with self._runtime_gate:
                self._starting_invocations -= 1
            raise
        async with self._runtime_gate:
            self._starting_invocations -= 1
            self._active_invocations += 1
        try:
            yield
        finally:
            try:
                await invocation.__aexit__(None, None, None)
            finally:
                async with self._runtime_gate:
                    self._active_invocations -= 1

    def _emit_callback(self, name: str, *args: Any) -> None:
        """Queues an observational callback without blocking core execution."""
        callback = getattr(self, name, None)
        if callback is None or self._closing:
            return
        item = (callback, tuple(args))
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            with self._callback_lock:
                self._deferred_callbacks.append(item)
            return
        self._ensure_callback_dispatcher(loop)
        self._callback_queue.put_nowait(item)

    def _ensure_callback_dispatcher(
        self, loop: Optional[asyncio.AbstractEventLoop] = None
    ) -> None:
        if self._callback_worker is not None and not self._callback_worker.done():
            return
        loop = loop or asyncio.get_running_loop()
        self._callback_queue = asyncio.Queue()
        with self._callback_lock:
            deferred = self._deferred_callbacks
            self._deferred_callbacks = []
        for item in deferred:
            self._callback_queue.put_nowait(item)
        self._callback_worker = loop.create_task(
            self._dispatch_callbacks(), name=f"att-callbacks-{id(self)}"
        )

    async def _dispatch_callbacks(self) -> None:
        while True:
            callback, args = await self._callback_queue.get()
            try:
                if inspect.iscoroutinefunction(callback):
                    await callback(*args)
                else:
                    result = await asyncio.to_thread(callback, *args)
                    if inspect.isawaitable(result):
                        await result
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger.exception("Observational ATT callback failed.")
            finally:
                self._callback_queue.task_done()

    async def flush_callbacks(self) -> None:
        """Waits for queued callbacks; primarily useful for tests and shutdown hosts."""
        if self._closing:
            return
        self._ensure_callback_dispatcher()
        await self._callback_queue.join()

    def _capture_state_snapshot(self, dirty: Dict[str, Any]) -> Dict[str, Any]:
        full = dirty["full"]
        now = time.time()
        configs = None
        if full or dirty["configs"]:
            configs = {
                "schema_version": STATE_SCHEMA_VERSION,
                "att_config": self.config.to_dict(),
                "root_ai_id": self.root_ai.agent_id,
                "model_configs": {
                    alias: dict(config)
                    for alias, config in self.model_configs.items()
                },
                "presets": {
                    name: {
                        **preset,
                        "roles": tuple(
                            tuple(role) for role in preset.get("roles", ())
                        ),
                    }
                    for name, preset in self.presets.items()
                },
                "model_token_usage": dict(self.model_token_usage),
            }

        agent_lookup = dict(self._agents_by_id)
        relevant_teams = (
            self.teams.values()
            if full
            else (
                self.teams[team_id]
                for team_id in dirty["teams"]
                if team_id in self.teams
            )
        )
        for relevant_team in relevant_teams:
            for member in relevant_team.members:
                agent_lookup.setdefault(member.agent_id, member)
        agent_ids = set(agent_lookup) if full else set()
        if not full:
            for identifier in dirty["agents"]:
                if identifier in agent_lookup:
                    agent_ids.add(identifier)
                elif identifier in self.agents:
                    agent_ids.add(self.agents[identifier].agent_id)
        if not full:
            for team_id in dirty["teams"]:
                team = self.teams.get(team_id)
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
                    model_alias = self.resolve_model_alias(agent.llm_client)
                else:
                    model_alias = agent._model_alias
                    if model_alias is None and agent.llm_client is not None:
                        model_alias = self.resolve_model_alias(agent.llm_client)
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
                    "role_description": getattr(
                        agent, "role_description", ""
                    ),
                    "system_instructions": getattr(
                        agent, "system_instructions", ""
                    ),
                    "model_alias": model_alias,
                    "lifecycle_state": agent.lifecycle_state,
                    "last_context": (
                        dict(agent.last_context) if agent.last_context else None
                    ),
                    "messages": tuple(
                        dict(message)
                        for message in self._agent_history(agent)
                    ),
                    "message_timestamp": now,
                }
            )
        if unresolved_agents:
            raise ValueError(
                "Cannot persist agents whose LLM clients have no stable, "
                "unique registered alias: " + ", ".join(unresolved_agents)
            )

        team_ids = set(self.teams) if full else set(dirty["teams"])
        teams = []
        for team_id in sorted(team_ids):
            team = self.teams.get(team_id)
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
                    "parent_team_id": (
                        team.parent_team.team_id if team.parent_team else None
                    ),
                    "migration_count": team.migration_count,
                    "creator_type": creator_type,
                    "creator_id": creator_id,
                    "status_map": team.status_snapshot(),
                    "system_instructions": getattr(
                        team, "system_instructions", ""
                    ),
                    "members": [member.agent_id for member in team.members],
                    "message_timestamp": now,
                }
            )

        inbox_ids = set(self.teams) if full else set(dirty["inboxes"])
        inboxes = {}
        for team_id in sorted(inbox_ids):
            team = self.teams.get(team_id)
            if team is None:
                continue
            with team.inbox_lock:
                messages = tuple(dict(message) for message in team.message_inbox)
            inboxes[team_id] = {
                "messages": messages,
                "message_timestamp": now,
            }
        proposal_ids = (
            set(self.teams) if full else set(dirty["proposals"])
        )
        proposals = {
            team_id: [
                {
                    "proposal_id": proposal_id,
                    **{
                        key: dict(value) if isinstance(value, dict) else value
                        for key, value in proposal.items()
                    },
                }
                for proposal_id, proposal in self.teams[
                    team_id
                ].proposals.items()
            ]
            for team_id in sorted(proposal_ids)
            if team_id in self.teams
        }

        library_ids = (
            set(self.libraries) if full else set(dirty["libraries"])
        )
        libraries = []
        for lib_id in sorted(library_ids):
            library = self.libraries.get(lib_id)
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

        permission_ids = (
            set(self.libraries) if full else set(dirty["permissions"])
        )
        permissions = {
            lib_id: {
                path: dict(team_map)
                for path, team_map in self.library_permissions.get(
                    lib_id, {}
                ).items()
            }
            for lib_id in permission_ids
        }
        link_ids = set(self.libraries) if full else set(dirty["links"])
        links = {
            lib_id: {
                path: dict(target)
                for path, target in self.library_links.get(lib_id, {}).items()
            }
            for lib_id in link_ids
        }

        file_changes = {
            lib_id: dict(changes)
            for lib_id, changes in dirty["file_changes"].items()
        }
        if full:
            for lib_id in self.libraries:
                file_changes[lib_id] = dict(
                    self._library_files.get(lib_id, {})
                )

        request_ids = (
            set(self.broker.communication_requests)
            if full
            else set(dirty["communication_requests"])
        )
        approval_request_ids = (
            set(self.broker.communication_requests)
            if full
            else set(dirty["communication_approvals"])
        )
        agreement_ids = (
            set(self.broker.agreements)
            if full
            else set(dirty["communication_agreements"])
        )
        peer_message_ids = (
            set(self.broker.peer_messages)
            if full
            else set(dirty["peer_messages"])
        )
        communication_requests = [
            self.broker.communication_requests[request_id].model_dump(
                mode="json"
            )
            for request_id in sorted(request_ids)
            if request_id in self.broker.communication_requests
        ]
        communication_approvals = [
            approval.model_dump(mode="json")
            for request_id in sorted(approval_request_ids)
            for approval in self.broker.approvals_for_request(request_id)
        ]
        communication_ballots = [
            ballot.model_dump(mode="json")
            for request_id in sorted(approval_request_ids)
            for ballot in self.broker.ballots.get(request_id, [])
        ]
        communication_agreements = [
            self.broker.agreements[agreement_id].model_dump(mode="json")
            for agreement_id in sorted(agreement_ids)
            if agreement_id in self.broker.agreements
        ]
        peer_messages = [
            self.broker.peer_messages[message_id].model_dump(mode="json")
            for message_id in sorted(peer_message_ids)
            if message_id in self.broker.peer_messages
        ]

        return {
            "state_version": self._state_version,
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

    async def _apply_state_snapshot_unvalidated(
        self, state: Dict[str, Any]
    ) -> None:
        configs = state["configs"]
        config_data = json.loads(configs["att_config"])
        self.config = ATTConfig(**config_data)
        self.model_configs = json.loads(configs.get("model_configs", "{}"))
        self.presets = json.loads(configs.get("presets", "{}"))
        self.model_token_usage = json.loads(
            configs.get("model_token_usage", "{}")
        )

        required_aliases = {
            row["model_alias"]
            for row in state["agents"]
            if row.get("lifecycle_state", "active") == "active"
            and row.get("model_alias") != "default"
        }
        missing_aliases = sorted(
            alias
            for alias in required_aliases
            if alias not in self.llm_clients
            and not (
                self.generator_handler and alias in self.model_configs
            )
        )
        if missing_aliases:
            raise StateRestoreError(
                "Missing runtime bindings for model aliases: "
                + ", ".join(missing_aliases)
            )

        self.agents.clear()
        self._agents_by_id.clear()
        for row in state["agents"]:
            alias = row.get("model_alias")
            lifecycle_state = row.get("lifecycle_state", "active")
            if lifecycle_state != "active":
                client = None
            elif alias in self.llm_clients:
                client = self.llm_clients[alias]
            elif (
                alias != "default"
                and alias in self.model_configs
                and self.generator_handler
            ):
                client = HandlerClientAdapter(alias, self.generator_handler)
                client._supports_native = self.model_configs.get(
                    alias, {}
                ).get("supports_native_tool_calling", False)
            elif alias == "default" and self.generator_handler:
                client = ManagerDefaultClientAdapter(self)
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
            agent.last_context = (
                json.loads(row["last_context"])
                if row["last_context"]
                else None
            )
            agent.messages = []
            agent.message_history = []
            agent._history_seen_ids = set()
            for message in row["messages"]:
                restored = {
                    key: value
                    for key, value in message.items()
                    if value is not None
                }
                agent.messages.append(restored)
                agent.message_history.append(restored)
                agent._history_seen_ids.add(id(restored))
            self._agents_by_id[agent.agent_id] = agent
            if lifecycle_state == "active":
                self.agents[agent.name] = agent

        root_id = configs["root_ai_id"]
        if root_id not in self._agents_by_id:
            raise StateRestoreError(
                f"Persisted root agent {root_id!r} was not found."
            )
        self.root_ai = self._agents_by_id[root_id]
        self.supervisor.root_ai = self.root_ai

        self.libraries.clear()
        self._library_files.clear()
        for row in state["libraries"]:
            library = self._new_document_library(
                lib_id=row["lib_id"],
                name=row["name"],
                owner_team_id=row["owner_team_id"],
                owner_agent_id=row.get("owner_agent_id"),
                library_kind=row.get("library_kind", "team"),
                lifecycle_state=row.get("lifecycle_state", "active"),
                description=row["description"] or "",
                is_public_visible=row["is_public_visible"],
            )
            await asyncio.to_thread(
                library._restore_all_files, row["files"]
            )
            self.libraries[library.lib_id] = library
            self._library_files[library.lib_id] = dict(row["files"])
        self.library_permissions = state["permissions"]
        self.library_links = state.get("links", {})

        self.teams.clear()
        self._team_parent_map.clear()
        team_map: Dict[str, AgentTeam] = {}
        for row in state["teams"]:
            creator = (
                self._agents_by_id.get(row["creator_id"])
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
            team.manager = self
            team.message_inbox = row["inbox"]
            for message in team.message_inbox:
                if message.get("type") == "audit_unknown_escalation":
                    message.setdefault(
                        "fingerprint",
                        self._unknown_alert_fingerprint(message),
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
                    key: value
                    for key, value in proposal.items()
                    if key != "proposal_id"
                }
                for proposal in row["proposals"]
            }
            team.members = [
                self._agents_by_id[agent_id]
                for agent_id in row["members"]
            ]
            team_map[team.team_id] = team

        for row in state["teams"]:
            team = team_map[row["team_id"]]
            parent_id = row["parent_team_id"]
            if parent_id:
                parent = team_map[parent_id]
                team._parent_team = parent
                parent.child_teams.append(team)
                self._team_parent_map[team.team_id] = parent_id
            if row["creator_type"] == "team":
                team.creator = team_map.get(row["creator_id"])
        self.teams = team_map

        from ai_team_team.tool import get_default_tools

        for team in self.teams.values():
            team.doc_library = self.libraries.get(f"DL-{team.team_id}")
            team.tools = get_default_tools(self.tools_context, team)
            team.tools.update(self.global_tools)

        self.broker.restore(
            state.get("communication_requests", []),
            state.get("communication_approvals", []),
            state.get("communication_ballots", []),
            state.get("communication_agreements", []),
            state.get("peer_messages", []),
        )

    async def _apply_state_snapshot(self, state: Dict[str, Any]) -> None:
        """Stages, validates, and atomically publishes a restored state."""
        if self._starting_invocations or self._active_invocations:
            raise StateRestoreError(
                "Cannot restore state while agent invocations are active or starting."
            )
        if any(team.is_running for team in self.teams.values()):
            raise StateRestoreError(
                "Cannot restore state while a team discussion is active."
            )
        if any(agent.lock.locked() for agent in self._agents_by_id.values()):
            raise StateRestoreError(
                "Cannot restore state while an agent invocation is active."
            )
        if self.token_budget.has_active_reservations():
            raise StateRestoreError(
                "Cannot restore state while model token reservations are active."
            )
        try:
            target_config = self._validate_state_snapshot(state)
        except StateRestoreError:
            raise
        except Exception as exc:
            raise StateRestoreError(
                f"Invalid persisted state: {exc}"
            ) from exc
        workspace = os.path.realpath(
            os.path.abspath(target_config.workspace_root)
        )
        managed_root = os.path.join(workspace, ".att_doc_libs")
        if os.path.lexists(managed_root) and os.path.islink(managed_root):
            raise StateRestoreError(
                "The managed DocLib root cannot be a symbolic link."
            )
        os.makedirs(managed_root, exist_ok=True)
        staging_workspace = tempfile.mkdtemp(
            prefix=".att-restore-", dir=managed_root
        )
        staged_state = json.loads(json.dumps(state))
        staged_config_data = json.loads(
            staged_state["configs"]["att_config"]
        )
        staged_config_data["workspace_root"] = staging_workspace
        staged_state["configs"]["att_config"] = json.dumps(
            staged_config_data
        )

        staged = ATTManager(
            Agent(
                "__restore_staging_root__",
                "Restore staging root",
                llm_client=self.root_ai.llm_client,
            ),
            ATTConfig(workspace_root=staging_workspace),
            _restore_mode=True,
        )
        staged.llm_clients = dict(self.llm_clients)
        staged.generator_handler = self.generator_handler
        staged.global_tools = dict(self.global_tools)
        published: List[Tuple[str, Optional[str]]] = []
        staged_closed = False
        try:
            await staged._apply_state_snapshot_unvalidated(staged_state)
            await staged._persistence.close()
            staged_closed = True
            staged.config = target_config
            staged.library_links = self._normalized_library_links(
                state.get("links", {})
            )

            from ai_team_team.tool import get_default_tools

            for library in staged.libraries.values():
                library._on_change = self._on_library_change
            for team in staged.teams.values():
                team.manager = self
                team.invalidate_depth_cache(recursive=False)
                team.tools = get_default_tools(self.tools_context, team)
                team.tools.update(self.global_tools)
            for team in staged.teams.values():
                _ = team.depth

            published = self._publish_staged_libraries(
                staged.libraries,
                managed_root,
            )
            old_state = {
                "config": self.config,
                "root_ai": self.root_ai,
                "agents": self.agents,
                "agents_by_id": self._agents_by_id,
                "teams": self.teams,
                "libraries": self.libraries,
                "library_permissions": self.library_permissions,
                "library_links": self.library_links,
                "library_files": self._library_files,
                "team_parent_map": self._team_parent_map,
                "model_configs": self.model_configs,
                "presets": self.presets,
                "model_token_usage": self.model_token_usage,
                "communication_requests": self.broker.communication_requests,
                "communication_approvals": self.broker.communication_approvals,
                "communication_ballots": self.broker.ballots,
                "communication_agreements": self.broker.agreements,
                "peer_messages": self.broker.peer_messages,
            }
            try:
                self.config = target_config
                self.root_ai = staged.root_ai
                self.agents = staged.agents
                self._agents_by_id = staged._agents_by_id
                self.teams = staged.teams
                self.libraries = staged.libraries
                self.library_permissions = staged.library_permissions
                self.library_links = staged.library_links
                self._library_files = staged._library_files
                self._team_parent_map = staged._team_parent_map
                self.model_configs = staged.model_configs
                self.presets = staged.presets
                self.model_token_usage = staged.model_token_usage
                self.broker.restore(
                    (
                        item.model_dump(mode="json")
                        for item in staged.broker.communication_requests.values()
                    ),
                    (
                        item.model_dump(mode="json")
                        for item in staged.broker.communication_approvals.values()
                    ),
                    (
                        item.model_dump(mode="json")
                        for values in staged.broker.ballots.values()
                        for item in values
                    ),
                    (
                        item.model_dump(mode="json")
                        for item in staged.broker.agreements.values()
                    ),
                    (
                        item.model_dump(mode="json")
                        for item in staged.broker.peer_messages.values()
                    ),
                )
                self.supervisor.root_ai = self.root_ai
                self.tools_context["att_manager"] = self
                self.token_budget.reset_reservations()
            except Exception:
                self.config = old_state["config"]
                self.root_ai = old_state["root_ai"]
                self.agents = old_state["agents"]
                self._agents_by_id = old_state["agents_by_id"]
                self.teams = old_state["teams"]
                self.libraries = old_state["libraries"]
                self.library_permissions = old_state["library_permissions"]
                self.library_links = old_state["library_links"]
                self._library_files = old_state["library_files"]
                self._team_parent_map = old_state["team_parent_map"]
                self.model_configs = old_state["model_configs"]
                self.presets = old_state["presets"]
                self.model_token_usage = old_state["model_token_usage"]
                self.broker.communication_requests = old_state[
                    "communication_requests"
                ]
                self.broker.communication_approvals = old_state[
                    "communication_approvals"
                ]
                self.broker.ballots = old_state[
                    "communication_ballots"
                ]
                self.broker.agreements = old_state[
                    "communication_agreements"
                ]
                self.broker.peer_messages = old_state["peer_messages"]
                self.supervisor.root_ai = self.root_ai
                self._rollback_published_libraries(published)
                published = []
                raise
            self._discard_library_backups(published)
            published = []
        except StateRestoreError:
            if published:
                self._rollback_published_libraries(published)
            raise
        except Exception as exc:
            if published:
                self._rollback_published_libraries(published)
            raise StateRestoreError(
                f"State restoration failed before commit: {exc}"
            ) from exc
        finally:
            if not staged_closed:
                await asyncio.shield(staged._persistence.close())
            shutil.rmtree(staging_workspace, ignore_errors=True)

    def _validate_state_snapshot(self, state: Dict[str, Any]) -> ATTConfig:
        """Validates every persisted reference before staging side effects."""
        try:
            configs = state["configs"]
            restored_config = json.loads(configs["att_config"])
            config = ATTConfig(**restored_config)
            persisted_model_configs = json.loads(
                configs.get("model_configs", "{}")
            )
            persisted_presets = json.loads(configs.get("presets", "{}"))
            persisted_usage = json.loads(
                configs.get("model_token_usage", "{}")
            )
            agent_rows = state["agents"]
            team_rows = state["teams"]
            library_rows = state["libraries"]
            permissions = state["permissions"]
            communication_requests = state["communication_requests"]
            communication_approvals = state["communication_approvals"]
            communication_ballots = state["communication_ballots"]
            communication_agreements = state["communication_agreements"]
            peer_messages = state["peer_messages"]
        except Exception as exc:
            raise StateRestoreError(
                f"Invalid persisted state structure: {exc}"
            ) from exc

        agent_ids = [row.get("agent_id") for row in agent_rows]
        agent_names = [row.get("name") for row in agent_rows]
        if None in agent_ids or len(agent_ids) != len(set(agent_ids)):
            raise StateRestoreError("Agent IDs are missing or duplicated.")
        for agent_id in agent_ids:
            try:
                if str(uuid.UUID(agent_id)) != agent_id:
                    raise ValueError
            except (ValueError, AttributeError, TypeError) as exc:
                raise StateRestoreError(
                    f"Agent ID {agent_id!r} is not a canonical UUID."
                ) from exc
        if None in agent_names or len(agent_names) != len(set(agent_names)):
            raise StateRestoreError("Agent names are missing or duplicated.")
        agent_id_set = set(agent_ids)
        active_agent_ids = {
            row["agent_id"]
            for row in agent_rows
            if row.get("lifecycle_state") == "active"
        }
        for row in agent_rows:
            if row.get("lifecycle_state") not in {
                "active",
                "retained",
                "archived",
            }:
                raise StateRestoreError(
                    f"Agent {row.get('agent_id')!r} has an invalid lifecycle state."
                )
        root_id = configs.get("root_ai_id")
        if root_id not in active_agent_ids:
            raise StateRestoreError(
                f"Persisted root agent {root_id!r} was not found or is inactive."
            )
        if not isinstance(persisted_model_configs, dict) or not isinstance(
            persisted_presets, dict
        ):
            raise StateRestoreError(
                "Persisted model configurations and presets must be objects."
            )
        if not isinstance(persisted_usage, dict) or any(
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < 0
            for value in persisted_usage.values()
        ):
            raise StateRestoreError(
                "Persisted model token usage must contain non-negative integers."
            )
        if any(
            row.get("model_alias") is None
            for row in agent_rows
            if row.get("lifecycle_state") == "active"
        ):
            raise StateRestoreError(
                "Every active persisted agent must reference an explicit model alias."
            )
        missing_aliases = sorted(
            {
                row.get("model_alias")
                for row in agent_rows
                if row.get("lifecycle_state") == "active"
                if row.get("model_alias") != "default"
                and (
                    row.get("model_alias") not in self.llm_clients
                    and not (
                        self.generator_handler
                        and row.get("model_alias")
                        in persisted_model_configs
                    )
                )
            }
        )
        if missing_aliases:
            raise StateRestoreError(
                "Missing runtime bindings for model aliases: "
                + ", ".join(missing_aliases)
            )
        has_default_binding = bool(
            "default" in self.llm_clients
            or self.generator_handler
        )
        if any(
            row.get("model_alias") == "default"
            for row in agent_rows
            if row.get("lifecycle_state") == "active"
        ) and not has_default_binding:
            raise StateRestoreError(
                "No runtime binding is available for the default model alias."
            )
        for row in agent_rows:
            if row.get("last_context"):
                try:
                    json.loads(row["last_context"])
                except Exception as exc:
                    raise StateRestoreError(
                        f"Agent {row['name']!r} has invalid last_context JSON."
                    ) from exc

        team_ids = [row.get("team_id") for row in team_rows]
        if None in team_ids or len(team_ids) != len(set(team_ids)):
            raise StateRestoreError("Team identifiers are missing or duplicated.")
        team_id_set = set(team_ids)
        for row in agent_rows:
            messages = row.get("messages", [])
            if not isinstance(messages, list):
                raise StateRestoreError(
                    f"Agent {row.get('agent_id')!r} has invalid message history."
                )
            for message in messages:
                if not isinstance(message, dict):
                    raise StateRestoreError(
                        f"Agent {row.get('agent_id')!r} has a malformed message."
                    )
                message_team_id = message.get("team_id")
                if (
                    message_team_id is not None
                    and message_team_id not in team_id_set
                ):
                    raise StateRestoreError(
                        f"Agent {row.get('agent_id')!r} message references "
                        f"missing team {message_team_id!r}."
                    )
        parent_map: Dict[str, Optional[str]] = {}
        for row in team_rows:
            team_id = row["team_id"]
            try:
                json.loads(row.get("status_map") or "{}")
            except Exception as exc:
                raise StateRestoreError(
                    f"Team {team_id!r} contains invalid JSON metadata."
                ) from exc
            missing_members = sorted(
                set(row.get("members", [])) - active_agent_ids
            )
            if missing_members:
                raise StateRestoreError(
                    f"Team {team_id!r} references missing members: "
                    + ", ".join(missing_members)
                )
            if len(row.get("members", [])) != len(
                set(row.get("members", []))
            ):
                raise StateRestoreError(
                    f"Team {team_id!r} contains duplicate members."
                )
            parent_id = row.get("parent_team_id")
            if parent_id is not None and parent_id not in team_id_set:
                raise StateRestoreError(
                    f"Team {team_id!r} references missing parent {parent_id!r}."
                )
            parent_map[team_id] = parent_id
            creator_type = row.get("creator_type")
            creator_id = row.get("creator_id")
            if creator_type == "agent":
                valid_creator = creator_id in active_agent_ids
            elif creator_type == "team":
                valid_creator = creator_id in team_id_set and creator_id != team_id
            else:
                valid_creator = False
            if not valid_creator:
                raise StateRestoreError(
                    f"Team {team_id!r} has invalid creator reference "
                    f"{creator_type!r}:{creator_id!r}."
                )
            for proposal in row.get("proposals", []):
                if proposal.get("action") not in {"add", "remove"}:
                    raise StateRestoreError(
                        f"Proposal {proposal.get('proposal_id')!r} has invalid "
                        f"action {proposal.get('action')!r}."
                    )
                if proposal.get("status") not in {
                    "active",
                    "approved",
                    "rejected",
                    "retracted",
                }:
                    raise StateRestoreError(
                        f"Proposal {proposal.get('proposal_id')!r} has invalid "
                        f"status {proposal.get('status')!r}."
                    )
                if not isinstance(proposal.get("proposed_details", {}), dict):
                    raise StateRestoreError(
                        f"Proposal {proposal.get('proposal_id')!r} has invalid details."
                    )
                initiator_type = proposal.get("initiator_type")
                initiator_id = proposal.get("initiator_agent_id")
                initiator_name = proposal.get("initiator_name")
                if initiator_type not in {"individual", "AT"}:
                    raise StateRestoreError(
                        f"Proposal {proposal.get('proposal_id')!r} has invalid "
                        f"initiator type {initiator_type!r}."
                    )
                if (
                    initiator_type == "individual"
                    and initiator_id not in agent_id_set
                ):
                    raise StateRestoreError(
                        f"Proposal {proposal.get('proposal_id')!r} references "
                        f"missing initiator agent {initiator_id!r}."
                    )
                if (
                    initiator_type == "AT"
                    and initiator_name not in {"AT", team_id}
                ):
                    raise StateRestoreError(
                        f"Proposal {proposal.get('proposal_id')!r} references "
                        f"invalid team initiator {initiator_name!r}."
                    )
                votes = proposal.get("votes", {})
                if not isinstance(votes, dict):
                    raise StateRestoreError(
                        f"Proposal {proposal.get('proposal_id')!r} has invalid votes."
                    )
                unknown_voters = sorted(
                    set(votes) - agent_id_set
                )
                if unknown_voters:
                    raise StateRestoreError(
                        f"Proposal {proposal.get('proposal_id')!r} references "
                        "missing voter IDs: " + ", ".join(unknown_voters)
                    )
                for voter_id, ballot in votes.items():
                    if (
                        not isinstance(ballot, dict)
                        or ballot.get("vote")
                        not in {"Agree", "Disagree", "Abstain"}
                        or not isinstance(ballot.get("public"), bool)
                        or not isinstance(ballot.get("rationale", ""), str)
                    ):
                        raise StateRestoreError(
                            f"Proposal {proposal.get('proposal_id')!r} has "
                            f"an invalid ballot for voter {voter_id!r}."
                        )

        for team_id in team_id_set:
            seen = set()
            current: Optional[str] = team_id
            while current is not None:
                if current in seen:
                    raise StateRestoreError(
                        f"Team topology contains a cycle at {current!r}."
                    )
                seen.add(current)
                current = parent_map[current]

        library_ids = [row.get("lib_id") for row in library_rows]
        if None in library_ids or len(library_ids) != len(set(library_ids)):
            raise StateRestoreError("DocLib identifiers are missing or duplicated.")
        library_id_set = set(library_ids)
        library_kind_by_id: Dict[str, str] = {}
        library_row_by_id = {
            row["lib_id"]: row for row in library_rows
        }
        private_owner_counts: Dict[str, int] = {
            agent_id: 0 for agent_id in agent_id_set
        }
        files_by_library: Dict[str, Dict[str, str]] = {}
        for row in library_rows:
            lib_id = row["lib_id"]
            if (
                not isinstance(lib_id, str)
                or lib_id in {"", ".", ".."}
                or "/" in lib_id
                or "\\" in lib_id
                or "\x00" in lib_id
            ):
                raise StateRestoreError(
                    f"Invalid DocLib identifier {lib_id!r}."
                )
            kind = row.get("library_kind")
            owner_team_id = row.get("owner_team_id")
            owner_agent_id = row.get("owner_agent_id")
            lifecycle_state = row.get("lifecycle_state")
            library_kind_by_id[lib_id] = kind
            if kind == "team":
                if owner_team_id not in team_id_set or owner_agent_id is not None:
                    raise StateRestoreError(
                        f"Team DocLib {lib_id!r} has invalid ownership."
                    )
                if lifecycle_state != "active":
                    raise StateRestoreError(
                        f"Team DocLib {lib_id!r} must be active."
                    )
            elif kind == "agent_private":
                if owner_agent_id not in agent_id_set or owner_team_id is not None:
                    raise StateRestoreError(
                        f"Private DocLib {lib_id!r} has invalid ownership."
                    )
                if lib_id != f"PDL-{owner_agent_id}":
                    raise StateRestoreError(
                        f"Private DocLib {lib_id!r} has a non-canonical ID."
                    )
                if row.get("is_public_visible"):
                    raise StateRestoreError(
                        f"Private DocLib {lib_id!r} cannot be public."
                    )
                owner_state = next(
                    agent_row.get("lifecycle_state")
                    for agent_row in agent_rows
                    if agent_row.get("agent_id") == owner_agent_id
                )
                if lifecycle_state != owner_state:
                    raise StateRestoreError(
                        f"Private DocLib {lib_id!r} lifecycle does not match its owner."
                    )
                private_owner_counts[owner_agent_id] += 1
            else:
                raise StateRestoreError(
                    f"DocLib {lib_id!r} has invalid kind {kind!r}."
                )
            normalized_files = {}
            for path, content in row.get("files", {}).items():
                clean = self._normalize_library_file_path(path)
                if clean in normalized_files:
                    raise StateRestoreError(
                        f"DocLib {lib_id!r} contains duplicate file path {clean!r}."
                    )
                if not isinstance(content, str):
                    raise StateRestoreError(
                        f"DocLib file {lib_id}:{clean} has non-text content."
                    )
                normalized_files[clean] = content
            files_by_library[lib_id] = normalized_files
        for team_id in team_id_set:
            built_in_id = f"DL-{team_id}"
            built_in = library_row_by_id.get(built_in_id)
            if built_in is None:
                raise StateRestoreError(
                    f"Team {team_id!r} is missing its built-in DocLib."
                )
            if (
                built_in.get("library_kind") != "team"
                or built_in.get("owner_team_id") != team_id
                or built_in.get("owner_agent_id") is not None
            ):
                raise StateRestoreError(
                    f"Team {team_id!r} has an invalid built-in DocLib owner."
                )
        invalid_private_counts = {
            agent_id: count
            for agent_id, count in private_owner_counts.items()
            if count != 1
        }
        if invalid_private_counts:
            details = ", ".join(
                f"{agent_id}={count}"
                for agent_id, count in sorted(invalid_private_counts.items())
            )
            raise StateRestoreError(
                "Every agent must own exactly one private DocLib: " + details
            )

        for lib_id, path_map in permissions.items():
            if lib_id not in library_id_set:
                raise StateRestoreError(
                    f"Permissions reference missing DocLib {lib_id!r}."
                )
            if library_kind_by_id[lib_id] != "team" and path_map:
                raise StateRestoreError(
                    f"Private DocLib {lib_id!r} cannot have team ACL entries."
                )
            for path, team_map in path_map.items():
                self.normalize_library_path(path)
                for team_id, permission in team_map.items():
                    if team_id not in team_id_set:
                        raise StateRestoreError(
                            f"Permissions reference missing team {team_id!r}."
                        )
                    if permission not in {"READ", "WRITE"}:
                        raise StateRestoreError(
                            f"Invalid DocLib permission {permission!r}."
                        )

        normalized_links = self._normalized_library_links(
            state.get("links", {})
        )
        for source_lib_id, path_map in normalized_links.items():
            if source_lib_id not in library_id_set:
                raise StateRestoreError(
                    f"Link references missing source DocLib {source_lib_id!r}."
                )
            if library_kind_by_id[source_lib_id] != "team" and path_map:
                raise StateRestoreError(
                    f"Private DocLib {source_lib_id!r} cannot contain managed links."
                )
            for source_path, target in path_map.items():
                target_lib_id = target["target_lib_id"]
                target_path = target["target_path"]
                if target_lib_id not in library_id_set:
                    raise StateRestoreError(
                        f"Link references missing target DocLib {target_lib_id!r}."
                    )
                if library_kind_by_id[target_lib_id] != "team":
                    raise StateRestoreError(
                        f"Managed links cannot target private DocLib {target_lib_id!r}."
                    )
                if source_lib_id == target_lib_id:
                    raise StateRestoreError(
                        "Managed links must target another DocLib."
                    )
                if source_path in files_by_library[source_lib_id]:
                    raise StateRestoreError(
                        f"Link path {source_lib_id}:{source_path} collides with a file."
                    )
                visited = set()
                node = (source_lib_id, source_path)
                while True:
                    if node in visited:
                        raise StateRestoreError(
                            f"Managed DocLib link cycle detected at {node!r}."
                        )
                    visited.add(node)
                    link = normalized_links.get(node[0], {}).get(node[1])
                    if link is None:
                        if node[1] not in files_by_library.get(node[0], {}):
                            raise StateRestoreError(
                                f"Managed link resolves to missing file {node!r}."
                            )
                        break
                    node = (link["target_lib_id"], link["target_path"])

        self._validate_communication_state(
            communication_requests,
            communication_approvals,
            communication_ballots,
            communication_agreements,
            peer_messages,
            team_id_set,
            agent_id_set,
            root_id,
            {
                row["team_id"]: row.get("inbox", [])
                for row in team_rows
            },
        )
        return config

    def _validate_communication_state(
        self,
        request_rows: List[Dict[str, Any]],
        approval_rows: List[Dict[str, Any]],
        ballot_rows: List[Dict[str, Any]],
        agreement_rows: List[Dict[str, Any]],
        peer_message_rows: List[Dict[str, Any]],
        team_ids: set[str],
        agent_ids: set[str],
        root_agent_id: str,
        inboxes: Dict[str, List[Dict[str, Any]]],
    ) -> None:
        """Validates schema-6 communication references and state combinations."""
        from .communication import (
            CommunicationAgreement,
            CommunicationApproval,
            CommunicationApprovalStatus,
            CommunicationBallot,
            CommunicationRequest,
            CommunicationRequestStatus,
            PeerMessage,
            route_fingerprint,
        )
        from .config import _parse_communication_config

        try:
            requests = [
                CommunicationRequest.model_validate(row)
                for row in request_rows
            ]
            approvals = [
                CommunicationApproval.model_validate(row)
                for row in approval_rows
            ]
            ballots = [
                CommunicationBallot.model_validate(row)
                for row in ballot_rows
            ]
            agreements = [
                CommunicationAgreement.model_validate(row)
                for row in agreement_rows
            ]
            messages = [PeerMessage.model_validate(row) for row in peer_message_rows]
        except Exception as exc:
            raise StateRestoreError(
                f"Invalid communication state payload: {exc}"
            ) from exc

        request_by_id = {request.request_id: request for request in requests}
        if len(request_by_id) != len(requests):
            raise StateRestoreError("Communication request IDs are duplicated.")
        approval_keys = [approval.key for approval in approvals]
        if len(approval_keys) != len(set(approval_keys)):
            raise StateRestoreError("Communication approvals are duplicated.")
        agreement_ids = [agreement.agreement_id for agreement in agreements]
        if len(agreement_ids) != len(set(agreement_ids)):
            raise StateRestoreError("Communication agreement IDs are duplicated.")
        message_ids = [message.message_id for message in messages]
        if len(message_ids) != len(set(message_ids)):
            raise StateRestoreError("Peer message IDs are duplicated.")

        approvals_by_request: Dict[str, List[Any]] = {}
        for request in requests:
            if request.sender_team_id not in team_ids or request.recipient_team_id not in team_ids:
                raise StateRestoreError(
                    f"Communication request {request.request_id!r} references a missing AgentTeam."
                )
            if request.sender_team_id == request.recipient_team_id:
                raise StateRestoreError(
                    f"Communication request {request.request_id!r} is self-addressed."
                )
            if request.initiated_by_agent_id not in agent_ids:
                raise StateRestoreError(
                    f"Communication request {request.request_id!r} references a missing initiator Agent."
                )
            try:
                policy = _parse_communication_config(request.policy_snapshot)
            except Exception as exc:
                raise StateRestoreError(
                    f"Communication request {request.request_id!r} has an "
                    f"invalid policy snapshot: {exc}"
                ) from exc
            if policy.policy == "permissive":
                raise StateRestoreError(
                    f"Communication request {request.request_id!r} cannot use "
                    "the permissive policy."
                )
            if request.direction.value != policy.direction:
                raise StateRestoreError(
                    f"Communication request {request.request_id!r} direction "
                    "does not match its policy snapshot."
                )
            principal_keys = [
                principal.key for principal in request.approval_principals
            ]
            if not principal_keys or len(principal_keys) != len(
                set(principal_keys)
            ):
                raise StateRestoreError(
                    f"Communication request {request.request_id!r} has an "
                    "empty or duplicated approval route."
                )
            if route_fingerprint(request.approval_principals) != request.route_fingerprint:
                raise StateRestoreError(
                    f"Communication request {request.request_id!r} has an invalid route fingerprint."
                )
            for principal in request.approval_principals:
                if principal.kind == "agent_team" and principal.principal_id not in team_ids:
                    raise StateRestoreError(
                        f"Communication request {request.request_id!r} references a missing approval AgentTeam."
                    )
                if principal.kind == "agent" and principal.principal_id != root_agent_id:
                    raise StateRestoreError(
                        f"Communication request {request.request_id!r} references an unauthorized approval Agent."
                    )

        for approval in approvals:
            request = request_by_id.get(approval.request_id)
            if request is None or approval.principal not in request.approval_principals:
                raise StateRestoreError(
                    f"Communication approval {approval.key!r} has no matching request principal."
                )
            approvals_by_request.setdefault(approval.request_id, []).append(approval)
        for request in requests:
            request_approvals = sorted(
                approvals_by_request.get(request.request_id, []),
                key=lambda item: item.sequence,
            )
            if len(request_approvals) != len(request.approval_principals):
                raise StateRestoreError(
                    f"Communication request {request.request_id!r} has incomplete approvals."
                )
            if [item.sequence for item in request_approvals] != list(
                range(len(request.approval_principals))
            ) or any(
                approval.principal != request.approval_principals[index]
                for index, approval in enumerate(request_approvals)
            ):
                raise StateRestoreError(
                    f"Communication request {request.request_id!r} has an "
                    "invalid approval order."
                )
            statuses = {approval.status for approval in request_approvals}
            if request.status in {
                CommunicationRequestStatus.APPROVED,
                CommunicationRequestStatus.STALE,
            } and statuses != {CommunicationApprovalStatus.APPROVED}:
                raise StateRestoreError(
                    f"Terminal communication request {request.request_id!r} "
                    "lacks unanimous principal approval."
                )
            if request.status is CommunicationRequestStatus.DENIED and (
                CommunicationApprovalStatus.DENIED not in statuses
                or statuses
                & {
                    CommunicationApprovalStatus.PENDING,
                    CommunicationApprovalStatus.PROCESSING,
                }
            ):
                raise StateRestoreError(
                    f"Denied communication request {request.request_id!r} has "
                    "an invalid approval state."
                )
            if request.status in {
                CommunicationRequestStatus.PENDING,
                CommunicationRequestStatus.PROCESSING,
            } and statuses & {
                CommunicationApprovalStatus.DENIED,
                CommunicationApprovalStatus.CANCELLED,
            }:
                raise StateRestoreError(
                    f"Pending communication request {request.request_id!r} "
                    "contains a terminal approval."
                )
            if (
                request.status is CommunicationRequestStatus.PENDING
                and CommunicationApprovalStatus.PROCESSING in statuses
            ):
                raise StateRestoreError(
                    f"Pending communication request {request.request_id!r} "
                    "contains a processing approval."
                )
            if (
                request.status is CommunicationRequestStatus.PENDING
                and statuses == {CommunicationApprovalStatus.APPROVED}
            ):
                raise StateRestoreError(
                    f"Pending communication request {request.request_id!r} "
                    "already has unanimous approval."
                )
            if (
                request.status is CommunicationRequestStatus.PROCESSING
                and CommunicationApprovalStatus.PROCESSING not in statuses
            ):
                raise StateRestoreError(
                    f"Processing communication request {request.request_id!r} "
                    "has no processing approval."
                )
            terminal = request.status in {
                CommunicationRequestStatus.APPROVED,
                CommunicationRequestStatus.DENIED,
                CommunicationRequestStatus.STALE,
            }
            if terminal != (request.resolved_at is not None):
                raise StateRestoreError(
                    f"Communication request {request.request_id!r} has an "
                    "invalid resolution timestamp."
                )
            for approval in request_approvals:
                approval_terminal = approval.status in {
                    CommunicationApprovalStatus.APPROVED,
                    CommunicationApprovalStatus.DENIED,
                    CommunicationApprovalStatus.CANCELLED,
                }
                if approval_terminal != (approval.resolved_at is not None):
                    raise StateRestoreError(
                        f"Communication approval {approval.key!r} has an "
                        "invalid resolution timestamp."
                    )

        for request in requests:
            successor_id = request.superseded_by_request_id
            predecessor_id = request.supersedes_request_id
            if request.status is CommunicationRequestStatus.STALE:
                if successor_id is None:
                    raise StateRestoreError(
                        f"Stale communication request {request.request_id!r} "
                        "has no successor."
                    )
            elif successor_id is not None:
                raise StateRestoreError(
                    f"Non-stale communication request {request.request_id!r} "
                    "references a successor."
                )
            if successor_id is not None:
                successor = request_by_id.get(successor_id)
                if (
                    successor is None
                    or successor.supersedes_request_id != request.request_id
                ):
                    raise StateRestoreError(
                        f"Communication request {request.request_id!r} has an "
                        "invalid successor reference."
                    )
            if predecessor_id is not None:
                predecessor = request_by_id.get(predecessor_id)
                if (
                    predecessor is None
                    or predecessor.superseded_by_request_id != request.request_id
                ):
                    raise StateRestoreError(
                        f"Communication request {request.request_id!r} has an "
                        "invalid predecessor reference."
                    )
            seen = set()
            current = request
            while current.superseded_by_request_id is not None:
                if current.request_id in seen:
                    raise StateRestoreError(
                        "Communication request successor chain contains a cycle."
                    )
                seen.add(current.request_id)
                current = request_by_id[current.superseded_by_request_id]

        ballot_keys = [
            (
                ballot.request_id,
                ballot.principal.key,
                ballot.voter_agent_id,
            )
            for ballot in ballots
        ]
        if len(ballot_keys) != len(set(ballot_keys)):
            raise StateRestoreError("Communication ballots are duplicated.")
        for ballot in ballots:
            if ballot.request_id not in request_by_id or ballot.voter_agent_id not in agent_ids:
                raise StateRestoreError("Communication ballot has a missing reference.")
            if ballot.principal.kind != "agent_team":
                raise StateRestoreError(
                    "Only an AgentTeam approval may contain member ballots."
                )
            if not any(
                approval.request_id == ballot.request_id
                and approval.principal == ballot.principal
                for approval in approvals
            ):
                raise StateRestoreError("Communication ballot has no matching approval.")

        agreement_by_id = {item.agreement_id: item for item in agreements}
        agreements_by_request: Dict[str, List[Any]] = {}
        for agreement in agreements:
            if agreement.source_team_id not in team_ids or agreement.target_team_id not in team_ids:
                raise StateRestoreError("Communication agreement references a missing AgentTeam.")
            request = request_by_id.get(agreement.created_from_request_id)
            if request is None or request.status is not CommunicationRequestStatus.APPROVED:
                raise StateRestoreError("Communication agreement has no approved source request.")
            agreements_by_request.setdefault(request.request_id, []).append(
                agreement
            )
            if (
                agreement.source_team_id != request.sender_team_id
                or agreement.target_team_id != request.recipient_team_id
                or agreement.direction is not request.direction
                or agreement.policy_snapshot != request.policy_snapshot
                or agreement.allowed_message_types != ["peer_message"]
            ):
                raise StateRestoreError(
                    "Communication agreement does not match its source request."
                )
            if agreement.revoked_by_team_id is not None and agreement.revoked_by_team_id not in {
                agreement.source_team_id,
                agreement.target_team_id,
            }:
                raise StateRestoreError("Communication agreement was revoked by a non-endpoint AgentTeam.")
            if agreement.superseded_by_agreement_id is not None and agreement.superseded_by_agreement_id not in agreement_by_id:
                raise StateRestoreError("Communication agreement references a missing successor.")
            if agreement.active and (
                agreement.revoked_at is not None
                or agreement.revoked_by_team_id is not None
                or agreement.revoke_reason is not None
                or agreement.superseded_by_agreement_id is not None
            ):
                raise StateRestoreError(
                    "Active communication agreement contains revocation metadata."
                )
            if not agreement.active and agreement.revoked_at is None:
                raise StateRestoreError(
                    "Inactive communication agreement lacks a revocation timestamp."
                )

        for request in requests:
            source_agreements = agreements_by_request.get(
                request.request_id, []
            )
            if request.status is CommunicationRequestStatus.APPROVED:
                if len(source_agreements) != 1:
                    raise StateRestoreError(
                        f"Approved communication request {request.request_id!r} "
                        "must create exactly one agreement."
                    )
            elif source_agreements:
                raise StateRestoreError(
                    f"Non-approved communication request {request.request_id!r} "
                    "created an agreement."
                )

        active_routes = set()
        for agreement in agreements:
            if not agreement.active:
                continue
            routes = {(agreement.source_team_id, agreement.target_team_id)}
            if agreement.direction.value == "bidirectional":
                routes.add(
                    (agreement.target_team_id, agreement.source_team_id)
                )
            if active_routes & routes:
                raise StateRestoreError("Duplicate active communication route.")
            active_routes.update(routes)

        invocation_ids = [message.invocation_id for message in messages if message.invocation_id]
        if len(invocation_ids) != len(set(invocation_ids)):
            raise StateRestoreError("Peer message invocation IDs are duplicated.")
        for message in messages:
            if message.sender_team_id not in team_ids or message.recipient_team_id not in team_ids:
                raise StateRestoreError("Peer message references a missing AgentTeam.")
            if message.sender_team_id == message.recipient_team_id:
                raise StateRestoreError("Peer message is self-addressed.")
            if message.initiated_by_agent_id not in agent_ids:
                raise StateRestoreError("Peer message references a missing initiating Agent.")
            if message.agreement_id is not None:
                agreement = agreement_by_id.get(message.agreement_id)
                if agreement is None:
                    raise StateRestoreError(
                        "Peer message references a missing Agreement."
                    )
                forward = (
                    message.sender_team_id == agreement.source_team_id
                    and message.recipient_team_id == agreement.target_team_id
                )
                reverse = (
                    agreement.direction.value == "bidirectional"
                    and message.sender_team_id == agreement.target_team_id
                    and message.recipient_team_id == agreement.source_team_id
                )
                if not (forward or reverse):
                    raise StateRestoreError(
                        "Peer message route is not covered by its Agreement."
                    )
            if (message.delivery_state == "consumed") != (
                message.consumed_at is not None
            ):
                raise StateRestoreError(
                    "Peer message has an invalid consumption timestamp."
                )

        approval_by_team_request = {
            (approval.principal.principal_id, approval.request_id): approval
            for approval in approvals
            if approval.principal.kind == "agent_team"
        }
        approval_notifications: Dict[tuple[str, str], int] = {}
        peer_notifications: Dict[str, List[str]] = {}
        for team_id, inbox in inboxes.items():
            if not isinstance(inbox, list):
                raise StateRestoreError(
                    f"AgentTeam {team_id!r} has an invalid inbox."
                )
            for item in inbox:
                if not isinstance(item, dict):
                    raise StateRestoreError(
                        f"AgentTeam {team_id!r} has a malformed inbox item."
                    )
                if item.get("type") == "communication_approval_request":
                    request_id = item.get("request_id")
                    key = (team_id, request_id)
                    approval = approval_by_team_request.get(key)
                    request = request_by_id.get(request_id)
                    if (
                        approval is None
                        or request is None
                        or approval.status
                        not in {
                            CommunicationApprovalStatus.PENDING,
                            CommunicationApprovalStatus.PROCESSING,
                        }
                        or request.status
                        not in {
                            CommunicationRequestStatus.PENDING,
                            CommunicationRequestStatus.PROCESSING,
                        }
                    ):
                        raise StateRestoreError(
                            "Communication approval inbox item has no active "
                            "matching Approval."
                        )
                    approval_notifications[key] = (
                        approval_notifications.get(key, 0) + 1
                    )
                elif item.get("type") == "peer_message":
                    message_id = item.get("message_id")
                    if not isinstance(message_id, str):
                        raise StateRestoreError(
                            "Peer inbox item lacks a durable message ID."
                        )
                    peer_notifications.setdefault(message_id, []).append(
                        team_id
                    )

        expected_approval_notifications = {
            (approval.principal.principal_id, approval.request_id)
            for approval in approvals
            if approval.principal.kind == "agent_team"
            and approval.status
            in {
                CommunicationApprovalStatus.PENDING,
                CommunicationApprovalStatus.PROCESSING,
            }
            and request_by_id[approval.request_id].status
            in {
                CommunicationRequestStatus.PENDING,
                CommunicationRequestStatus.PROCESSING,
            }
        }
        if set(approval_notifications) != expected_approval_notifications or any(
            count != 1 for count in approval_notifications.values()
        ):
            raise StateRestoreError(
                "Communication approval inbox notifications are incomplete or duplicated."
            )
        for message in messages:
            notification_teams = peer_notifications.pop(
                message.message_id, []
            )
            if message.delivery_state == "pending":
                if notification_teams != [message.recipient_team_id]:
                    raise StateRestoreError(
                        "Pending peer delivery is missing or duplicated in the "
                        "recipient inbox."
                    )
            elif notification_teams:
                raise StateRestoreError(
                    "Consumed peer delivery remains in an AgentTeam inbox."
                )
        if peer_notifications:
            raise StateRestoreError(
                "AgentTeam inbox references an unknown peer delivery."
            )

    def _normalized_library_links(
        self, links: Dict[str, Dict[str, Dict[str, str]]]
    ) -> Dict[str, Dict[str, Dict[str, str]]]:
        normalized: Dict[str, Dict[str, Dict[str, str]]] = {}
        try:
            for source_lib_id, path_map in links.items():
                for source_path, target in path_map.items():
                    clean_source = self._normalize_library_file_path(source_path)
                    clean_target = self._normalize_library_file_path(
                        target["target_path"]
                    )
                    source_map = normalized.setdefault(source_lib_id, {})
                    if clean_source in source_map:
                        raise ValueError(
                            f"Duplicate normalized link path {clean_source!r}."
                        )
                    source_map[clean_source] = {
                        "target_lib_id": target["target_lib_id"],
                        "target_path": clean_target,
                    }
        except Exception as exc:
            raise StateRestoreError(
                f"Invalid managed DocLib link metadata: {exc}"
            ) from exc
        return normalized

    def _publish_staged_libraries(
        self,
        libraries: Dict[str, DocumentLibrary],
        managed_root: str,
    ) -> List[Tuple[str, Optional[str]]]:
        published: List[Tuple[str, Optional[str]]] = []
        try:
            staged_ids = set(libraries)
            for lib_id, old_library in self.libraries.items():
                final_root = os.path.join(managed_root, lib_id)
                if (
                    lib_id in staged_ids
                    or os.path.abspath(old_library.root_dir)
                    != os.path.abspath(final_root)
                    or not os.path.exists(final_root)
                ):
                    continue
                backup = os.path.join(
                    managed_root,
                    f".{lib_id}-restore-backup-{uuid.uuid4().hex}",
                )
                os.replace(final_root, backup)
                published.append((final_root, backup))
            for lib_id, library in libraries.items():
                final_root = os.path.join(managed_root, lib_id)
                if os.path.lexists(final_root) and os.path.islink(final_root):
                    raise PermissionError(
                        f"DocLib root {final_root!r} is a symbolic link."
                    )
                backup = None
                if os.path.exists(final_root):
                    backup = os.path.join(
                        managed_root,
                        f".{lib_id}-restore-backup-{uuid.uuid4().hex}",
                    )
                    os.replace(final_root, backup)
                published.append((final_root, backup))
                os.replace(library.root_dir, final_root)
                library.root_dir = final_root
            return published
        except Exception:
            self._rollback_published_libraries(published)
            raise

    def _publish_new_staged_libraries(
        self,
        libraries: Dict[str, DocumentLibrary],
        managed_root: str,
    ) -> List[Tuple[str, Optional[str]]]:
        """Atomically publishes only newly created DocLib directories."""
        published: List[Tuple[str, Optional[str]]] = []
        try:
            for lib_id, library in libraries.items():
                final_root = os.path.join(managed_root, lib_id)
                if os.path.lexists(final_root):
                    raise FileExistsError(
                        f"DocLib storage already exists for {lib_id!r}."
                    )
                os.replace(library.root_dir, final_root)
                library.root_dir = final_root
                published.append((final_root, None))
            return published
        except Exception:
            self._rollback_published_libraries(published)
            raise

    @staticmethod
    def _rollback_published_libraries(
        published: List[Tuple[str, Optional[str]]]
    ) -> None:
        for final_root, backup in reversed(published):
            if os.path.exists(final_root):
                shutil.rmtree(final_root, ignore_errors=True)
            if backup and os.path.exists(backup):
                os.replace(backup, final_root)

    @staticmethod
    def _discard_library_backups(
        published: List[Tuple[str, Optional[str]]]
    ) -> None:
        for _, backup in published:
            if backup:
                shutil.rmtree(backup, ignore_errors=True)

    def _new_document_library(
        self,
        *,
        lib_id: str,
        name: str,
        owner_team_id: Optional[str] = None,
        owner_agent_id: Optional[str] = None,
        library_kind: str = "team",
        lifecycle_state: str = "active",
        description: str,
        is_public_visible: bool,
        storage_dir: Optional[str] = None,
    ) -> DocumentLibrary:
        self._library_files.setdefault(lib_id, {})
        return self._build_document_library(
            lib_id=lib_id,
            name=name,
            owner_team_id=owner_team_id,
            owner_agent_id=owner_agent_id,
            library_kind=library_kind,
            lifecycle_state=lifecycle_state,
            description=description,
            is_public_visible=is_public_visible,
            storage_dir=storage_dir,
        )

    def _build_document_library(
        self,
        *,
        lib_id: str,
        name: str,
        owner_team_id: Optional[str] = None,
        owner_agent_id: Optional[str] = None,
        library_kind: str = "team",
        lifecycle_state: str = "active",
        description: str,
        is_public_visible: bool,
        storage_dir: Optional[str] = None,
    ) -> DocumentLibrary:
        """Builds a DocLib without publishing it in manager registries."""
        return DocumentLibrary(
            lib_id=lib_id,
            name=name,
            owner_team_id=owner_team_id,
            owner_agent_id=owner_agent_id,
            library_kind=library_kind,
            lifecycle_state=lifecycle_state,
            description=description,
            is_public_visible=is_public_visible,
            root_dir=self.config.workspace_root,
            on_change=self._on_library_change,
            storage_dir=storage_dir,
        )

    def register_agent(
        self, agent: Agent, *, auto_save: bool = True
    ) -> Agent:
        """Registers one stable agent identity and creates its private DocLib."""
        if not isinstance(agent, Agent):
            raise TypeError("agent must be an Agent instance.")
        if agent.lifecycle_state != "active":
            raise ValueError(
                "Only a new active Agent can be registered; inactive "
                "identities require reactivate_agent()."
            )
        existing_by_id = self._agents_by_id.get(agent.agent_id)
        if existing_by_id is not None and existing_by_id is not agent:
            raise ValueError(
                f"Agent ID {agent.agent_id!r} is already registered."
            )
        existing_by_name = self.agents.get(agent.name)
        if existing_by_name is not None and existing_by_name is not agent:
            raise ValueError(f"Agent name {agent.name!r} is already registered.")
        for known in self._agents_by_id.values():
            if known is not agent and known.name == agent.name:
                raise ValueError(f"Agent name {agent.name!r} is already reserved.")

        if existing_by_id is agent and agent.lifecycle_state != "active":
            raise ValueError(
                "Inactive agents must be restored with reactivate_agent()."
            )

        agent.lifecycle_state = "active"
        lib_id = agent.private_doc_library_id or f"PDL-{agent.agent_id}"
        expected = f"PDL-{agent.agent_id}"
        if lib_id != expected:
            raise ValueError(
                f"Private DocLib ID must be {expected!r} for this agent."
            )
        library = self.libraries.get(lib_id)
        if library is None:
            library = self._new_document_library(
                lib_id=lib_id,
                name=f"{agent.name} Private Library",
                owner_agent_id=agent.agent_id,
                library_kind="agent_private",
                lifecycle_state="active",
                description=(
                    f"Persistent private workspace for agent {agent.name}."
                ),
                is_public_visible=False,
            )
            self.libraries[lib_id] = library
        elif (
            library.library_kind != "agent_private"
            or library.owner_agent_id != agent.agent_id
        ):
            raise ValueError("Private DocLib ownership is inconsistent.")
        agent._private_doc_library_id = lib_id
        self._agents_by_id[agent.agent_id] = agent
        self.agents[agent.name] = agent
        if auto_save:
            self._auto_save(
                agents={agent.agent_id}, libraries={lib_id}
            )
        return agent

    def get_private_library_id(self, agent_id: str) -> str:
        """Returns the one private library associated with an agent identity."""
        agent = self._agents_by_id.get(agent_id)
        if agent is None or agent.private_doc_library_id is None:
            raise KeyError(f"Unknown agent ID {agent_id!r}.")
        return agent.private_doc_library_id

    def _require_private_agent_context(self) -> Tuple[Agent, DocumentLibrary]:
        """Resolves private ownership exclusively from invocation context."""
        agent = self._active_tool_agent.get()
        if agent is None:
            raise PermissionError(
                "Private DocLib access requires an active agent invocation."
            )
        registered = self._agents_by_id.get(agent.agent_id)
        if (
            registered is not agent
            or agent.lifecycle_state != "active"
            or self.agents.get(agent.name) is not agent
        ):
            raise PermissionError("The active agent identity is not active.")
        lib_id = agent.private_doc_library_id
        library = self.libraries.get(lib_id or "")
        if (
            library is None
            or library.library_kind != "agent_private"
            or library.owner_agent_id != agent.agent_id
        ):
            raise PermissionError("Private DocLib ownership is unavailable.")
        return agent, library

    async def retire_agent(
        self,
        agent_id: str,
        policy: Optional[str] = None,
        confirm_delete: bool = False,
    ) -> None:
        """Retires one unused agent under the configured private-data policy."""
        agent = self._agents_by_id.get(agent_id)
        if agent is None:
            raise KeyError(f"Unknown agent ID {agent_id!r}.")
        async with agent.lifecycle_lock:
            await self._retire_agent_locked(
                agent_id, policy=policy, confirm_delete=confirm_delete
            )

    async def _retire_agent_locked(
        self,
        agent_id: str,
        policy: Optional[str] = None,
        confirm_delete: bool = False,
    ) -> None:
        """Implements retirement while the identity lifecycle lock is held."""
        selected = policy or self.config.agent_private_data_policy
        if selected not in {"retain", "archive", "delete"}:
            raise ValueError("policy must be retain, archive, or delete.")
        agent = self._agents_by_id.get(agent_id)
        if agent is None:
            raise KeyError(f"Unknown agent ID {agent_id!r}.")
        if agent.lifecycle_state != "active":
            raise ValueError("Agent is already inactive.")
        if agent is self.root_ai:
            raise ValueError("The root agent cannot be retired.")
        if selected == "delete" and not confirm_delete:
            raise ValueError("Permanent deletion requires confirm_delete=True.")

        if selected == "delete":
            # Revalidate every deletion precondition after all previously
            # accepted persistence work has completed.
            await self.flush_state()

        memberships = [
            team.team_id for team in self.teams.values() if agent in team.members
        ]
        if memberships:
            raise ValueError(
                "Agent still belongs to teams: " + ", ".join(sorted(memberships))
            )
        creator_teams = [
            team.team_id for team in self.teams.values() if team.creator is agent
        ]
        if creator_teams:
            raise ValueError(
                "Agent still creates teams: " + ", ".join(sorted(creator_teams))
            )
        if agent.lock.locked():
            raise ValueError("Agent has an active model invocation.")

        if selected == "delete":
            governance_refs = [
                f"{team.team_id}:{proposal_id}"
                for team in self.teams.values()
                for proposal_id, proposal in team.proposals.items()
                if proposal.get("initiator_agent_id") == agent_id
                or agent_id in proposal.get("votes", {})
            ]
            governance_refs.extend(
                f"communication-request:{request.request_id}"
                for request in self.broker.communication_requests.values()
                if request.initiated_by_agent_id == agent_id
            )
            governance_refs.extend(
                f"communication-ballot:{request_id}"
                for request_id, ballots in self.broker.ballots.items()
                if any(
                    ballot.voter_agent_id == agent_id
                    for ballot in ballots
                )
            )
            governance_refs.extend(
                f"peer-message:{message.message_id}"
                for message in self.broker.peer_messages.values()
                if message.initiated_by_agent_id == agent_id
            )
            if governance_refs:
                raise ValueError(
                    "Agent still has governance records: "
                    + ", ".join(sorted(governance_refs))
                )

        lib_id = self.get_private_library_id(agent_id)
        library = self.libraries[lib_id]
        if selected in {"retain", "archive"}:
            alias = self.resolve_model_alias(agent.llm_client)
            old_alias = agent._model_alias
            agent._model_alias = alias
            state = "retained" if selected == "retain" else "archived"
            old_client = agent.llm_client
            agent.lifecycle_state = state
            with library._lock:
                library.lifecycle_state = state
            self.agents.pop(agent.name, None)
            agent.llm_client = None
            try:
                self._auto_save(agents={agent_id}, libraries={lib_id})
                await self.flush_state()
            except Exception:
                agent.lifecycle_state = "active"
                with library._lock:
                    library.lifecycle_state = "active"
                agent.llm_client = old_client
                agent._model_alias = old_alias
                self.agents[agent.name] = agent
                raise
            self._emit_callback(
                "on_system_event",
                "agent_lifecycle_changed",
                {"agent_id": agent_id, "state": state, "library_id": lib_id},
            )
            return

        parent_dir = os.path.dirname(library.root_dir)
        trash_path = os.path.join(
            parent_dir, f".{lib_id}-delete-{uuid.uuid4().hex}"
        )
        old_files = self._library_files.get(lib_id, {})
        old_links = self.library_links.get(lib_id)
        old_permissions = self.library_permissions.get(lib_id)
        moved = False
        committed = False
        try:
            agent.lifecycle_state = "deleting"
            with library._lock:
                library.lifecycle_state = "archived"
                if os.path.exists(library.root_dir):
                    os.replace(library.root_dir, trash_path)
                    moved = True
            self.agents.pop(agent.name, None)
            self._agents_by_id.pop(agent_id, None)
            self.libraries.pop(lib_id, None)
            self._library_files.pop(lib_id, None)
            self.library_links.pop(lib_id, None)
            self.library_permissions.pop(lib_id, None)
            self._auto_save(
                deleted_agents={agent_id}, deleted_libraries={lib_id}
            )
            await self.flush_state()
            committed = True
        except Exception:
            self._agents_by_id[agent_id] = agent
            self.agents[agent.name] = agent
            self.libraries[lib_id] = library
            self._library_files[lib_id] = old_files
            if old_links is not None:
                self.library_links[lib_id] = old_links
            if old_permissions is not None:
                self.library_permissions[lib_id] = old_permissions
            if moved and os.path.exists(trash_path):
                os.replace(trash_path, library.root_dir)
            with library._lock:
                library.lifecycle_state = "active"
            agent.lifecycle_state = "active"
            raise
        finally:
            if committed and os.path.exists(trash_path):
                shutil.rmtree(trash_path, ignore_errors=True)
        self._emit_callback(
            "on_system_event",
            "agent_lifecycle_changed",
            {"agent_id": agent_id, "state": "deleted", "library_id": lib_id},
        )
        agent.lifecycle_state = "deleted"
        agent.llm_client = None
        agent._private_doc_library_id = None
        agent.messages.clear()
        agent.message_history.clear()
        agent._history_seen_ids.clear()

    async def reactivate_agent(self, agent_id: str, model_alias: str) -> Agent:
        """Reactivates a retained or archived identity with a stable binding."""
        agent = self._agents_by_id.get(agent_id)
        if agent is None:
            raise KeyError(f"Unknown agent ID {agent_id!r}.")
        async with agent.lifecycle_lock:
            return await self._reactivate_agent_locked(agent_id, model_alias)

    async def _reactivate_agent_locked(
        self, agent_id: str, model_alias: str
    ) -> Agent:
        """Implements reactivation while the identity lifecycle lock is held."""
        agent = self._agents_by_id.get(agent_id)
        if agent is None:
            raise KeyError(f"Unknown agent ID {agent_id!r}.")
        if agent.lifecycle_state == "active":
            raise ValueError("Agent is already active.")
        if self.agents.get(agent.name) not in {None, agent}:
            raise ValueError(f"Agent name {agent.name!r} is already active.")
        if model_alias == "default":
            if "default" in self.llm_clients:
                client = self.llm_clients["default"]
            elif self.generator_handler is not None:
                client = ManagerDefaultClientAdapter(self)
            else:
                raise ValueError("The default model alias has no runtime binding.")
        elif model_alias in self.llm_clients:
            client = self.llm_clients[model_alias]
        elif model_alias in self.model_configs and self.generator_handler:
            client = HandlerClientAdapter(model_alias, self.generator_handler)
            client._supports_native = (
                self.model_configs.get(model_alias, {}).get(
                    "supports_native_tool_calling"
                )
                is True
            )
        else:
            raise ValueError(
                f"Model alias {model_alias!r} has no runtime binding."
            )
        lib_id = self.get_private_library_id(agent_id)
        library = self.libraries[lib_id]
        old_state = agent.lifecycle_state
        old_library_state = library.lifecycle_state
        old_alias = agent._model_alias
        agent.llm_client = client
        agent._model_alias = model_alias
        agent.lifecycle_state = "active"
        with library._lock:
            library.lifecycle_state = "active"
        self.agents[agent.name] = agent
        try:
            self._auto_save(agents={agent_id}, libraries={lib_id})
            await self.flush_state()
        except Exception:
            self.agents.pop(agent.name, None)
            agent.llm_client = None
            agent._model_alias = old_alias
            agent.lifecycle_state = old_state
            with library._lock:
                library.lifecycle_state = old_library_state
            raise
        self._emit_callback(
            "on_system_event",
            "agent_lifecycle_changed",
            {"agent_id": agent_id, "state": "active", "library_id": lib_id},
        )
        return agent

    def _on_library_change(
        self, lib_id: str, path: str, content: Optional[str]
    ) -> None:
        with self._snapshot_lock:
            files = self._library_files.setdefault(lib_id, {})
            if content is None:
                files.pop(path, None)
            else:
                files[path] = content
            self._auto_save(
                libraries={lib_id},
                file_changes={lib_id: {path: content}},
            )
        library = self.libraries.get(lib_id)
        if library is not None and library.library_kind == "agent_private":
            self._emit_callback(
                "on_system_event",
                "private_library_file_changed",
                {
                    "agent_id": library.owner_agent_id,
                    "library_id": lib_id,
                    "path": path,
                    "operation": "delete" if content is None else "write",
                    "result": "success",
                },
            )

    def register_tool(
        self,
        name: Any = None,
        description: Optional[str] = None,
        func: Optional[Callable[..., Any]] = None,
        schema: Optional[Any] = None
    ):
        """Registers a custom utility tool to all teams."""
        tool = Tool(name, description, func, schema)
        self.global_tools[tool.name] = tool
        # Bind to existing teams
        for team in self.teams.values():
            team.tools[tool.name] = tool

    def register_tool_auditor(self, tool_name: str, auditor_func: Callable[..., Tuple[bool, str]]):
        """Registers an auditing hook executed before specific tool calls."""
        self.tool_auditors[tool_name] = auditor_func

    def register_model(
        self,
        name: str,
        config: Dict[str, Any],
        client: Optional[Any] = None,
    ):
        """Registers a unified model configuration (e.g. metadata, type, ai_note)."""
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Model alias must be a non-empty string.")
        if not isinstance(config, dict):
            raise ValueError("Model configuration must be a dictionary.")
        self.model_configs[name] = dict(config)
        if client is not None:
            self.register_llm_client(name, client)
        self._auto_save(configs=True)

    def register_llm_client(self, alias: str, client: Any) -> None:
        """Binds one stable alias to one runtime client identity."""
        if not isinstance(alias, str) or not alias.strip():
            raise ValueError("LLM client alias must be a non-empty string.")
        if client is None:
            raise ValueError("LLM client cannot be None.")
        conflicting = [
            name
            for name, registered in self.llm_clients.items()
            if registered is client and name != alias
        ]
        if conflicting:
            raise ValueError(
                f"LLM client is already registered as {conflicting[0]!r}; "
                "one client identity may have only one stable alias."
            )
        existing = self.llm_clients.get(alias)
        if existing is not None and existing is not client:
            raise ValueError(
                f"LLM client alias {alias!r} is already bound to another client."
            )
        self.llm_clients[alias] = client

    def register_generator_handler(self, handler: Callable[..., str]):
        """Registers a global callback handler for generating text from a model alias."""
        self.generator_handler = handler

    def count_tokens(self, text: str, model_alias: str) -> int:
        """Counts tokens for the given text using tokenizers or falls back to len(text)//4."""
        if not text:
            return 0
        
        tokenizer_name_or_path = self.config.model_tokenizer_configs.get(model_alias)
        if not tokenizer_name_or_path:
            tokenizer_name_or_path = self.config.model_tokenizer_configs.get("default")
            
        if tokenizer_name_or_path:
            try:
                if not hasattr(self, "_tokenizer_cache"):
                    self._tokenizer_cache = {}
                
                if tokenizer_name_or_path not in self._tokenizer_cache:
                    from tokenizers import Tokenizer
                    if tokenizer_name_or_path.endswith(".json") and os.path.exists(tokenizer_name_or_path):
                        tokenizer = Tokenizer.from_file(tokenizer_name_or_path)
                    else:
                        tokenizer = Tokenizer.from_pretrained(tokenizer_name_or_path)
                    self._tokenizer_cache[tokenizer_name_or_path] = tokenizer
                
                tokenizer = self._tokenizer_cache[tokenizer_name_or_path]
                encoded = tokenizer.encode(text)
                return len(encoded.ids)
            except Exception as e:
                self.logger.warning(f"Tokenizer error for {tokenizer_name_or_path}: {e}. Falling back to character-based heuristic.")
        
        return max(1, len(text) // 4)

    def resolve_model_alias(self, llm_client: Any) -> str:
        """Returns a stable alias or fails instead of collapsing to default."""
        from .adapters import ManagerDefaultClientAdapter

        if isinstance(llm_client, ManagerDefaultClientAdapter):
            return "default"
        if isinstance(llm_client, HandlerClientAdapter):
            alias = llm_client.model_name
            if (
                llm_client.handler is self.generator_handler
                and (alias == "default" or alias in self.model_configs)
            ):
                return alias

        aliases = [
            name
            for name, client in self.llm_clients.items()
            if client is llm_client
        ]
        if len(aliases) == 1:
            return aliases[0]
        if len(aliases) > 1:
            raise ValueError(
                "LLM client identity is registered under multiple aliases: "
                + ", ".join(sorted(aliases))
            )

        model_name = getattr(llm_client, "model_name", None)
        if (
            isinstance(model_name, str)
            and self.llm_clients.get(model_name) is llm_client
        ):
            return model_name
        raise ValueError(
            "LLM client has no stable registered alias. Call "
            "register_llm_client(alias, client) before persistence."
        )

    def resolve_runtime_model_alias(self, llm_client: Any) -> str:
        """Resolves operational budgets without making an alias persistable."""
        try:
            return self.resolve_model_alias(llm_client)
        except ValueError:
            if llm_client is getattr(self.root_ai, "llm_client", None):
                return "default"
            return "unregistered"

    async def handle_failover(self, agent: Agent, team: AgentTeam, error: TokenLimitExceededError) -> bool:
        """
        Handles client failover for an agent when a token limit is reached.
        Returns True if hot-swap succeeded and caller should retry.
        """
        old_model = self.resolve_runtime_model_alias(agent.llm_client)
        policy = self.config.failover_policy

        def has_binding(alias: str) -> bool:
            if alias in self.llm_clients:
                return True
            if alias in self.model_configs and self.generator_handler:
                return True
            if alias == "default":
                return bool(
                    self.generator_handler
                    or getattr(self.root_ai, "llm_client", None)
                )
            return False
        
        parent_team = team.parent_team or self.find_parent_team(team)

        candidates = []
        required_tokens = max(1, getattr(error, "required_tokens", 1))
        for name in self.config.model_token_limits.keys():
            if name == old_model:
                continue
            if not has_binding(name):
                continue
            available = self.token_budget.available(name)
            if available is not None and available >= required_tokens:
                candidates.append(name)
        if (
            "default" not in self.config.model_token_limits
            and "default" not in candidates
            and old_model != "default"
            and has_binding("default")
        ):
            candidates.append("default")

        selected_model = None

        if policy == "auto":
            if candidates:
                selected_model = candidates[0]
            else:
                self.logger.error(f"Failover failed: No candidate models with remaining budget found.")
                return False
                
        elif policy == "parent":
            from .communication import ApprovalPrincipal

            if not candidates:
                self.logger.error(
                    "Parent-governed failover has no eligible model candidates."
                )
                return False
            principal = (
                ApprovalPrincipal(
                    kind="agent_team", principal_id=parent_team.team_id
                )
                if parent_team is not None
                else ApprovalPrincipal(
                    kind="agent", principal_id=self.root_ai.agent_id
                )
            )
            if principal.kind == "agent" and principal.principal_id == agent.agent_id:
                self.logger.error(
                    "Parent-governed failover cannot re-enter the failing Agent."
                )
                return False
            if principal.kind == "agent_team" and any(
                member.agent_id == agent.agent_id
                for member in parent_team.members
            ):
                self.logger.error(
                    "Parent-governed failover cannot re-enter the failing Agent "
                    "through a shared parent AgentTeam membership."
                )
                return False
            prompt = (
                "Select a replacement model for an Agent whose token budget is "
                "exhausted.\n\n"
                f"Child AgentTeam: {team.team_id}\n"
                f"Agent: {agent.name} ({agent.role})\n"
                f"Exhausted model: {old_model}\n"
                f"Required tokens: {required_tokens}\n"
            )
            try:
                if principal.kind == "agent":
                    decision = await asyncio.wait_for(
                        self.broker.decision_provider.decide_agent_model(
                            principal, prompt, candidates
                        ),
                        timeout=self.config.parent_failover_timeout_seconds,
                    )
                else:
                    decision = await asyncio.wait_for(
                        self.broker.decision_provider.decide_team_model(
                            principal, prompt, candidates
                        ),
                        timeout=self.config.parent_failover_timeout_seconds,
                    )
            except asyncio.TimeoutError:
                self.logger.error(
                    "Parent-governed failover did not complete before timeout."
                )
                return False
            except Exception as exc:
                self.logger.error(
                    "Parent-governed failover failed closed: %s", exc
                )
                return False
            if decision.status != "approved" or decision.selected_value not in candidates:
                self.logger.error(
                    "Parent-governed failover failed closed: %s",
                    decision.reason,
                )
                return False
            selected_model = decision.selected_value

        if not selected_model:
            self.logger.error("No failover model selected.")
            return False

        new_client = None
        if selected_model in self.llm_clients:
            new_client = self.llm_clients[selected_model]
        elif selected_model in self.model_configs and self.generator_handler:
            new_client = HandlerClientAdapter(selected_model, self.generator_handler)
            config = self.model_configs.get(selected_model)
            if config:
                new_client._supports_native = config.get("supports_native_tool_calling", False)
        elif selected_model == "default" and has_binding("default"):
            new_client = ManagerDefaultClientAdapter(self)
        else:
            self.logger.error(
                "Failover model %r has no runtime binding.", selected_model
            )
            return False
            
        agent.llm_client = new_client
        
        agent_status = f"Failover: Switched to {selected_model}"
        team.set_status(agent.name, agent_status)
        self._emit_callback("on_status_change", agent.name, agent_status)

        if self.on_log_append:
            log_title = f"[SYSTEM ALERT] Model Failover Event | {agent.name}"
            log_content = (
                f"AGENT: {agent.name}\n"
                f"ROLE: {agent.role}\n"
                f"TEAM: {team.team_id}\n"
                f"FAILOVER POLICY: {policy}\n"
                f"ACTION: Switched client from Model '{old_model}' to Model '{selected_model}' due to budget exhaustion ({error})."
            )
            self._emit_callback(
                "on_log_append",
                team.team_id,
                log_title,
                log_content,
                team.chapter_num,
            )

        self._emit_callback("on_system_event", "model_failover", {
            "agent_name": agent.name,
            "team_id": team.team_id,
            "old_model": old_model,
            "new_model": selected_model,
            "reason": str(error),
        })
                
        self.logger.warning(f"[FAILOVER SUCCESS] Switched Agent '{agent.name}' from Model '{old_model}' to Model '{selected_model}'. Retrying turn.")
        return True


    def register_preset(self, name: str, description: str, system_instructions: str, roles: List[Tuple[str, str]]):
        """Registers a custom dynamic committee preset."""
        self.presets[name] = {
            "description": description,
            "system_instructions": system_instructions,
            "roles": roles
        }
        self._auto_save(configs=True)

    def get_preset(self, name: str) -> dict:
        return self.presets.get(name, self.presets["generic"])

    def register_tools_context(self, context: Dict[str, Any]):
        """Registers system dependencies/resources context for binding tools to AIs."""
        safe_context = dict(context)
        safe_context.pop("att_manager", None)
        self.tools_context.update(safe_context)
        self.tools_context["att_manager"] = self
        from ai_team_team.tool import get_default_tools
        # Bind generic tools to existing teams
        for team in self.teams.values():
            team.tools.update(get_default_tools(self.tools_context, team))
            # Also bind globally registered tools
            team.tools.update(self.global_tools)

    def get_available_tools(
        self, team: AgentTeam, agent: Optional[Agent] = None
    ) -> Dict[str, Any]:
        """Returns the invocation-time tool view for one AgentTeam."""
        tools = dict(getattr(team, "tools", {}) or {})
        if (
            not self.config.enable_dynamic_delegation
            or team.depth >= self.config.max_delegation_depth
        ):
            tools.pop("dispatch_subagent", None)
        if team.parent_team is None and self.find_parent_team(team) is None:
            tools.pop("delegate_escalation", None)
        if not self.config.enable_membership_voting:
            for name in {
                "initiate_membership_vote",
                "cast_vote",
                "retract_membership_vote",
            }:
                tools.pop(name, None)
        return tools

    def probe_native_tool_capability(
        self,
        client: Any,
        *,
        agent: Optional[Agent] = None,
        team: Optional[AgentTeam] = None,
    ) -> bool:
        """Safely probes a synchronous native-tool capability contract."""
        probe = getattr(client, "supports_native_tool_calling", None)
        if not callable(probe):
            return False
        try:
            result = probe()
            if inspect.isawaitable(result):
                close = getattr(result, "close", None)
                if callable(close):
                    close()
                raise TypeError(
                    "supports_native_tool_calling() must be synchronous."
                )
            if result is True:
                return True
            if result is False:
                return False
            raise TypeError(
                "supports_native_tool_calling() must return a literal boolean."
            )
        except Exception as exc:
            payload = {
                "agent_id": agent.agent_id if agent else None,
                "team_id": team.team_id if team else None,
                "error_type": type(exc).__name__,
            }
            self.logger.info(
                "Native tool capability probe failed for Agent %s: %s",
                payload["agent_id"],
                exc,
            )
            self._emit_callback(
                "on_system_event", "tool_capability_probe_failed", payload
            )
            return False

    def unique_agent_name(self, base_name: str, team: AgentTeam) -> str:
        """Returns a registry-safe agent name for a team."""
        if base_name not in self.agents:
            return base_name
        suffix = team.team_id.split("-", 1)[-1]
        candidate = f"{base_name}_{suffix}"
        counter = 2
        while candidate in self.agents:
            candidate = f"{base_name}_{suffix}_{counter}"
            counter += 1
        return candidate

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
        is_public_visible: bool = False,
        initial_docs: Optional[Dict[str, str]] = None,
    ) -> AgentTeam:
        """Stages off-registry objects and atomically publishes one AgentTeam."""
        if self._closing:
            raise RuntimeError("ATTManager is closing and rejects new teams.")
        self._validate_team_creation_inputs(
            creator=creator,
            member_count=member_count,
            roles_and_presets=roles_and_presets,
            roles_and_models=roles_and_models,
            member_configs=member_configs,
            initial_docs=initial_docs,
            preset_name=preset_name,
            system_instructions=system_instructions,
            team_purpose=team_purpose,
            is_public_visible=is_public_visible,
        )
        managed_root = os.path.join(
            os.path.realpath(os.path.abspath(self.config.workspace_root)),
            ".att_doc_libs",
        )
        if os.path.lexists(managed_root) and os.path.islink(managed_root):
            raise PermissionError("The managed DocLib root cannot be a symlink.")
        os.makedirs(managed_root, exist_ok=True)
        staging_root = tempfile.mkdtemp(
            prefix=".att-team-stage-", dir=managed_root
        )
        published: List[Tuple[str, Optional[str]]] = []
        snapshot: Optional[Dict[str, Any]] = None
        stage: Optional[Dict[str, Any]] = None
        try:
            stage = self._create_agent_team(
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
                staging_root=staging_root,
            )
            with self._topology_lock:
                self._validate_team_creation_commit(stage)
                snapshot = self._team_creation_snapshot()
                published = self._publish_new_staged_libraries(
                    stage["libraries"], managed_root
                )
                self.libraries.update(stage["libraries"])
                self._library_files.update(stage["library_files"])
                for agent in stage["new_agents"]:
                    self.register_agent(agent, auto_save=False)
                for agent, role, _original_role in stage["role_updates"]:
                    agent.role = role
                team = stage["team"]
                self.teams[team.team_id] = team
                parent = stage["parent"]
                if parent is not None:
                    self._team_parent_map[team.team_id] = parent.team_id
                    parent.add_child_team(team)
            self._discard_library_backups(published)
        except Exception:
            if stage is not None:
                for agent, _role, original_role in stage["role_updates"]:
                    agent.role = original_role
            if published:
                self._rollback_published_libraries(published)
            if snapshot is not None:
                with self._topology_lock:
                    self._rollback_team_creation(snapshot)
            raise
        finally:
            shutil.rmtree(staging_root, ignore_errors=True)

        self.logger.info(
            "Successfully spawned AgentTeam %s with %s members.",
            team.team_id,
            len(team.members),
        )
        self._auto_save(
            configs=True,
            agents={agent.agent_id for agent in stage["registered_agents"]},
            teams={team.team_id}
            | ({team.parent_team.team_id} if team.parent_team else set()),
            libraries=set(stage["libraries"])
            | {
                agent.private_doc_library_id
                for agent in stage["registered_agents"]
                if agent.private_doc_library_id
            },
        )
        return team

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
        if not isinstance(creator, (Agent, AgentTeam)):
            raise TypeError("creator must be an Agent or AgentTeam.")
        if isinstance(creator, AgentTeam) and self.teams.get(creator.team_id) is not creator:
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
            or effective_count < self.config.min_subagent_team_size
        ):
            raise ValueError(
                f"An AgentTeam requires at least {self.config.min_subagent_team_size} members."
            )
        available_models = set(self.llm_clients) | set(self.model_configs)
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
                or not all(
                    isinstance(value, str) and bool(value)
                    for value in item
                )
                for item in roles_and_presets
            ):
                raise TypeError(
                    "roles_and_presets must contain non-empty (name, role) string tuples."
                )
            if len(roles_and_presets) < self.config.min_subagent_team_size:
                raise ValueError(
                    f"roles_and_presets must define at least {self.config.min_subagent_team_size} members."
                )
        for role, config in (member_configs or {}).items():
            if not isinstance(role, str) or not role:
                raise ValueError("Member role names must be non-empty strings.")
            if isinstance(config, Agent):
                continue
            if not isinstance(config, dict):
                raise TypeError(
                    f"Member configuration for {role!r} must be a mapping or Agent."
                )
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
            if hired is not None and hired not in self.agents:
                raise ValueError(f"Agent {hired!r} is not registered.")
            alias = config.get("model")
            if (
                alias
                and alias != "default"
                and alias not in available_models
                and alias not in self.agents
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
                    raise ValueError(
                        f"Invalid initial document path {path!r}."
                    ) from exc
                if not isinstance(content, str):
                    raise TypeError(
                        f"Initial document content for {path!r} must be a string."
                    )

    def _team_creation_snapshot(self) -> Dict[str, Any]:
        return {
            "agents": dict(self.agents),
            "agents_by_id": dict(self._agents_by_id),
            "teams": dict(self.teams),
            "libraries": dict(self.libraries),
            "library_files": dict(self._library_files),
            "parent_map": dict(self._team_parent_map),
            "children": {
                team_id: list(team.child_teams)
                for team_id, team in self.teams.items()
            },
            "private_ids": {
                id(agent): agent.private_doc_library_id
                for agent in self._agents_by_id.values()
            },
            "agent_fields": {
                id(agent): {
                    "role": agent.role,
                    "role_description": agent.role_description,
                    "system_instructions": agent.system_instructions,
                }
                for agent in self._agents_by_id.values()
            },
        }

    def _rollback_team_creation(self, snapshot: Dict[str, Any]) -> None:
        prior_library_ids = set(snapshot["libraries"])
        for lib_id, library in list(self.libraries.items()):
            if lib_id not in prior_library_ids:
                shutil.rmtree(library.root_dir, ignore_errors=True)
        for agent in self._agents_by_id.values():
            if id(agent) not in snapshot["private_ids"]:
                agent._private_doc_library_id = None
            elif id(agent) in snapshot["agent_fields"]:
                fields = snapshot["agent_fields"][id(agent)]
                agent.role = fields["role"]
                agent.role_description = fields["role_description"]
                agent.system_instructions = fields["system_instructions"]
        self.agents = snapshot["agents"]
        self._agents_by_id = snapshot["agents_by_id"]
        self.teams = snapshot["teams"]
        self.libraries = snapshot["libraries"]
        self._library_files = snapshot["library_files"]
        self._team_parent_map = snapshot["parent_map"]
        for team_id, children in snapshot["children"].items():
            self.teams[team_id].child_teams = children

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
        if member_configs:
            member_count = len(member_configs)
        team = AgentTeam(
            creator=creator,
            preset_name=preset_name,
            team_purpose=team_purpose,
        )
        team.manager = self
        parent = (
            creator
            if isinstance(creator, AgentTeam)
            else self.get_agent_team(creator)
        )
        team._parent_team = parent
        if isinstance(creator, AgentTeam):
            team.chapter_num = creator.chapter_num
        elif parent is not None:
            team.chapter_num = parent.chapter_num

        def client_by_alias(alias: Optional[str]) -> Any:
            if alias and alias != "default":
                if alias in self.llm_clients:
                    return self.llm_clients[alias]
                if alias in self.model_configs and self.generator_handler:
                    adapter = HandlerClientAdapter(
                        alias, self.generator_handler
                    )
                    adapter._supports_native = (
                        self.model_configs.get(alias, {}).get(
                            "supports_native_tool_calling"
                        )
                        is True
                    )
                    return adapter
                raise ValueError(f"Model {alias!r} is not registered.")
            if "default" in self.llm_clients:
                return self.llm_clients["default"]
            if self.root_ai.llm_client:
                return self.root_ai.llm_client
            return ManagerDefaultClientAdapter(self)

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
                elif config.get("hire_agent") in self.agents:
                    agent = self.agents[config["hire_agent"]]
                elif config.get("model") in self.agents:
                    agent = self.agents[config["model"]]
                else:
                    agent = Agent(
                        name=(
                            f"Dynamic_{role_name}_"
                            f"{team.team_id.split('-', 1)[1]}"
                        ),
                        role=role_name,
                        llm_client=client_by_alias(config.get("model")),
                        role_description=config.get("role_description", ""),
                        system_instructions=config.get(
                            "system_instructions", ""
                        ),
                    )
                members.append(agent)
        elif roles_and_presets:
            for name, role in roles_and_presets:
                members.append(
                    Agent(
                        name=self.unique_agent_name(name, team),
                        role=role,
                        llm_client=client_for_role(role, name),
                    )
                )
        else:
            roles = self.get_preset(preset_name).get("roles", [])
            if len(roles) >= member_count:
                for name, role in roles[:member_count]:
                    members.append(
                        Agent(
                            name=self.unique_agent_name(name, team),
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
        team.system_instructions = (
            system_instructions
            or self.get_preset(preset_name).get("system_instructions", "")
        )

        from ai_team_team.tool import get_default_tools

        team.tools.update(get_default_tools(self.tools_context, team))
        team.tools.update(self.global_tools)

        registered_agents: List[Agent] = []
        for agent in [creator, *members]:
            if not isinstance(agent, Agent):
                continue
            if all(existing is not agent for existing in registered_agents):
                registered_agents.append(agent)
        new_agents = [
            agent
            for agent in registered_agents
            if self._agents_by_id.get(agent.agent_id) is not agent
        ]

        libraries: Dict[str, DocumentLibrary] = {}
        library_files: Dict[str, Dict[str, str]] = {}
        for agent in new_agents:
            expected_id = f"PDL-{agent.agent_id}"
            if (
                agent.private_doc_library_id is not None
                and agent.private_doc_library_id != expected_id
            ):
                raise ValueError(
                    f"Private DocLib ID must be {expected_id!r}."
                )
            if expected_id in self.libraries:
                raise ValueError(
                    f"Private DocLib {expected_id!r} is already registered."
                )
            library = self._build_document_library(
                lib_id=expected_id,
                name=f"{agent.name} Private Library",
                owner_agent_id=agent.agent_id,
                library_kind="agent_private",
                lifecycle_state="active",
                description=(
                    f"Persistent private workspace for agent {agent.name}."
                ),
                is_public_visible=False,
                storage_dir=os.path.join(staging_root, expected_id),
            )
            libraries[expected_id] = library
            library_files[expected_id] = {}

        team_lib_id = f"DL-{team.team_id}"
        team_library = self._build_document_library(
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

    def _validate_team_creation_commit(
        self, stage: Dict[str, Any]
    ) -> None:
        """Revalidates all live references immediately before publication."""
        if self._closing:
            raise RuntimeError("ATTManager is closing and rejects new teams.")
        team = stage["team"]
        creator = team.creator
        if isinstance(creator, AgentTeam):
            if self.teams.get(creator.team_id) is not creator:
                raise ValueError(
                    "The creator AgentTeam changed during team staging."
                )
            current_parent = creator
        else:
            if creator.lifecycle_state != "active":
                raise ValueError("The creator Agent is no longer active.")
            current_parent = self.get_agent_team(creator)
        if current_parent is not stage["parent"]:
            raise ValueError(
                "The proposed parent changed during team staging."
            )
        if team.team_id in self.teams:
            raise ValueError(f"AgentTeam ID {team.team_id!r} is already registered.")
        for lib_id in stage["libraries"]:
            if lib_id in self.libraries:
                raise ValueError(
                    f"Document library {lib_id!r} is already registered."
                )
        for agent in stage["new_agents"]:
            existing_id = self._agents_by_id.get(agent.agent_id)
            existing_name = self.agents.get(agent.name)
            if existing_id is not None or existing_name is not None:
                raise ValueError(
                    f"Agent identity {agent.name!r} changed during team staging."
                )

    def find_parent_team(self, target: AgentTeam) -> Optional[AgentTeam]:
        if target._parent_team is not None:
            return target._parent_team

        # Fast O(1) hash map lookup
        parent_id = self._team_parent_map.get(target.team_id)
        if parent_id and parent_id in self.teams:
            target._parent_team = self.teams[parent_id]
            return target._parent_team

        # Fallback for dynamic creators during bootstrap
        if isinstance(target.creator, AgentTeam):
            target._parent_team = target.creator
            self._team_parent_map[target.team_id] = target.creator.team_id
            return target.creator
            
        if hasattr(target.creator, "name"):
            # Creator is an Agent
            parent = self.get_agent_team(target.creator)
            if parent:
                target._parent_team = parent
                self._team_parent_map[target.team_id] = parent.team_id
                return parent

        return None
        
    def get_agent_team(self, agent: Agent) -> Optional[AgentTeam]:
        active_team = self._active_team.get()
        if active_team is not None and agent in active_team.members:
            return active_team
        memberships = [
            team for team in self.teams.values() if agent in team.members
        ]
        if len(memberships) == 1:
            return memberships[0]
        if len(memberships) > 1:
            raise AmbiguousTeamContextError(
                f"Agent {agent.name!r} belongs to multiple teams and no "
                "invocation-scoped team context is active: "
                + ", ".join(sorted(team.team_id for team in memberships))
            )
        return None

    @staticmethod
    def _agent_history(agent: Agent) -> List[Dict[str, Any]]:
        agent.sync_message_history()
        return agent.message_history
        
    def check_library_access(self, team_id: str, lib_id: str, path: str, required_permission: str) -> bool:
        """
        Checks if a team has the required permission ('READ' or 'WRITE') for a path in a DocLib.
        Owner of the library always has 'WRITE' (which includes 'READ') for all paths.
        """
        if lib_id not in self.libraries:
            return False
        try:
            clean_path = self.normalize_library_path(path)
        except PermissionError:
            return False
        lib = self.libraries[lib_id]
        if lib.library_kind != "team":
            return False
        if lib.owner_team_id == team_id:
            return True
            
        # Check explicit permissions
        if lib_id not in self.library_permissions:
            return False
            
        # Find prefix/parent path matches.
        if clean_path == "/":
            parts = ["/"]
        else:
            parts = []
            current = clean_path
            while current and current != "/":
                parts.append(current)
                current = os.path.dirname(current)
            parts.append("/")
            
        # Check permissions for each segment
        for p in parts:
            if p in self.library_permissions[lib_id]:
                team_perms = self.library_permissions[lib_id][p]
                if team_id in team_perms:
                    perm = team_perms[team_id]
                    if required_permission == "READ":
                        if perm in {"READ", "WRITE"}:
                            return True
                    elif required_permission == "WRITE":
                        if perm == "WRITE":
                            return True
        return False

    @staticmethod
    def normalize_library_path(path: str) -> str:
        """Returns one canonical virtual ACL path or raises on traversal."""
        if not isinstance(path, str) or not path.strip():
            raise PermissionError(
                "Access denied: Empty library paths are not allowed."
            )
        normalized = DocumentLibrary._normalize_path(path, allow_root=True)
        return "/" if not normalized else f"/{normalized}"

    @staticmethod
    def _normalize_library_file_path(path: str) -> str:
        return DocumentLibrary._normalize_path(path, allow_root=False)

    def _resolve_library_target(
        self,
        team_id: str,
        lib_id: str,
        path: str,
        required_permission: str,
        *,
        initial_visited: Optional[set[Tuple[str, str]]] = None,
    ) -> Tuple[DocumentLibrary, str]:
        """Resolves a managed file-link chain with live ACL checks."""
        current_lib_id = lib_id
        current_path = self._normalize_library_file_path(path)
        visited = set(initial_visited or set())
        while True:
            node = (current_lib_id, current_path)
            if node in visited:
                raise ValueError("Managed DocLib link cycle detected.")
            visited.add(node)
            if current_lib_id not in self.libraries:
                raise FileNotFoundError(
                    f"Document library '{current_lib_id}' not found."
                )
            if not self.check_library_access(
                team_id,
                current_lib_id,
                current_path,
                required_permission,
            ):
                raise PermissionError(
                    f"Permission denied for {required_permission} on "
                    f"'{current_lib_id}:{current_path}'."
                )
            target = self.library_links.get(current_lib_id, {}).get(
                current_path
            )
            if target is None:
                return self.libraries[current_lib_id], current_path
            current_lib_id = target["target_lib_id"]
            current_path = self._normalize_library_file_path(
                target["target_path"]
            )

    async def create_library_link(
        self,
        team_id: str,
        source_lib_id: str,
        source_path: str,
        target_lib_id: str,
        target_path: str,
    ) -> None:
        """Creates one ACL-aware cross-library file link."""
        if source_lib_id == target_lib_id:
            raise ValueError("Managed links must target another DocLib.")
        source_path = self._normalize_library_file_path(source_path)
        target_path = self._normalize_library_file_path(target_path)
        if source_lib_id not in self.libraries or target_lib_id not in self.libraries:
            raise FileNotFoundError("Both source and target DocLibs must be registered.")
        if (
            self.libraries[source_lib_id].library_kind != "team"
            or self.libraries[target_lib_id].library_kind != "team"
        ):
            raise PermissionError("Private DocLibs cannot participate in links.")
        if not self.check_library_access(
            team_id, source_lib_id, source_path, "WRITE"
        ):
            raise PermissionError(
                "WRITE permission is required for the link path."
            )
        if source_path in self.library_links.get(source_lib_id, {}):
            raise FileExistsError("A managed link already exists at that path.")
        if await asyncio.to_thread(
            self.libraries[source_lib_id].path_exists, source_path
        ):
            raise FileExistsError("A physical file already exists at that path.")

        target_library, resolved_target = self._resolve_library_target(
            team_id,
            target_lib_id,
            target_path,
            "READ",
            initial_visited={(source_lib_id, source_path)},
        )
        if not await asyncio.to_thread(
            target_library.is_file, resolved_target
        ):
            raise FileNotFoundError(
                "Managed links may target existing files only."
            )
        with self._snapshot_lock:
            self.library_links.setdefault(source_lib_id, {})[source_path] = {
                "target_lib_id": target_lib_id,
                "target_path": target_path,
            }
            self._auto_save(links={source_lib_id})

    async def read_library_file(
        self,
        team_id: str,
        lib_id: str,
        path: str,
        start_line: int = 1,
        end_line: Optional[int] = None,
    ) -> str:
        library, resolved_path = self._resolve_library_target(
            team_id, lib_id, path, "READ"
        )
        return await asyncio.to_thread(
            library.read_file, resolved_path, start_line, end_line
        )

    async def write_library_file(
        self,
        team_id: str,
        lib_id: str,
        path: str,
        content: str,
    ) -> None:
        library, resolved_path = self._resolve_library_target(
            team_id, lib_id, path, "WRITE"
        )
        await asyncio.to_thread(library.write_file, resolved_path, content)

    async def delete_library_path(
        self, team_id: str, lib_id: str, path: str
    ) -> str:
        clean_path = self._normalize_library_file_path(path)
        if not self.check_library_access(team_id, lib_id, clean_path, "WRITE"):
            raise PermissionError(
                f"Permission denied for WRITE on '{lib_id}:{clean_path}'."
            )
        with self._snapshot_lock:
            link_map = self.library_links.get(lib_id, {})
            if clean_path in link_map:
                del link_map[clean_path]
                self._auto_save(links={lib_id})
                return (
                    f"Successfully deleted managed link '{path}' in "
                    f"library '{lib_id}'."
                )
        return await asyncio.to_thread(
            self.libraries[lib_id].delete_file, clean_path
        )

    async def list_library_contents(
        self, team_id: str, lib_id: str, path: str = "/"
    ) -> List[str]:
        clean_acl_path = self.normalize_library_path(path)
        if not self.check_library_access(
            team_id, lib_id, clean_acl_path, "READ"
        ):
            raise PermissionError(
                f"Permission denied for READ on '{lib_id}:{path}'."
            )
        clean_dir = "" if clean_acl_path == "/" else clean_acl_path.lstrip("/")
        if clean_dir in self.library_links.get(lib_id, {}):
            raise NotADirectoryError("Managed links are file links only.")
        items = await asyncio.to_thread(
            self.libraries[lib_id].list_contents, path
        )
        for source_path, target in self.library_links.get(lib_id, {}).items():
            if os.path.dirname(source_path) != clean_dir:
                continue
            try:
                target_library, target_path = self._resolve_library_target(
                    team_id, lib_id, source_path, "READ"
                )
                if not await asyncio.to_thread(
                    target_library.is_file, target_path
                ):
                    continue
            except (FileNotFoundError, PermissionError, ValueError):
                continue
            items.append(
                f"[LINK] /{source_path} -> "
                f"{target['target_lib_id']}:{target['target_path']}"
            )
        return sorted(items)

    async def list_private_files(self, path: str = "/") -> List[str]:
        """Lists the current invocation agent's private workspace."""
        _, library = self._require_private_agent_context()
        return await asyncio.to_thread(library.list_contents, path)

    async def read_private_file(
        self,
        path: str,
        start_line: int = 1,
        end_line: Optional[int] = None,
    ) -> str:
        """Reads private content only for the current invocation agent."""
        _, library = self._require_private_agent_context()
        return await asyncio.to_thread(
            library.read_file, path, start_line, end_line
        )

    async def write_private_file(self, path: str, content: str) -> None:
        """Writes private content only for the current invocation agent."""
        _, library = self._require_private_agent_context()
        await asyncio.to_thread(library.write_file, path, content)

    async def delete_private_file(self, path: str) -> str:
        """Deletes private content only for the current invocation agent."""
        _, library = self._require_private_agent_context()
        return await asyncio.to_thread(library.delete_file, path)

    async def move_private_file(
        self,
        source_path: str,
        target_path: str,
        overwrite: bool = False,
    ) -> None:
        """Atomically moves a private file within its owner's workspace."""
        _, library = self._require_private_agent_context()
        async with self.suppress_auto_save():
            await asyncio.to_thread(
                library.move_file, source_path, target_path, overwrite
            )

    async def publish_private_file(
        self,
        source_path: str,
        target_path: str,
        overwrite: bool = False,
    ) -> None:
        """Copies one private file to the active team's built-in DocLib."""
        agent, private_library = self._require_private_agent_context()
        team = self._active_team.get()
        if team is None or agent not in team.members:
            raise PermissionError(
                "Publishing requires an active team containing the current agent."
            )
        target_library = team.doc_library
        expected_library = self.libraries.get(f"DL-{team.team_id}")
        if (
            self.teams.get(team.team_id) is not team
            or target_library is None
            or target_library is not expected_library
            or target_library.library_kind != "team"
            or target_library.owner_team_id != team.team_id
        ):
            raise RuntimeError("The active team has no built-in DocLib.")
        clean_source = self._normalize_library_file_path(source_path)
        clean_target = self._normalize_library_file_path(target_path)
        if not self.check_library_access(
            team.team_id, target_library.lib_id, clean_target, "WRITE"
        ):
            raise PermissionError("WRITE permission is required on the target path.")
        if clean_target in self.library_links.get(target_library.lib_id, {}):
            raise FileExistsError(
                "The target path is a managed link and cannot be overwritten."
            )

        def copy_under_locks() -> None:
            ordered = sorted(
                (private_library, target_library), key=lambda item: item.lib_id
            )
            with ordered[0]._lock:
                with ordered[1]._lock:
                    if not private_library.is_file(clean_source):
                        raise FileNotFoundError(
                            f"Private file {source_path!r} does not exist."
                        )
                    content = private_library.read_text(clean_source)
                    target_library.write_file_atomic(
                        clean_target, content, overwrite=overwrite
                    )

        await asyncio.to_thread(copy_under_locks)
        self._emit_callback(
            "on_system_event",
            "private_library_published",
            {
                "agent_id": agent.agent_id,
                "team_id": team.team_id,
                "source_library_id": private_library.lib_id,
                "source_path": clean_source,
                "target_library_id": target_library.lib_id,
                "target_path": clean_target,
                "operation": "copy",
                "result": "success",
            },
        )

    async def move_library_file(
        self,
        team_id: str,
        lib_id: str,
        source_path: str,
        target_path: str,
        overwrite: bool = False,
    ) -> None:
        """Moves a team-library file after checking both ACL paths."""
        if lib_id not in self.libraries:
            raise FileNotFoundError(f"Document library {lib_id!r} not found.")
        library = self.libraries[lib_id]
        if library.library_kind != "team":
            raise PermissionError("Private DocLibs require private tools.")
        clean_source = self._normalize_library_file_path(source_path)
        clean_target = self._normalize_library_file_path(target_path)
        if not self.check_library_access(team_id, lib_id, clean_source, "WRITE"):
            raise PermissionError("WRITE permission is required on the source path.")
        if not self.check_library_access(team_id, lib_id, clean_target, "WRITE"):
            raise PermissionError("WRITE permission is required on the target path.")
        links = self.library_links.get(lib_id, {})
        if clean_source in links or clean_target in links:
            raise FileExistsError("Managed-link paths cannot be moved or overwritten.")
        async with self.suppress_auto_save():
            await asyncio.to_thread(
                library.move_file, clean_source, clean_target, overwrite
            )


    def render_topology_tree(self) -> str:
        """Renders the active hierarchical agent team lineage as an indented tree."""
        lines = [f"- [Root AI: {self.root_ai.name}] (Level 0)"]
        
        level_1_teams = []
        for team in self.teams.values():
            if team.parent_team is None:
                level_1_teams.append(team)
                
        def traverse(team, depth=1, is_last=True):
            indent = "  " * depth
            prefix = "└── " if is_last else "├── "
            lines.append(f"{indent}{prefix}{team.team_id} (Purpose: {team.team_purpose} | Progress: {team.team_progress}) [Level {team.depth}]")
            children = team.child_teams
            for i, child in enumerate(children):
                traverse(child, depth + 1, is_last=(i == len(children) - 1))
                
        for i, t in enumerate(level_1_teams):
            traverse(t, 1, is_last=(i == len(level_1_teams) - 1))
            
        return "\n".join(lines)

    async def negotiate_and_execute_migration(self, team: AgentTeam, target_parent: AgentTeam, rationale: str) -> Tuple[bool, str]:
        """Arbitrates the migration of an AgentTeam using the critic LLM client, updates structure, and broadcasts alerts."""
        from .policies import (
            migration_approval_principals,
            resolve_migration_policy,
        )

        limit = self.config.max_migrations_per_team_discussion
        policy_name = getattr(self.config, "migration_policy", "ancestor_approval")
        policy = resolve_migration_policy(policy_name)
        with self._topology_lock:
            if self.teams.get(team.team_id) is not team:
                return False, "Rejected: Migrating AgentTeam is not registered."
            if self.teams.get(target_parent.team_id) is not target_parent:
                return False, "Rejected: Target parent AgentTeam is not registered."
            current_count = getattr(team, "migration_count", 0)
            if current_count >= limit:
                return False, f"Rejected: Cannot request migration. Maximum migrations per discussion session ({limit}) reached."
            initial_parent = team.parent_team
            if initial_parent is not None and team not in initial_parent.child_teams:
                return False, "Rejected: Current parent/child topology is inconsistent."
            cursor = target_parent
            while cursor is not None:
                if cursor is team:
                    return False, "Rejected: Target parent is a descendant of the migrating AgentTeam."
                cursor = cursor.parent_team
            approved_principal_keys = tuple(
                principal.key
                for principal in migration_approval_principals(
                    policy_name, team, target_parent, self
                )
            )
            current_parent_id = (
                initial_parent.team_id if initial_parent else "Root AI"
            )
        
        try:
            approved, reason = await policy.authorize_migration(team, target_parent, self, rationale)
            
            if approved:
                with self._topology_lock:
                    if self.teams.get(team.team_id) is not team:
                        return False, (
                            "Rejected: Migrating AgentTeam was unregistered "
                            "while authorization was pending."
                        )
                    if self.teams.get(target_parent.team_id) is not target_parent:
                        return False, (
                            "Rejected: Target parent AgentTeam was unregistered "
                            "while authorization was pending."
                        )
                    current_parent = team.parent_team
                    current_count = team.migration_count
                    if current_parent is not initial_parent:
                        return False, (
                            "Rejected: Current parent changed while authorization "
                            "was pending."
                        )
                    if (
                        current_parent is not None
                        and team not in current_parent.child_teams
                    ):
                        return False, (
                            "Rejected: Current parent/child topology became "
                            "inconsistent while authorization was pending."
                        )
                    if current_count >= limit:
                        return False, (
                            "Rejected: Migration limit was reached while "
                            "authorization was pending."
                        )

                    cursor = target_parent
                    while cursor is not None:
                        if cursor is team:
                            return False, (
                                "Rejected: Target parent became a descendant "
                                "while authorization was pending."
                            )
                        cursor = cursor.parent_team

                    current_principal_keys = tuple(
                        principal.key
                        for principal in migration_approval_principals(
                            policy_name, team, target_parent, self
                        )
                    )
                    if current_principal_keys != approved_principal_keys:
                        return False, (
                            "Rejected: The migration approval path changed "
                            "while authorization was pending."
                        )

                    if current_parent and team in current_parent.child_teams:
                        current_parent.child_teams.remove(team)
                    target_parent.add_child_team(team)
                    team._parent_team = target_parent
                    self._team_parent_map[team.team_id] = target_parent.team_id
                    team.migration_count = current_count + 1
                    team.invalidate_depth_cache(recursive=True)
                
                # 2. Dispatch notifications
                if current_parent:
                    current_parent.receive_message({
                        "from": "System/Migration",
                        "type": "migration_alert",
                        "reason": f"Child team '{team.team_id}' has migrated to parent '{target_parent.team_id}'. Rationale: {rationale}"
                    })
                target_parent.receive_message({
                    "from": "System/Migration",
                    "type": "migration_alert",
                    "reason": f"Team '{team.team_id}' has joined as your child. Rationale: {rationale}"
                })
                team.receive_message({
                    "from": "System/Migration",
                    "type": "migration_alert",
                    "reason": f"Your team has successfully migrated to parent '{target_parent.team_id}'. Arbiter Reason: {reason}"
                })
                
                # 3. Trigger callback
                self._emit_callback(
                    "on_team_migration",
                    team.team_id,
                    current_parent_id if current_parent else None,
                    target_parent.team_id,
                )
                
                self.logger.info(f"Migration of team {team.team_id} to parent {target_parent.team_id} approved. Reason: {reason}")
                affected_team_ids = {
                    team.team_id,
                    target_parent.team_id,
                }
                if current_parent:
                    affected_team_ids.add(current_parent.team_id)

                def collect_descendants(node: AgentTeam) -> None:
                    for child in node.child_teams:
                        affected_team_ids.add(child.team_id)
                        collect_descendants(child)

                collect_descendants(team)
                self._auto_save(teams=affected_team_ids)
                return True, f"Approved: {reason}"
            else:
                self.logger.info(f"Migration of team {team.team_id} to parent {target_parent.team_id} rejected. Reason: {reason}")
                return False, f"Rejected: {reason}"
                
        except Exception as e:
            self.logger.error(f"Migration arbitration error: {e}")
            return False, f"Arbitration error: {e}"

    async def _apply_deferred_membership_changes(
        self, team: AgentTeam
    ) -> None:
        """Applies each approved membership proposal at most once."""
        changed_agents: set[str] = set()
        changed = False
        membership_changed = False
        async with team.state_lock:
            for proposal in team.proposals.values():
                details = proposal.setdefault("proposed_details", {})
                if (
                    proposal.get("status") != "approved"
                    or details.get("executed") is True
                ):
                    continue

                details["executed"] = True
                changed = True
                action = proposal.get("action")
                target = proposal.get("target")
                if action == "add":
                    model_name = details.get("model")
                    if model_name and model_name != "default":
                        if model_name in self.llm_clients:
                            client = self.llm_clients[model_name]
                        elif (
                            model_name in self.model_configs
                            and self.generator_handler
                        ):
                            client = HandlerClientAdapter(
                                model_name, self.generator_handler
                            )
                            client._supports_native = (
                                self.model_configs.get(model_name, {}).get(
                                    "supports_native_tool_calling"
                                )
                                is True
                            )
                        else:
                            proposal["status"] = "rejected"
                            self.logger.warning(
                                "Deferred membership add rejected: model "
                                "%r is unavailable.",
                                model_name,
                            )
                            continue
                    else:
                        client = ManagerDefaultClientAdapter(self)

                    new_agent = Agent(
                        name=self.unique_agent_name(
                            f"Dynamic_{target}", team
                        ),
                        role=target,
                        llm_client=client,
                        role_description=details.get(
                            "role_description", ""
                        ),
                        system_instructions=details.get(
                            "system_instructions", ""
                        ),
                    )
                    if any(
                        member.name == new_agent.name
                        for member in team.members
                    ):
                        proposal["status"] = "rejected"
                        continue
                    team.members.append(new_agent)
                    self.register_agent(new_agent, auto_save=False)
                    changed_agents.add(new_agent.agent_id)
                    membership_changed = True
                    self.logger.info(
                        "Deferred execution added member %s to team %s.",
                        new_agent.name,
                        team.team_id,
                    )
                elif action == "remove":
                    if (
                        len(team.members)
                        <= self.config.min_subagent_team_size
                    ):
                        proposal["status"] = "rejected"
                        continue
                    target_agent = next(
                        (
                            member
                            for member in team.members
                            if member.name == target
                        ),
                        None,
                    )
                    if target_agent is None:
                        proposal["status"] = "rejected"
                        continue
                    team.members.remove(target_agent)
                    membership_changed = True
                    self.logger.info(
                        "Deferred execution removed member %s from team %s.",
                        target,
                        team.team_id,
                    )
                else:
                    proposal["status"] = "rejected"

        if changed:
            self._auto_save(
                agents=changed_agents,
                teams=(
                    {team.team_id} if membership_changed else set()
                ),
                proposals={team.team_id},
                libraries={
                    self._agents_by_id[agent_id].private_doc_library_id
                    for agent_id in changed_agents
                },
            )

    async def execute_team_discussion(
        self,
        team: AgentTeam,
        prompt: str,
        rounds: int = 2,
        skip_audit: bool = False,
    ) -> str:
        """Queues one discussion behind any active session for the same team."""
        result = await self.execute_team_discussion_detailed(
            team,
            prompt,
            rounds=rounds,
            skip_audit=skip_audit,
        )
        return result.transcript

    async def execute_team_discussion_detailed(
        self,
        team: AgentTeam,
        prompt: str,
        rounds: int = 2,
        skip_audit: bool = False,
    ) -> "DiscussionResult":
        """Runs one serialized discussion and returns all structured turns."""
        result, _ = await self._execute_team_discussion_with_members(
            team,
            prompt,
            rounds=rounds,
            skip_audit=skip_audit,
        )
        return result

    async def _execute_team_discussion_with_members(
        self,
        team: AgentTeam,
        prompt: str,
        rounds: int = 2,
        skip_audit: bool = False,
        require_complete: bool = False,
    ) -> Tuple[Any, List[Agent]]:
        """Runs one serialized session and captures membership after locking."""
        if self._closing:
            raise RuntimeError("ATTManager is closing and rejects new discussions.")
        if not isinstance(rounds, int) or isinstance(rounds, bool) or rounds < 1:
            raise ValueError("rounds must be a positive integer.")
        async with team.discussion_lock:
            async with self._runtime_gate:
                if self._closing:
                    raise RuntimeError(
                        "ATTManager is closing and rejects new discussions."
                    )
                is_runtime_audit = bool(
                    skip_audit and getattr(team, "_runtime_only", False)
                )
                if (
                    self.teams.get(team.team_id) is not team
                    and not is_runtime_audit
                ):
                    raise ValueError("The discussion team is not registered.")
                team.is_running = True
                member_snapshot = list(team.members)
            try:
                session_kwargs = {
                    "rounds": rounds,
                    "skip_audit": skip_audit,
                }
                if require_complete:
                    session_kwargs["require_complete"] = True
                result = await self._execute_team_discussion_session(
                    team, prompt, **session_kwargs
                )
                if isinstance(result, str):
                    from .response import (
                        AuditResult,
                        AuditStatus,
                        DiscussionResult,
                        DiscussionStatus,
                    )

                    result = DiscussionResult(
                        team_id=team.team_id,
                        discussion_id=(
                            self._active_discussion_id.get()
                            or f"DISC-{uuid.uuid4().hex}"
                        ),
                        status=DiscussionStatus.COMPLETED,
                        transcript=result,
                        rounds=[],
                        audit=AuditResult(
                            status=AuditStatus.HEALTHY,
                            reason="Compatibility session result.",
                        ),
                    )
                return result, member_snapshot
            finally:
                team.is_running = False

    async def _execute_team_discussion_session(
        self,
        team: AgentTeam,
        prompt: str,
        rounds: int = 2,
        skip_audit: bool = False,
        require_complete: bool = False,
    ) -> str:
        """Executes a multi-agent debate session inside the AT, monitored by the Supervisor."""
        with self._topology_lock:
            team.migration_count = 0
        team.is_running = True
        self.logger.info(f"Executing discussion in team {team.team_id} (rounds={rounds}, skip_audit={skip_audit})...")
        
        dialog_history = []
        last_round_answers = {}
        from .response import (
            AgentTurnResult,
            AgentTurnStatus,
            AuditResult,
            AuditStatus,
            DiscussionResult,
            DiscussionRoundResult,
            DiscussionStatus,
            OperationalStatus,
        )

        audit_result = AuditResult(
            status=AuditStatus.HEALTHY,
            reason="Audit skipped.",
        )
        discussion_token = self._active_discussion_id.set(
            f"DISC-{uuid.uuid4().hex}"
        )
        processed_unknown_fingerprints: set[str] = set()
        processed_operational_fingerprints: set[str] = set()
        processed_communication_request_ids: set[str] = set()
        processed_peer_message_ids: set[str] = set()
        communication_member_snapshot = list(team.members)
        discussion_had_member_errors = False
        discussion_succeeded = False
        structured_rounds: List[DiscussionRoundResult] = []
        
        auto_save_context = self.suppress_auto_save()
        await auto_save_context.__aenter__()
        try:
            for r in range(1, rounds + 1):
                inbox_context = ""
                with team.inbox_lock:
                    pending_inbox = []
                    retained_inbox = []
                    for message in team.message_inbox:
                        if (
                            message.get("type")
                            == "audit_unknown_escalation"
                        ):
                            if message.get("state", "pending") == "pending":
                                message["state"] = "processing"
                                message["processing_count"] = message.get(
                                    "occurrence_count", 1
                                )
                                pending_inbox.append(message)
                                processed_unknown_fingerprints.add(
                                    message["fingerprint"]
                                )
                            retained_inbox.append(message)
                        elif (
                            message.get("type")
                            == "operational_degraded_escalation"
                        ):
                            if message.get("state", "pending") == "pending":
                                message["state"] = "processing"
                                message["processing_count"] = message.get(
                                    "occurrence_count", 1
                                )
                                pending_inbox.append(message)
                                processed_operational_fingerprints.add(
                                    message["fingerprint"]
                                )
                            retained_inbox.append(message)
                        elif (
                            message.get("type")
                            == "communication_approval_request"
                        ):
                            request_id = message.get("request_id")
                            if request_id:
                                pending_inbox.append(message)
                                processed_communication_request_ids.add(
                                    request_id
                                )
                            retained_inbox.append(message)
                        elif message.get("type") == "peer_message":
                            message_id = message.get("message_id")
                            pending_inbox.append(message)
                            retained_inbox.append(message)
                            if message_id:
                                processed_peer_message_ids.add(message_id)
                        else:
                            pending_inbox.append(message)
                    team.message_inbox = retained_inbox
                if pending_inbox:
                    inbox_lines = []
                    for msg in pending_inbox:
                        inbox_lines.append(f"- **From [{msg.get('from', 'Unknown')}]**: {msg.get('reason') or msg.get('objective') or str(msg)}")
                    
                    raw_inbox_text = "\n".join(inbox_lines)
                    threshold = self.config.inbox_summarize_threshold_chars
                    if len(raw_inbox_text) > threshold:
                        summarize_client = None
                        if team.members and getattr(team.members[0], "llm_client", None):
                            summarize_client = team.members[0].llm_client
                        elif self.root_ai and getattr(self.root_ai, "llm_client", None):
                            summarize_client = self.root_ai.llm_client
                        
                        if summarize_client:
                            self.logger.info("Inbox context too large, summarizing before injection...")
                            summary_prompt = f"Summarize the following system alerts and escalations concisely:\n\n{raw_inbox_text}"
                            try:
                                raw_inbox_text = await generate_with_retry(
                                    llm_client=summarize_client,
                                    prompt=summary_prompt,
                                    system_instruction="You are a strict system summarizer. Compress alerts while keeping critical facts and failures.",
                                    temperature=0.1,
                                    retries=self.config.llm_max_retries,
                                    backoff_factor=self.config.llm_retry_backoff_factor,
                                    manager=self
                                )
                            except Exception as e:
                                self.logger.warning(f"Failed to summarize inbox: {e}")
                            
                    inbox_context = (
                        f"\n\n### UNRESOLVED INBOX ALERTS & ESCALATIONS\n"
                        f"Your team has received the following signals from your descendants or supervisor:\n"
                        f"{raw_inbox_text}\n"
                        f"Please address or incorporate these alerts into your decision-making."
                    )
                    self._auto_save(inboxes={team.team_id})

                round_members = list(team.members)
                tasks = []
                for agent in round_members:
                    if r == 1:
                        round_prompt = f"{prompt}{inbox_context}"
                    else:
                        other_answers = []
                        for other_agent in round_members:
                            if other_agent.name != agent.name:
                                ans = last_round_answers.get((r - 1, other_agent.name), "No response.")
                                other_answers.append(f"{other_agent.name} (Role: {other_agent.role}): {ans}")
                        
                        round_prompt = (
                            f"Here is the discussion from Round {r - 1}:\n"
                            + "\n".join(other_answers) + "\n\n"
                            f"Please continue the discussion. Build on or challenge their arguments."
                            f"{inbox_context}"
                        )

                    async def _run_agent(ag=agent, pr=round_prompt):
                        public_method = team.execute_reasoning_step
                        if (
                            getattr(public_method, "__func__", None)
                            is not AgentTeam.execute_reasoning_step
                        ):
                            raw = await public_method(
                                agent=ag,
                                prompt=pr,
                                system_instruction=team.system_instructions,
                                max_steps=self.config.react_max_steps,
                                manager=self,
                            )
                            if isinstance(raw, AgentTurnResult):
                                return raw
                            return AgentTurnResult(
                                agent_id=ag.agent_id,
                                team_id=team.team_id,
                                discussion_id=self._active_discussion_id.get(),
                                status=AgentTurnStatus.COMPLETED,
                                answer=str(raw),
                            )
                        return await team.execute_reasoning_step_detailed(
                            agent=ag,
                            prompt=pr,
                            system_instruction=team.system_instructions,
                            max_steps=self.config.react_max_steps,
                            manager=self,
                        )
                    tasks.append(_run_agent())

                results = await asyncio.gather(*tasks, return_exceptions=True)

                round_turns: List[AgentTurnResult] = []
                for agent, result in zip(round_members, results):
                    if isinstance(result, asyncio.CancelledError):
                        raise result
                    if isinstance(result, AgentTurnIncompleteError):
                        aborted_turn = result.result
                        await self._report_operational_degraded(
                            team,
                            AuditResult(
                                status=AuditStatus.UNKNOWN,
                                reason=(
                                    "The discussion aborted before content "
                                    "supervision completed."
                                ),
                                operational_status=(
                                    OperationalStatus.DEGRADED
                                ),
                                operational_reason=(
                                    "A configured member failure policy "
                                    "aborted the discussion: "
                                    f"agent_id={aborted_turn.agent_id}, "
                                    f"error_kind={aborted_turn.error_kind or 'unknown'}."
                                ),
                            ),
                        )
                        raise result
                    if isinstance(result, ATTException):
                        self.logger.error(
                            "Discussion aborted by framework error: %s", result
                        )
                        raise result
                    elif isinstance(result, Exception):
                        self.logger.error(
                            "Agent %s encountered an unclassified member error "
                            "of type %s.",
                            agent.name,
                            type(result).__name__,
                        )
                        discussion_had_member_errors = True
                        turn = AgentTurnResult(
                            agent_id=agent.agent_id,
                            team_id=team.team_id,
                            discussion_id=self._active_discussion_id.get(),
                            round_number=r,
                            status=AgentTurnStatus.INCOMPLETE,
                            error_kind="member_exception",
                            reason=(
                                f"{type(result).__name__}: member execution "
                                "failed before producing a structured result."
                            ),
                        )
                    else:
                        turn = result.model_copy(update={"round_number": r})
                        if turn.status is AgentTurnStatus.INCOMPLETE:
                            discussion_had_member_errors = True
                    ans = turn.text
                    round_turns.append(turn)
                    last_round_answers[(r, agent.name)] = ans
                    dialog_history.append(f"{agent.name}: {ans}")

                structured_rounds.append(
                    DiscussionRoundResult(
                        round_number=r, turns=round_turns
                    )
                )

                if self.config.enable_membership_voting:
                    await self._apply_deferred_membership_changes(team)

            transcript = "\n".join(dialog_history)

            if require_complete and discussion_had_member_errors:
                raise RuntimeError(
                    "The governance discussion was incomplete because at "
                    "least one Agent reasoning step failed."
                )

            # Run supervisory audit
            operational_status = (
                OperationalStatus.DEGRADED
                if discussion_had_member_errors
                else OperationalStatus.HEALTHY
            )
            incomplete_metadata = []
            for round_result in structured_rounds:
                for turn in round_result.turns:
                    if turn.status is AgentTurnStatus.INCOMPLETE:
                        incomplete_metadata.append(
                            {
                                "agent_id": turn.agent_id,
                                "round_number": turn.round_number,
                                "error_kind": turn.error_kind,
                                "reason": turn.reason,
                                "tool_failures": [
                                    failure.model_dump(mode="json")
                                    for failure in turn.tool_failures
                                ],
                            }
                        )
            operational_reason = (
                "One or more Agent turns were incomplete: "
                + json.dumps(incomplete_metadata, sort_keys=True)
                if incomplete_metadata
                else "All member turns completed."
            )
            audit_transcript = transcript
            if incomplete_metadata:
                audit_transcript += (
                    "\n\n[ATT OPERATIONAL METADATA]\n"
                    + json.dumps(incomplete_metadata, sort_keys=True)
                )

            if not skip_audit:
                audit_result = await self.supervisor.audit_team_dialog(
                    team,
                    audit_transcript,
                    operational_status=operational_status,
                    operational_reason=operational_reason,
                )
                if audit_result.status is AuditStatus.UNHEALTHY:
                    await self.supervisor.report_anomaly(
                        team, audit_result.reason, self
                    )
                elif audit_result.status is AuditStatus.UNKNOWN:
                    self._emit_callback(
                        "on_system_event",
                        "audit_unknown",
                        {
                            "team_id": team.team_id,
                            "reason": audit_result.reason,
                            "cause": audit_result.cause,
                        },
                    )
                    await self.supervisor.report_unknown(
                        team, audit_result, self
                    )
                if (
                    audit_result.operational_status
                    is OperationalStatus.DEGRADED
                ):
                    await self._report_operational_degraded(
                        team, audit_result
                    )
            else:
                audit_result = AuditResult(
                    status=AuditStatus.HEALTHY,
                    reason="Audit skipped.",
                    operational_status=operational_status,
                    operational_reason=operational_reason,
                )
                
            # Log debate transcript using logger callback
            if self.on_log_append:
                log_title = f"Synthesized Debate Transcript | {team.team_id} ({team.preset_name}) - Rounds: {rounds}"
                log_content = (
                    f"TEAM_ID: {team.team_id}\n"
                    f"PRESET_NAME: {team.preset_name}\n"
                    f"PURPOSE: {team.team_purpose}\n"
                    f"PROMPT: {prompt}\n"
                    f"--- SYNTHESIZED TRANSCRIPT BEGIN ---\n"
                    f"{transcript}\n"
                    f"--- SYNTHESIZED TRANSCRIPT END ---\n"
                    f"AUDIT STATUS: {audit_result.status.value}\n"
                    f"AUDIT REASON: {audit_result.reason}\n"
                    f"OPERATIONAL STATUS: {audit_result.operational_status.value}\n"
                    f"OPERATIONAL REASON: {audit_result.operational_reason}\n"
                )
                self._emit_callback(
                    "on_log_append",
                    team.team_id,
                    log_title,
                    log_content,
                    team.chapter_num,
                )

            # A governance ballot may only follow a discussion that reached
            # the complete session boundary. A partial member failure keeps
            # every queued communication Approval pending for a later retry.
            if (
                processed_communication_request_ids
                and not discussion_had_member_errors
            ):
                await self.broker.process_team_approvals_from_transcript(
                    team,
                    sorted(processed_communication_request_ids),
                    transcript,
                    communication_member_snapshot,
                )

            self._auto_save(
                agents={agent.agent_id for agent in team.members},
                teams={team.team_id},
            )
            discussion_succeeded = True
            return DiscussionResult(
                team_id=team.team_id,
                discussion_id=self._active_discussion_id.get(),
                status=(
                    DiscussionStatus.PARTIAL
                    if discussion_had_member_errors
                    else DiscussionStatus.COMPLETED
                ),
                transcript=transcript,
                rounds=structured_rounds,
                audit=audit_result,
            )
        finally:
            if processed_peer_message_ids and discussion_succeeded:
                consumed_at = time.time()
                with team.inbox_lock:
                    team.message_inbox = [
                        message
                        for message in team.message_inbox
                        if message.get("message_id")
                        not in processed_peer_message_ids
                    ]
                changed_peer_messages = set()
                with self._snapshot_lock:
                    for message_id in processed_peer_message_ids:
                        message = self.broker.peer_messages.get(message_id)
                        if message is not None:
                            message.delivery_state = "consumed"
                            message.consumed_at = consumed_at
                            changed_peer_messages.add(message_id)
                self._auto_save(
                    inboxes={team.team_id},
                    peer_messages=changed_peer_messages,
                )
            if processed_unknown_fingerprints:
                with team.inbox_lock:
                    if discussion_succeeded:
                        retained_messages = []
                        for message in team.message_inbox:
                            is_processed_alert = (
                                message.get("type")
                                == "audit_unknown_escalation"
                                and message.get("fingerprint")
                                in processed_unknown_fingerprints
                            )
                            if not is_processed_alert:
                                retained_messages.append(message)
                                continue
                            processing_count = message.pop(
                                "processing_count",
                                message.get("occurrence_count", 1),
                            )
                            if (
                                message.get("occurrence_count", 1)
                                > processing_count
                            ):
                                message["state"] = "pending"
                                retained_messages.append(message)
                        team.message_inbox = retained_messages
                    else:
                        for message in team.message_inbox:
                            if (
                                message.get("type")
                                == "audit_unknown_escalation"
                                and message.get("fingerprint")
                                in processed_unknown_fingerprints
                            ):
                                message["state"] = "pending"
                                message.pop("processing_count", None)
                self._auto_save(inboxes={team.team_id})
            if processed_operational_fingerprints:
                self._finish_durable_alert_processing(
                    team,
                    "operational_degraded_escalation",
                    processed_operational_fingerprints,
                    discussion_succeeded,
                )
            await auto_save_context.__aexit__(None, None, None)
            self._active_discussion_id.reset(discussion_token)
            team.is_running = False
            if team.message_inbox and self.config.enable_emergency_wakeup:
                wake_types = {
                    "child_failure_escalation",
                    "escalation_spawn",
                }
                if self.config.audit_unknown_escalation_mode == "wake":
                    wake_types.add("audit_unknown_escalation")
                if (
                    self.config.operational_degraded_escalation_mode
                    == "wake"
                ):
                    wake_types.add("operational_degraded_escalation")
                emergency_msg = next(
                    (
                        msg
                        for msg in team.message_inbox
                        if msg.get("type") in wake_types
                    ),
                    None,
                )
                if emergency_msg:
                    self.schedule_emergency_wakeup(
                        team,
                        emergency_msg,
                        skip_audit=(
                            emergency_msg.get("type")
                            in {
                                "audit_unknown_escalation",
                                "operational_degraded_escalation",
                            }
                        ),
                    )

    async def flush_deferred_tasks(self):
        """Schedules deferred emergency call specifications."""
        while not self.deferred_emergency_tasks.empty():
            team, alert, skip_audit = (
                self.deferred_emergency_tasks.get_nowait()
            )
            self.schedule_emergency_wakeup(
                team, alert, skip_audit=skip_audit
            )

    def schedule_emergency_wakeup(
        self,
        team: AgentTeam,
        alert: Dict[str, Any],
        *,
        skip_audit: bool = False,
    ) -> None:
        """Schedules an emergency discussion and deduplicates audit outages."""
        if self._closing:
            return
        dedupe_key = None
        if alert.get("type") in {
            "audit_unknown_escalation",
            "operational_degraded_escalation",
        }:
            dedupe_key = self._unknown_audit_wakeup_key(team, alert)
            if dedupe_key in self._unknown_audit_wakeups:
                return
            self._unknown_audit_wakeups.add(dedupe_key)

        async def run() -> None:
            try:
                await self.execute_emergency_discussion(
                    team, alert, skip_audit=skip_audit
                )
            finally:
                if dedupe_key is not None:
                    self._unknown_audit_wakeups.discard(dedupe_key)

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            if dedupe_key is not None:
                self._unknown_audit_wakeups.discard(dedupe_key)
            self.deferred_emergency_tasks.put_nowait(
                (team, dict(alert), skip_audit)
            )
            self.logger.info(
                "Queued emergency wakeup for team %s until an event loop "
                "is available.",
                team.team_id,
            )
        else:
            task = loop.create_task(run())
            self._emergency_tasks.add(task)
            task.add_done_callback(self._emergency_tasks.discard)

    @staticmethod
    def _unknown_alert_fingerprint(alert: Dict[str, Any]) -> str:
        payload = json.dumps(
            {
                "type": alert.get("type"),
                "failed_team_id": alert.get("failed_team_id"),
                "reason": alert.get("reason"),
                "cause": alert.get("cause"),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _merge_unknown_alert(
        self, team: AgentTeam, alert: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Compatibility wrapper for UNKNOWN audit alerts."""
        return self._merge_durable_alert(team, alert)

    def _merge_durable_alert(
        self, team: AgentTeam, alert: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Persistently coalesces one operational alert without dropping uniques."""
        now = time.time()
        alert_type = alert.get("type")
        if alert_type not in {
            "audit_unknown_escalation",
            "operational_degraded_escalation",
        }:
            raise ValueError("Unsupported durable alert type.")
        fingerprint = alert.get("fingerprint") or self._unknown_alert_fingerprint(
            alert
        )
        with team.inbox_lock:
            existing = next(
                (
                    item
                    for item in team.message_inbox
                    if item.get("type") == alert_type
                    and item.get("fingerprint") == fingerprint
                ),
                None,
            )
            if existing is not None:
                existing["occurrence_count"] = int(
                    existing.get("occurrence_count", 1)
                ) + 1
                existing["last_seen"] = now
                merged = existing
            else:
                merged = dict(alert)
                merged.update(
                    {
                        "fingerprint": fingerprint,
                        "occurrence_count": 1,
                        "first_seen": now,
                        "last_seen": now,
                        "state": "pending",
                    }
                )
                team.message_inbox.append(merged)
            unique_count = sum(
                item.get("type") == alert_type
                for item in team.message_inbox
            )
        if unique_count >= self.config.audit_unknown_soft_threshold:
            event_name = (
                "audit_unknown_soft_threshold"
                if alert_type == "audit_unknown_escalation"
                else "operational_degraded_soft_threshold"
            )
            self.logger.warning(
                "Team %s has %s unique pending %s alerts.",
                team.team_id,
                unique_count,
                alert_type,
            )
            self._emit_callback(
                "on_system_event",
                event_name,
                {
                    "team_id": team.team_id,
                    "alert_type": alert_type,
                    "unique_alerts": unique_count,
                },
            )
        return merged

    def _finish_durable_alert_processing(
        self,
        team: AgentTeam,
        alert_type: str,
        fingerprints: set[str],
        succeeded: bool,
    ) -> None:
        with team.inbox_lock:
            retained = []
            for message in team.message_inbox:
                selected = (
                    message.get("type") == alert_type
                    and message.get("fingerprint") in fingerprints
                )
                if not selected:
                    retained.append(message)
                    continue
                processing_count = message.pop(
                    "processing_count", message.get("occurrence_count", 1)
                )
                if not succeeded or message.get(
                    "occurrence_count", 1
                ) > processing_count:
                    message["state"] = "pending"
                    retained.append(message)
            team.message_inbox = retained
        self._auto_save(inboxes={team.team_id})

    async def _report_operational_degraded(
        self, team: AgentTeam, audit_result: Any
    ) -> None:
        """Records and optionally propagates one operational degradation."""
        message = {
            "type": "operational_degraded_escalation",
            "from": "Supervisor",
            "failed_team_id": team.team_id,
            "reason": audit_result.operational_reason,
        }
        message["fingerprint"] = self._unknown_alert_fingerprint(message)
        self._emit_callback(
            "on_system_event", "operational_degraded", dict(message)
        )
        mode = self.config.operational_degraded_escalation_mode
        if mode == "none":
            return
        parent = team.parent_team or self.find_parent_team(team)
        if parent is None:
            self._emit_callback(
                "on_emergency_escalation",
                team.team_id,
                message["type"],
                message["reason"],
            )
            return
        parent.receive_message(message)

    def acknowledge_unknown_alert(
        self, team_id: str, fingerprint: str
    ) -> bool:
        """Explicitly acknowledges and removes one UNKNOWN alert."""
        team = self.teams.get(team_id)
        if team is None:
            raise KeyError(f"Unknown team {team_id!r}.")
        with team.inbox_lock:
            before = len(team.message_inbox)
            team.message_inbox = [
                item
                for item in team.message_inbox
                if not (
                    item.get("type") == "audit_unknown_escalation"
                    and item.get("fingerprint") == fingerprint
                )
            ]
            changed = len(team.message_inbox) != before
        if changed:
            self._auto_save(inboxes={team_id})
        return changed

    def clear_unknown_alerts(
        self, team_id: str, fingerprints: Optional[set[str]] = None
    ) -> int:
        """Explicitly clears selected or all UNKNOWN alerts for one team."""
        team = self.teams.get(team_id)
        if team is None:
            raise KeyError(f"Unknown team {team_id!r}.")
        with team.inbox_lock:
            retained = []
            removed = 0
            for item in team.message_inbox:
                is_unknown = item.get("type") == "audit_unknown_escalation"
                selected = fingerprints is None or item.get("fingerprint") in fingerprints
                if is_unknown and selected:
                    removed += 1
                else:
                    retained.append(item)
            team.message_inbox = retained
        if removed:
            self._auto_save(inboxes={team_id})
        return removed

    @staticmethod
    def _unknown_audit_wakeup_key(
        team: AgentTeam, alert: Dict[str, Any]
    ) -> str:
        fingerprint = alert.get("fingerprint") or ATTManager._unknown_alert_fingerprint(
            alert
        )
        return f"{team.team_id}:{alert.get('type')}:{fingerprint}"

    def is_unknown_audit_wakeup_active(
        self, team: AgentTeam, alert: Dict[str, Any]
    ) -> bool:
        """Returns whether an identical UNKNOWN wakeup is already active."""
        key = self._unknown_audit_wakeup_key(team, alert)
        return key in self._unknown_audit_wakeups

    async def execute_emergency_discussion(
        self,
        team: AgentTeam,
        alert: Dict[str, Any],
        *,
        skip_audit: bool = False,
    ) -> str:
        """Executes an emergency discussion round to handle child failure or escalation."""
        emergency_prompt = (
            f"EMERGENCY MEETING: An anomaly or escalation was reported from your child team or supervisor.\n"
            f"Alert details: {alert.get('reason') or alert.get('objective') or str(alert)}\n"
            f"Please evaluate this issue and decide on corrective actions or escalate further."
        )
        rounds = getattr(self.config, "emergency_discussion_rounds", 1)
        self.logger.warning(f"Starting emergency discussion on team {team.team_id} for {rounds} round(s)...")
        return await self.execute_team_discussion(
            team,
            prompt=emergency_prompt,
            rounds=rounds,
            skip_audit=skip_audit,
        )
