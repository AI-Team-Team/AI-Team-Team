import asyncio
import contextvars
import os
import logging
import json
import time
import threading
import shutil
import tempfile
import uuid
from contextlib import asynccontextmanager
from typing import List, Dict, Optional, Tuple, Any, Callable

from ai_team_team.doc_library import DocumentLibrary
from ai_team_team.tool import Tool

# Modular sub-module imports
from .agent import Agent
from .team import AgentTeam
from .broker import NegotiationBroker
from .config import ATTConfig
from .exceptions import ATTException, TokenLimitExceededError, StateRestoreError
from .utils import generate_with_retry
from .adapters import ManagerDefaultClientAdapter, HandlerClientAdapter
from .token_budget import TokenBudgetLedger

from ai_team_team.database.persistence import (
    PersistenceCoordinator,
    STATE_SCHEMA_VERSION,
)

class ATTManager:
    """Master controller managing the overall ATT (AI Team Team) topology."""
    def __init__(self, root_ai: Agent, config: Optional[ATTConfig] = None, db_path: Optional[str] = None):
        self.root_ai = root_ai
        self.config = config or ATTConfig()
        self.db_path = db_path
        self.agents: Dict[str, Agent] = {root_ai.name: root_ai}
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
        self._persistence = PersistenceCoordinator()
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
        self._unknown_audit_wakeups: set[str] = set()
        self._emergency_tasks: set[asyncio.Task[Any]] = set()
        
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
            "agreements": full,
            "libraries": set(),
            "permissions": set(),
            "links": set(),
            "file_changes": {},
        }

    @staticmethod
    def _merge_dirty_state(target: Dict[str, Any], source: Dict[str, Any]) -> None:
        target["full"] = target["full"] or source["full"]
        target["configs"] = target["configs"] or source["configs"]
        target["agreements"] = target["agreements"] or source["agreements"]
        for key in (
            "agents",
            "teams",
            "inboxes",
            "proposals",
            "libraries",
            "permissions",
            "links",
        ):
            target[key].update(source[key])
        for lib_id, changes in source["file_changes"].items():
            target["file_changes"].setdefault(lib_id, {}).update(changes)

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
            or dirty["agreements"]
            or dirty["agents"]
            or dirty["teams"]
            or dirty["inboxes"]
            or dirty["proposals"]
            or dirty["libraries"]
            or dirty["permissions"]
            or dirty["links"]
            or dirty["file_changes"]
        )

    def _auto_save(
        self,
        *,
        configs: bool = False,
        agents: Optional[set[str]] = None,
        teams: Optional[set[str]] = None,
        inboxes: Optional[set[str]] = None,
        proposals: Optional[set[str]] = None,
        agreements: bool = False,
        libraries: Optional[set[str]] = None,
        permissions: Optional[set[str]] = None,
        links: Optional[set[str]] = None,
        file_changes: Optional[
            Dict[str, Dict[str, Optional[str]]]
        ] = None,
        full: bool = False,
    ) -> None:
        """Records an immutable incremental state delta for the single writer."""
        if not self.db_path:
            return
        dirty = self._new_dirty_state(full=full)
        dirty["configs"] = configs or full
        dirty["agreements"] = agreements or full
        dirty["agents"].update(agents or set())
        dirty["teams"].update(teams or set())
        dirty["inboxes"].update(inboxes or set())
        dirty["proposals"].update(proposals or set())
        dirty["libraries"].update(libraries or set())
        dirty["permissions"].update(permissions or set())
        dirty["links"].update(links or set())
        for lib_id, changes in (file_changes or {}).items():
            dirty["file_changes"].setdefault(lib_id, {}).update(changes)

        if not self._dirty_state_has_changes(dirty):
            return
        batch = self._persistence_batch.get()
        if batch is not None:
            self._merge_dirty_state(batch, dirty)
            return
        self._submit_dirty_state(dirty)

    def _submit_dirty_state(self, dirty: Dict[str, Any]) -> None:
        with self._snapshot_lock:
            snapshot = self._capture_state_snapshot(dirty)
            self._persistence.submit(self.db_path, snapshot)

    async def save_state(
        self, path: Optional[str] = None, full: bool = True
    ) -> None:
        """Persists state asynchronously and waits for the write to commit."""
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
        await asyncio.wrap_future(future)

    async def flush_state(self) -> None:
        """Waits until every queued state delta has committed."""
        await self._persistence.flush()

    async def close(self) -> None:
        """Flushes state and releases the persistence worker and engines."""
        active_tasks = tuple(
            task
            for task in self._emergency_tasks
            if not task.done() and task is not asyncio.current_task()
        )
        if active_tasks:
            await asyncio.gather(*active_tasks, return_exceptions=True)
        await self._persistence.close()

    async def load_state(self, path: str) -> None:
        """Restores a versioned state snapshot without blocking the event loop."""
        if not os.path.exists(path):
            raise FileNotFoundError(f"State database file '{path}' not found.")
        state = await self._persistence.read(path)
        await self._apply_state_snapshot(state)
        self.db_path = path

    def _capture_state_snapshot(self, dirty: Dict[str, Any]) -> Dict[str, Any]:
        full = dirty["full"]
        now = time.time()
        configs = None
        if full or dirty["configs"]:
            configs = {
                "schema_version": STATE_SCHEMA_VERSION,
                "att_config": json.dumps(self.config.__dict__),
                "root_ai_name": self.root_ai.name,
                "model_configs": json.dumps(self.model_configs),
                "presets": json.dumps(self.presets),
                "model_token_usage": json.dumps(self.model_token_usage),
            }

        agent_names = set(self.agents) if full else set(dirty["agents"])
        agents = []
        for name in sorted(agent_names):
            agent = self.agents.get(name)
            if agent is None:
                continue
            model_alias = self.resolve_model_alias(agent.llm_client)
            agents.append(
                {
                    "name": agent.name,
                    "role": agent.role,
                    "role_description": getattr(
                        agent, "role_description", ""
                    ),
                    "system_instructions": getattr(
                        agent, "system_instructions", ""
                    ),
                    "model_alias": model_alias,
                    "last_context": (
                        json.dumps(agent.last_context)
                        if agent.last_context
                        else None
                    ),
                    "messages": json.loads(json.dumps(agent.messages)),
                    "message_timestamp": now,
                }
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
                creator_id = team.creator.name
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
                    "communication_rules": json.dumps(
                        team.communication_rules
                    ),
                    "status_map": json.dumps(team.status_snapshot()),
                    "system_instructions": getattr(
                        team, "system_instructions", ""
                    ),
                    "members": [member.name for member in team.members],
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
                messages = json.loads(json.dumps(team.message_inbox))
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
                    **json.loads(json.dumps(proposal)),
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
                    "description": library.description,
                    "is_public_visible": library.is_public_visible,
                }
            )

        permission_ids = (
            set(self.libraries) if full else set(dirty["permissions"])
        )
        permissions = {
            lib_id: json.loads(
                json.dumps(self.library_permissions.get(lib_id, {}))
            )
            for lib_id in permission_ids
        }
        link_ids = set(self.libraries) if full else set(dirty["links"])
        links = {
            lib_id: json.loads(
                json.dumps(self.library_links.get(lib_id, {}))
            )
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

        return {
            "full": full,
            "configs": configs,
            "agents": agents,
            "teams": teams,
            "inboxes": inboxes,
            "proposals": proposals,
            "agreements": (
                [list(pair) for pair in sorted(self.broker.peer_talk_agreements)]
                if full or dirty["agreements"]
                else None
            ),
            "libraries": libraries,
            "permissions": permissions,
            "links": links,
            "file_changes": file_changes,
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
            if row.get("model_alias") not in (None, "default")
        }
        missing_aliases = sorted(
            alias
            for alias in required_aliases
            if alias not in self.llm_clients and not self.generator_handler
        )
        if missing_aliases:
            raise StateRestoreError(
                "Missing runtime bindings for model aliases: "
                + ", ".join(missing_aliases)
            )

        runtime_root_client = self.root_ai.llm_client
        self.agents.clear()
        for row in state["agents"]:
            alias = row.get("model_alias")
            if alias in self.llm_clients:
                client = self.llm_clients[alias]
            elif alias not in (None, "default") and self.generator_handler:
                client = HandlerClientAdapter(alias, self.generator_handler)
                client._supports_native = self.model_configs.get(
                    alias, {}
                ).get("supports_native_tool_calling", False)
            elif "default" in self.llm_clients:
                client = self.llm_clients["default"]
            elif runtime_root_client:
                client = runtime_root_client
            elif self.generator_handler:
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
            )
            agent.last_context = (
                json.loads(row["last_context"])
                if row["last_context"]
                else None
            )
            agent.messages = []
            for message in row["messages"]:
                restored = {
                    key: value
                    for key, value in message.items()
                    if value is not None
                }
                agent.messages.append(restored)
            self.agents[agent.name] = agent

        root_name = configs["root_ai_name"]
        if root_name not in self.agents:
            raise StateRestoreError(
                f"Persisted root agent {root_name!r} was not found."
            )
        self.root_ai = self.agents[root_name]
        self.supervisor.root_ai = self.root_ai

        self.libraries.clear()
        self._library_files.clear()
        for row in state["libraries"]:
            library = self._new_document_library(
                lib_id=row["lib_id"],
                name=row["name"],
                owner_team_id=row["owner_team_id"],
                description=row["description"] or "",
                is_public_visible=row["is_public_visible"],
            )
            await asyncio.to_thread(
                library.replace_all_files, row["files"]
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
                self.agents.get(row["creator_id"])
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
            team.communication_rules = json.loads(
                row["communication_rules"] or "{}"
            )
            team.status_map = json.loads(row["status_map"] or "{}")
            team.system_instructions = row["system_instructions"] or ""
            team._cached_depth = None
            team.manager = self
            team.message_inbox = row["inbox"]
            team.proposals = {
                proposal["proposal_id"]: {
                    key: value
                    for key, value in proposal.items()
                    if key != "proposal_id"
                }
                for proposal in row["proposals"]
            }
            team.members = [self.agents[name] for name in row["members"]]
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

        self.broker.peer_talk_agreements = set(
            tuple(pair) for pair in state["agreements"]
        )

    async def _apply_state_snapshot(self, state: Dict[str, Any]) -> None:
        """Stages, validates, and atomically publishes a restored state."""
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
                "teams": self.teams,
                "libraries": self.libraries,
                "library_permissions": self.library_permissions,
                "library_links": self.library_links,
                "library_files": self._library_files,
                "team_parent_map": self._team_parent_map,
                "model_configs": self.model_configs,
                "presets": self.presets,
                "model_token_usage": self.model_token_usage,
                "agreements": self.broker.peer_talk_agreements,
            }
            try:
                self.config = target_config
                self.root_ai = staged.root_ai
                self.agents = staged.agents
                self.teams = staged.teams
                self.libraries = staged.libraries
                self.library_permissions = staged.library_permissions
                self.library_links = staged.library_links
                self._library_files = staged._library_files
                self._team_parent_map = staged._team_parent_map
                self.model_configs = staged.model_configs
                self.presets = staged.presets
                self.model_token_usage = staged.model_token_usage
                self.broker.peer_talk_agreements = set(
                    staged.broker.peer_talk_agreements
                )
                self.supervisor.root_ai = self.root_ai
                self.tools_context["att_manager"] = self
                self.token_budget.reset_reservations()
            except Exception:
                self.config = old_state["config"]
                self.root_ai = old_state["root_ai"]
                self.agents = old_state["agents"]
                self.teams = old_state["teams"]
                self.libraries = old_state["libraries"]
                self.library_permissions = old_state["library_permissions"]
                self.library_links = old_state["library_links"]
                self._library_files = old_state["library_files"]
                self._team_parent_map = old_state["team_parent_map"]
                self.model_configs = old_state["model_configs"]
                self.presets = old_state["presets"]
                self.model_token_usage = old_state["model_token_usage"]
                self.broker.peer_talk_agreements = old_state["agreements"]
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
            config = ATTConfig(**json.loads(configs["att_config"]))
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
            agreements = state["agreements"]
        except Exception as exc:
            raise StateRestoreError(
                f"Invalid persisted state structure: {exc}"
            ) from exc

        agent_names = [row.get("name") for row in agent_rows]
        if None in agent_names or len(agent_names) != len(set(agent_names)):
            raise StateRestoreError("Agent identifiers are missing or duplicated.")
        root_name = configs.get("root_ai_name")
        if root_name not in set(agent_names):
            raise StateRestoreError(
                f"Persisted root agent {root_name!r} was not found."
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
        missing_aliases = sorted(
            {
                row.get("model_alias")
                for row in agent_rows
                if row.get("model_alias") not in {None, "default"}
                and row.get("model_alias") not in self.llm_clients
                and not self.generator_handler
            }
        )
        if missing_aliases:
            raise StateRestoreError(
                "Missing runtime bindings for model aliases: "
                + ", ".join(missing_aliases)
            )
        has_default_binding = bool(
            "default" in self.llm_clients
            or self.root_ai.llm_client
            or self.generator_handler
        )
        if any(
            row.get("model_alias") in {None, "default"}
            for row in agent_rows
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
        agent_name_set = set(agent_names)
        parent_map: Dict[str, Optional[str]] = {}
        for row in team_rows:
            team_id = row["team_id"]
            try:
                json.loads(row.get("communication_rules") or "{}")
                json.loads(row.get("status_map") or "{}")
            except Exception as exc:
                raise StateRestoreError(
                    f"Team {team_id!r} contains invalid JSON metadata."
                ) from exc
            missing_members = sorted(
                set(row.get("members", [])) - agent_name_set
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
                valid_creator = creator_id in agent_name_set
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
                initiator_type = proposal.get("initiator_type")
                initiator_name = proposal.get("initiator_name")
                if (
                    initiator_type == "individual"
                    and initiator_name not in agent_name_set
                ):
                    raise StateRestoreError(
                        f"Proposal {proposal.get('proposal_id')!r} references "
                        f"missing initiator agent {initiator_name!r}."
                    )
                if (
                    initiator_type == "AT"
                    and initiator_name not in {"AT", team_id}
                ):
                    raise StateRestoreError(
                        f"Proposal {proposal.get('proposal_id')!r} references "
                        f"invalid team initiator {initiator_name!r}."
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
            if row.get("owner_team_id") not in team_id_set:
                raise StateRestoreError(
                    f"DocLib {lib_id!r} references a missing owner team."
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
            if f"DL-{team_id}" not in library_id_set:
                raise StateRestoreError(
                    f"Team {team_id!r} is missing its built-in DocLib."
                )

        for lib_id, path_map in permissions.items():
            if lib_id not in library_id_set:
                raise StateRestoreError(
                    f"Permissions reference missing DocLib {lib_id!r}."
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
            for source_path, target in path_map.items():
                target_lib_id = target["target_lib_id"]
                target_path = target["target_path"]
                if target_lib_id not in library_id_set:
                    raise StateRestoreError(
                        f"Link references missing target DocLib {target_lib_id!r}."
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

        for sender_id, recipient_id in agreements:
            if sender_id not in team_id_set or recipient_id not in team_id_set:
                raise StateRestoreError(
                    "Broker agreement references a missing team."
                )
        return config

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
        owner_team_id: str,
        description: str,
        is_public_visible: bool,
        storage_dir: Optional[str] = None,
    ) -> DocumentLibrary:
        self._library_files.setdefault(lib_id, {})
        return DocumentLibrary(
            lib_id=lib_id,
            name=name,
            owner_team_id=owner_team_id,
            description=description,
            is_public_visible=is_public_visible,
            root_dir=self.config.workspace_root,
            on_change=self._on_library_change,
            storage_dir=storage_dir,
        )

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

    def register_model(self, name: str, config: Dict[str, Any]):
        """Registers a unified model configuration (e.g. metadata, type, ai_note)."""
        self.model_configs[name] = config
        self._auto_save(configs=True)

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
        """Resolves the model alias name for a given LLM client wrapper/mock."""
        model_name = getattr(llm_client, "model_name", None)
        if isinstance(model_name, str):
            return model_name
        for name, client in self.llm_clients.items():
            if client is llm_client:
                return name
        from .adapters import ManagerDefaultClientAdapter
        if isinstance(llm_client, ManagerDefaultClientAdapter):
            return "default"
        return "default"

    async def handle_failover(self, agent: Agent, team: AgentTeam, error: TokenLimitExceededError) -> bool:
        """
        Handles client failover for an agent when a token limit is reached.
        Returns True if hot-swap succeeded and caller should retry.
        """
        old_model = self.resolve_model_alias(agent.llm_client)
        policy = self.config.failover_policy
        
        parent_team = team.parent_team or self.find_parent_team(team)
        if policy == "parent" and parent_team is None:
            self.logger.warning(f"Parent failover policy requested but parent team not found. Falling back to 'auto'.")
            policy = "auto"

        candidates = []
        required_tokens = max(1, getattr(error, "required_tokens", 1))
        for name in self.config.model_token_limits.keys():
            if name == old_model:
                continue
            available = self.token_budget.available(name)
            if available is not None and available >= required_tokens:
                candidates.append(name)
        if "default" not in self.config.model_token_limits and "default" not in candidates:
            candidates.append("default")

        selected_model = None

        if policy == "auto":
            if candidates:
                selected_model = candidates[0]
            else:
                self.logger.error(f"Failover failed: No candidate models with remaining budget found.")
                return False
                
        elif policy == "parent":
            from ai_team_team.core.policies import get_team_representative
            parent_rep = get_team_representative(parent_team, self)
            
            if not parent_rep or not parent_rep.llm_client:
                self.logger.warning("Parent representative client not available. Falling back to 'auto'.")
                if candidates:
                    selected_model = candidates[0]
                else:
                    return False
            else:
                prompt_candidates = ", ".join(candidates)
                delegation_prompt = (
                    f"Your child team {team.team_id} is running and has encountered a model failover. "
                    f"Agent '{agent.name}' (role: {agent.role}) reached the token budget limit for Model '{old_model}'.\n"
                    f"Please select a new model for Agent '{agent.name}' from the following available models:\n"
                    f"[{prompt_candidates}]\n\n"
                    f"Evaluate the task importance and budget, and output exactly a JSON payload:\n"
                    f"{{\n"
                    f"  \"selected_model\": \"<model_name>\"\n"
                    f"}}"
                )
                
                try:
                    response_text = await generate_with_retry(
                        llm_client=parent_rep.llm_client,
                        prompt=delegation_prompt,
                        system_instruction="You are a precise failover manager that selects target models. Respond in JSON.",
                        temperature=0.1,
                        require_json=True,
                        manager=self
                    )
                    if "```" in response_text:
                        response_text = response_text.replace("```json", "").replace("```", "").strip()
                    data = json.loads(response_text)
                    choice = data.get("selected_model")
                    if choice in candidates:
                        selected_model = choice
                        self.logger.info(f"Parent team selected model '{selected_model}' for agent '{agent.name}'.")
                    else:
                        self.logger.warning(f"Parent team chose invalid model '{choice}'. Falling back to first available.")
                        selected_model = candidates[0] if candidates else None
                except Exception as ex:
                    self.logger.error(f"Parent representation query failed: {ex}. Falling back to first available.")
                    selected_model = candidates[0] if candidates else None

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
        else:
            new_client = ManagerDefaultClientAdapter(self)
            
        agent.llm_client = new_client
        
        agent_status = f"Failover: Switched to {selected_model}"
        team.set_status(agent.name, agent_status)
        if self.on_status_change:
            self.on_status_change(agent.name, agent_status)

        if self.on_log_append:
            log_title = f"[SYSTEM ALERT] Model Failover Event | {agent.name}"
            log_content = (
                f"AGENT: {agent.name}\n"
                f"ROLE: {agent.role}\n"
                f"TEAM: {team.team_id}\n"
                f"FAILOVER POLICY: {policy}\n"
                f"ACTION: Switched client from Model '{old_model}' to Model '{selected_model}' due to budget exhaustion ({error})."
            )
            self.on_log_append(team.team_id, log_title, log_content, team.chapter_num)

        if self.on_system_event:
            try:
                self.on_system_event("model_failover", {
                    "agent_name": agent.name,
                    "team_id": team.team_id,
                    "old_model": old_model,
                    "new_model": selected_model,
                    "reason": str(error)
                })
            except Exception:
                pass
                
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
        initial_docs: Optional[Dict[str, str]] = None
    ) -> AgentTeam:
        """Creates a team while holding the topology mutation lock."""
        with self._topology_lock:
            return self._create_agent_team(
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
        initial_docs: Optional[Dict[str, str]] = None
    ) -> AgentTeam:

        """Dynamically spawns a new recursive Agent Team (AT)."""
        if member_configs:
            member_count = len(member_configs)
            
        min_size = self.config.min_subagent_team_size
        assert member_count >= min_size, f"An Agent Team must contain at least {min_size} members to debate properly."
        
        team = AgentTeam(creator=creator, preset_name=preset_name, team_purpose=team_purpose)
        team.manager = self
        if isinstance(creator, AgentTeam):
            team._parent_team = creator
        else:
            team._parent_team = self.find_parent_team(team)
            
        if team._parent_team:
            self._team_parent_map[team.team_id] = team._parent_team.team_id
        
        if isinstance(creator, AgentTeam):
            team.chapter_num = creator.chapter_num
        elif isinstance(creator, Agent):
            for t in self.teams.values():
                if creator in t.members:
                    team.chapter_num = t.chapter_num
                    break

        def get_agent_client_by_name(client_name: Optional[str]) -> Any:
            default_wrapper = ManagerDefaultClientAdapter(self)
            if client_name and client_name != "default":
                if client_name in self.llm_clients:
                    return self.llm_clients[client_name]
                elif client_name in self.model_configs and self.generator_handler:
                    adapter = HandlerClientAdapter(client_name, self.generator_handler)
                    config = self.model_configs.get(client_name)
                    if config:
                        adapter._supports_native = config.get("supports_native_tool_calling", False)
                    return adapter
                else:
                    available = list(self.model_configs.keys()) + list(self.llm_clients.keys())
                    raise ValueError(f"Model '{client_name}' is not registered. Available models are: {available}.")
            if "default" in self.llm_clients:
                return self.llm_clients["default"]
            if self.root_ai.llm_client:
                return self.root_ai.llm_client
            return default_wrapper

        def get_agent_client(role_name: str, agent_name: str) -> Any:
            client_name = None
            if roles_and_models:
                client_name = roles_and_models.get(role_name) or roles_and_models.get(agent_name)
            return get_agent_client_by_name(client_name)

        members = []
        if member_configs:
            for role_name, config in member_configs.items():
                if isinstance(config, Agent):
                    agent = config
                    agent.role = role_name
                    self.agents[agent.name] = agent
                    members.append(agent)
                elif isinstance(config, dict) and config.get("hire_agent") in self.agents:
                    agent = self.agents[config["hire_agent"]]
                    members.append(agent)
                elif isinstance(config, dict) and config.get("model") in self.agents:
                    agent = self.agents[config["model"]]
                    members.append(agent)
                else:
                    model_alias = config.get("model")
                    role_desc = config.get("role_description", "")
                    sys_inst = config.get("system_instructions", "")
                    agent_name = f"Dynamic_{role_name}_{team.team_id.split('-')[1]}"
                    client = get_agent_client_by_name(model_alias)
                    agent = Agent(
                        name=agent_name,
                        role=role_name,
                        llm_client=client,
                        role_description=role_desc,
                        system_instructions=sys_inst
                    )
                    self.agents[agent_name] = agent
                    members.append(agent)
        elif roles_and_presets:
            for name, role in roles_and_presets:
                agent_name = self.unique_agent_name(name, team)
                agent = Agent(name=agent_name, role=role, llm_client=get_agent_client(role, name))
                self.agents[agent_name] = agent
                members.append(agent)
        else:
            preset = self.get_preset(preset_name)
            roles = preset.get("roles", [])
            if len(roles) >= member_count:
                for name, role in roles[:member_count]:
                    agent_name = self.unique_agent_name(name, team)
                    agent = Agent(name=agent_name, role=role, llm_client=get_agent_client(role, name))
                    self.agents[agent_name] = agent
                    members.append(agent)
            else:
                for i in range(member_count):
                    m_name = f"{team.team_id}_member_{i+1}"
                    agent = Agent(name=m_name, role="Specialist", llm_client=get_agent_client("Specialist", m_name))
                    self.agents[m_name] = agent
                    members.append(agent)

        team.members = members
        team.system_instructions = system_instructions or self.get_preset(preset_name).get("system_instructions", "")
        
        # Bind generic tools
        from ai_team_team.tool import get_default_tools
        team.tools.update(get_default_tools(self.tools_context, team))
        
        # Bind globally registered custom tools
        team.tools.update(self.global_tools)
            
        self.teams[team.team_id] = team
        
        # Instantiate and associate default built-in DocLib for the team
        lib_id = f"DL-{team.team_id}"
        lib_name = f"{team.team_id} Built-in Library"
        lib_desc = f"Default document library for team {team.team_id}."
        
        lib = self._new_document_library(
            lib_id=lib_id,
            name=lib_name,
            owner_team_id=team.team_id,
            description=lib_desc,
            is_public_visible=is_public_visible,
        )
        self.libraries[lib_id] = lib
        team.doc_library = lib
        
        # Write initial_docs if any
        if initial_docs:
            for file_path, content in initial_docs.items():
                lib.write_file(file_path, content)

        
        if isinstance(creator, AgentTeam):
            creator.add_child_team(team)
        elif isinstance(creator, Agent):
            parent_t = self.find_parent_team(team)
            if parent_t:
                parent_t.add_child_team(team)
            
        self.logger.info(f"Successfully spawned Agent Team {team.team_id} (N={len(members)}, Preset: {preset_name}) spawned by {creator.name if hasattr(creator, 'name') else creator.team_id}")
        self._auto_save(
            configs=True,
            agents={self.root_ai.name}
            | {member.name for member in members},
            teams={team.team_id}
            | ({team.parent_team.team_id} if team.parent_team else set()),
            libraries={lib_id},
        )
        return team

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
        if hasattr(agent, '_parent_team') and agent._parent_team is not None:
            return agent._parent_team
            
        for team in self.teams.values():
            if agent in team.members:
                agent._parent_team = team
                return team
                
        return None
        
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
        limit = self.config.max_migrations_per_team_discussion
        current_count = getattr(team, "migration_count", 0)
        if current_count >= limit:
            return False, f"Rejected: Cannot request migration. Maximum migrations per discussion session ({limit}) reached."

        current_parent = team.parent_team
        current_parent_id = current_parent.team_id if current_parent else "Root AI"
        
        from .policies import resolve_migration_policy
        policy_name = getattr(self.config, "migration_policy", "ancestor_approval")
        policy = resolve_migration_policy(policy_name)
        
        try:
            approved, reason = await policy.authorize_migration(team, target_parent, self, rationale)
            
            if approved:
                with self._topology_lock:
                    current_parent = team.parent_team
                    current_count = team.migration_count
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
                if self.on_team_migration:
                    self.on_team_migration(team.team_id, current_parent_id if current_parent else None, target_parent.team_id)
                
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
                    self.agents[new_agent.name] = new_agent
                    changed_agents.add(new_agent.name)
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
            )

    async def execute_team_discussion(
        self,
        team: AgentTeam,
        prompt: str,
        rounds: int = 2,
        skip_audit: bool = False,
    ) -> str:
        """Queues one discussion behind any active session for the same team."""
        async with team.discussion_lock:
            return await self._execute_team_discussion_session(
                team,
                prompt,
                rounds=rounds,
                skip_audit=skip_audit,
            )

    async def _execute_team_discussion_session(
        self,
        team: AgentTeam,
        prompt: str,
        rounds: int = 2,
        skip_audit: bool = False,
    ) -> str:
        """Executes a multi-agent debate session inside the AT, monitored by the Supervisor."""
        with self._topology_lock:
            team.migration_count = 0
        team.is_running = True
        self.logger.info(f"Executing discussion in team {team.team_id} (rounds={rounds}, skip_audit={skip_audit})...")
        
        dialog_history = []
        last_round_answers = {}
        from ai_team_team.supervision import AuditResult, AuditStatus

        audit_result = AuditResult(
            status=AuditStatus.HEALTHY,
            reason="Audit skipped.",
        )
        
        auto_save_context = self.suppress_auto_save()
        await auto_save_context.__aenter__()
        try:
            for r in range(1, rounds + 1):
                inbox_context = ""
                with team.inbox_lock:
                    pending_inbox = team.message_inbox
                    team.message_inbox = []
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
                        return await team.execute_reasoning_step(
                            agent=ag,
                            prompt=pr,
                            system_instruction=team.system_instructions,
                            max_steps=self.config.react_max_steps,
                            manager=self
                        )
                    tasks.append(_run_agent())

                results = await asyncio.gather(*tasks, return_exceptions=True)

                for agent, result in zip(round_members, results):
                    if isinstance(result, ATTException):
                        self.logger.error(f"Failed to execute discussion step due to ATT error: {result}")
                        if not skip_audit:
                            await self.supervisor.report_anomaly(team, f"LLM client invocation error: {result}", self)
                        raise result
                    elif isinstance(result, Exception):
                        self.logger.error(f"Agent {agent.name} encountered an error: {result}")
                        ans = f"Error: {result}"
                    else:
                        ans = str(result)
                    
                    last_round_answers[(r, agent.name)] = ans
                    dialog_history.append(f"{agent.name}: {ans}")

                if self.config.enable_membership_voting:
                    await self._apply_deferred_membership_changes(team)

            transcript = "\n".join(dialog_history)
            
            # Run supervisory audit
            if not skip_audit:
                audit_result = await self.supervisor.audit_team_dialog(
                    team, transcript
                )
                if audit_result.status is AuditStatus.UNHEALTHY:
                    await self.supervisor.report_anomaly(
                        team, audit_result.reason, self
                    )
                elif audit_result.status is AuditStatus.UNKNOWN:
                    if self.on_system_event:
                        self.on_system_event(
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
                )
                self.on_log_append(
                    team.team_id,
                    log_title,
                    log_content,
                    team.chapter_num
                )

            self._auto_save(
                agents={agent.name for agent in team.members},
                teams={team.team_id},
            )
            return transcript
        finally:
            await auto_save_context.__aexit__(None, None, None)
            team.is_running = False
            if team.message_inbox and self.config.enable_emergency_wakeup:
                wake_types = {
                    "child_failure_escalation",
                    "escalation_spawn",
                }
                if self.config.audit_unknown_escalation_mode == "wake":
                    wake_types.add("audit_unknown_escalation")
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
                            == "audit_unknown_escalation"
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
        dedupe_key = None
        if alert.get("type") == "audit_unknown_escalation":
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
    def _unknown_audit_wakeup_key(
        team: AgentTeam, alert: Dict[str, Any]
    ) -> str:
        return json.dumps(
            {
                "team_id": team.team_id,
                "failed_team_id": alert.get("failed_team_id"),
                "reason": alert.get("reason"),
                "cause": alert.get("cause"),
            },
            sort_keys=True,
        )

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
