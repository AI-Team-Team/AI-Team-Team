"""Concrete ATTManager facade and service composition root."""

import asyncio
import contextvars
import logging
import threading
from typing import Any, Callable, Dict, Optional, Tuple

from ai_team_team.doc_library import DocumentLibrary
from ai_team_team.tool import Tool

from ...adapters import ManagerDefaultClientAdapter
from ...agent import Agent
from ...broker import NegotiationBroker
from ...config import ATTConfig
from ...team import AgentTeam
from ...token_budget import TokenBudgetLedger
from ..agents import AgentRegistry
from ..alerts import AlertService
from ..callbacks import CallbackDispatcher
from ..communication_validation import CommunicationStateValidator
from ..discussions import DiscussionCoordinator
from ..failover import FailoverService
from ..libraries import LibraryService
from ..lifecycle import LifecycleService
from ..membership import MembershipService
from ..migration import MigrationService
from ..memory import MemoryService
from ..restore import RestoreService
from ..runtime import RuntimeRegistry
from ..snapshots import SnapshotBuilder
from ..state import StateCoordinator
from ..state_validation import StateValidator
from ..team_creation import TeamCreationService
from ..topology import TopologyService
from .agents_api import AgentAPI
from .discussions_api import DiscussionAPI
from .libraries_api import LibraryAPI
from .memory_api import MemoryAPI
from .runtime_api import RuntimeAPI
from .state_api import StateAPI
from .teams_api import TeamAPI


class ATTManager(
    StateAPI,
    AgentAPI,
    RuntimeAPI,
    TeamAPI,
    LibraryAPI,
    DiscussionAPI,
    MemoryAPI,
):
    """Master controller managing the overall ATT topology."""

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
        self._agent_registry = AgentRegistry(self)
        self.agents = self._agent_registry.active_by_name
        self._agents_by_id = self._agent_registry.by_id
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
        self.library_permissions: Dict[
            str, Dict[str, Dict[str, str]]
        ] = {}  # lib_id -> path -> team_id -> permission
        self.library_links: Dict[str, Dict[str, Dict[str, str]]] = {}
        self._library_files: Dict[str, Dict[str, str]] = {}
        self._library_service = LibraryService(self)
        self._lifecycle = LifecycleService(self)
        self._discussion = DiscussionCoordinator(self)
        self._failover = FailoverService(self)
        self._membership = MembershipService(self)
        self._migration = MigrationService(self)
        self._runtime = RuntimeRegistry(self)
        self._team_creation = TeamCreationService(self)

        # Public Tool registries
        self.global_tools: Dict[str, Tool] = {}

        self._topology = TopologyService(self)
        self._team_parent_map = self._topology.parent_map
        self._topology_lock = self._topology.lock
        self._snapshot_lock = threading.RLock()
        self._runtime_gate = asyncio.Lock()
        self._starting_invocations = 0
        self._active_invocations = 0
        self._state_version = 0
        self._snapshots = SnapshotBuilder(self)
        self._restore = RestoreService(self)
        self._state_validator = StateValidator(self)
        self._communication_validator = CommunicationStateValidator(self)
        self._state = StateCoordinator(self, db_path)
        self._persistence = self._state.persistence
        self._persistence_batch = self._state.batch
        self._active_tool_agent: contextvars.ContextVar[Optional[Agent]] = contextvars.ContextVar(
            f"att_active_tool_agent_{id(self)}", default=None
        )
        self._active_team: contextvars.ContextVar[Optional[AgentTeam]] = contextvars.ContextVar(
            f"att_active_team_{id(self)}", default=None
        )
        self._active_discussion_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
            f"att_active_discussion_{id(self)}", default=None
        )
        self._active_tool_invocation_id: contextvars.ContextVar[Optional[str]] = (
            contextvars.ContextVar(f"att_active_tool_invocation_{id(self)}", default=None)
        )
        self._active_agent_turn_id: contextvars.ContextVar[Optional[str]] = (
            contextvars.ContextVar(f"att_active_agent_turn_{id(self)}", default=None)
        )
        self._active_round_number: contextvars.ContextVar[Optional[int]] = (
            contextvars.ContextVar(f"att_active_round_{id(self)}", default=None)
        )
        self._memory_internal_operation: contextvars.ContextVar[bool] = (
            contextvars.ContextVar(f"att_memory_internal_{id(self)}", default=False)
        )
        self._memory = MemoryService(self)
        self._alerts = AlertService(self)
        self._unknown_audit_wakeups = self._alerts.active_wakeups
        self._emergency_tasks = self._alerts.emergency_tasks
        self.deferred_emergency_tasks = self._alerts.deferred_emergency_tasks
        self._llm_tasks: set[asyncio.Task[Any]] = set()
        self._closing = False
        self._closed = False
        self._callbacks = CallbackDispatcher(self)

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
                    ("Arbitrator", "Synthesizes the final decision."),
                ],
            }
        }
        if _restore_mode:
            self.agents[root_ai.name] = root_ai
            self._agents_by_id[root_ai.agent_id] = root_ai
        else:
            self.register_agent(root_ai, auto_save=False)
            self._memory.record_event(
                "agent_registered",
                agent=root_ai,
                payload={"lifecycle_state": "active"},
                persist=False,
                inherit_context=False,
            )
