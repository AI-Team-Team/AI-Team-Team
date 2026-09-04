import uuid
import asyncio
import inspect
import logging
import threading
from typing import TYPE_CHECKING, List, Dict, Optional, Tuple, Any, Union
from ai_team_team.tool import Tool
from ai_team_team.doc_library import DocumentLibrary
from .agent import Agent
from .exceptions import ATTException
from .utils import generate_with_retry

if TYPE_CHECKING:
    from .manager import ATTManager
    from .response import AgentTurnResult

class AgentTeam:
    """Represents a recursive team panel of Agents collaborating to debate/solve goals."""
    def __init__(self, creator: Any, preset_name: str, team_purpose: str = "Unspecified team purpose"):
        self.team_id = f"AT-{uuid.uuid4().hex[:6]}"
        self.creator = creator
        self.preset_name = preset_name
        self.team_purpose = team_purpose
        self.team_progress = "Not started"
        self.proposals: Dict[str, Dict[str, Any]] = {}
        self.chapter_num: Optional[int] = None
        self.status_map: Dict[str, str] = {}
        self.members: List[Agent] = []
        
        self.child_teams: List['AgentTeam'] = []
        self.logger = logging.getLogger(f"AgentTeam:{self.team_id}")
        self.message_inbox: List[Dict[str, Any]] = []
        self.tools: Dict[str, Tool] = {}
        self._parent_team: Optional['AgentTeam'] = None
        self.migration_count = 0
        self.doc_library: Optional[DocumentLibrary] = None
        self.is_running = False
        self._cached_depth: Optional[int] = None
        self._state_lock: Optional[asyncio.Lock] = None
        self._discussion_lock: Optional[asyncio.Lock] = None
        self._status_lock = threading.RLock()
        self._inbox_lock = threading.RLock()

    @property
    def state_lock(self):
        import asyncio
        if self._state_lock is None:
            self._state_lock = asyncio.Lock()
        return self._state_lock

    @property
    def discussion_lock(self):
        """Serializes normal and emergency discussions for this team."""
        if self._discussion_lock is None:
            self._discussion_lock = asyncio.Lock()
        return self._discussion_lock


    @property
    def parent_team(self) -> Optional['AgentTeam']:
        if self._parent_team is not None:
            return self._parent_team
        if isinstance(self.creator, AgentTeam):
            return self.creator
        return None

    @property
    def depth(self) -> int:
        if self._cached_depth is not None:
            return self._cached_depth
        
        d = 1
        curr = self.parent_team
        while curr is not None:
            d += 1
            curr = curr.parent_team
            
        self._cached_depth = d
        return d

    def add_child_team(self, child: 'AgentTeam'):
        if child not in self.child_teams:
            self.child_teams.append(child)

    def invalidate_depth_cache(self, recursive: bool = True) -> None:
        """Clears cached depth for this team and optionally all descendants."""
        self._cached_depth = None
        if recursive:
            for child in self.child_teams:
                child.invalidate_depth_cache(recursive=True)

    def set_status(self, agent_name: str, status: str) -> None:
        """Updates display-only status under a lightweight synchronous lock."""
        with self._status_lock:
            self.status_map[agent_name] = status

    def status_snapshot(self) -> Dict[str, str]:
        """Returns a consistent copy of display-only status."""
        with self._status_lock:
            return dict(self.status_map)

    @property
    def inbox_lock(self) -> threading.RLock:
        """Returns the short-lived lock protecting inbox handoff."""
        return self._inbox_lock

    def launch_att(
        self,
        manager: 'ATTManager',
        member_count: int = 3,
        roles_and_presets: Optional[List[Tuple[str, str]]] = None,
        system_instructions: str = "",
        team_purpose: str = "Unspecified team purpose",
        roles_and_models: Optional[Dict[str, str]] = None,
        member_configs: Optional[Dict[str, Dict[str, Any]]] = None,
        existing_members: Optional[List[Agent]] = None,
        existing_member_ids: Optional[List[str]] = None,
        is_public_visible: bool = False,
        initial_docs: Optional[Dict[str, str]] = None
    ) -> 'AgentTeam':
        """Allows any active team to recursively launch their own child AT."""
        child = manager.create_agent_team(
            creator=self,
            member_count=member_count,
            roles_and_presets=roles_and_presets,
            system_instructions=system_instructions,
            team_purpose=team_purpose,
            roles_and_models=roles_and_models,
            member_configs=member_configs,
            existing_members=existing_members,
            existing_member_ids=existing_member_ids,
            is_public_visible=is_public_visible,
            initial_docs=initial_docs
        )
        child.chapter_num = self.chapter_num
        return child


    def receive_message(self, message: Dict[str, Any]):
        manager = getattr(self, "manager", None)
        if manager and message.get("type") in {
            "audit_unknown_escalation",
            "operational_degraded_escalation",
        }:
            message = manager._merge_durable_alert(self, message)
        else:
            with self._inbox_lock:
                self.message_inbox.append(message)
        self.logger.info(f"Team {self.team_id} received message of type '{message.get('type')}' from '{message.get('from')}'")
        if manager:
            message_type = message.get("type")
            should_wake = message_type in {
                "child_failure_escalation",
                "escalation_spawn",
            }
            skip_audit = False
            if message_type == "audit_unknown_escalation":
                should_wake = (
                    manager.config.audit_unknown_escalation_mode == "wake"
                )
                skip_audit = True
            elif message_type == "operational_degraded_escalation":
                should_wake = (
                    manager.config.operational_degraded_escalation_mode
                    == "wake"
                )
                skip_audit = True

            if should_wake:
                if (
                    not self.is_running
                    and manager.config.enable_emergency_wakeup
                ):
                    manager.schedule_emergency_wakeup(
                        self, message, skip_audit=skip_audit
                    )
                manager._emit_callback(
                    "on_emergency_escalation",
                    self.team_id,
                    message_type,
                    message.get("reason")
                    or message.get("objective")
                    or str(message),
                )
            
            manager._auto_save(inboxes={self.team_id})

    async def execute_reasoning_step(
        self,
        agent: Agent,
        prompt: str,
        system_instruction: str,
        max_steps: int = 5,
        manager: Optional['ATTManager'] = None
    ) -> str:
        """Executes one Agent turn and returns its text-compatible result."""
        result = await self.execute_reasoning_step_detailed(
            agent,
            prompt,
            system_instruction,
            max_steps=max_steps,
            manager=manager,
        )
        return result.text

    async def execute_reasoning_step_detailed(
        self,
        agent: Agent,
        prompt: str,
        system_instruction: str,
        max_steps: int = 5,
        manager: Optional['ATTManager'] = None,
    ) -> "AgentTurnResult":
        """Executes one Agent turn and returns a structured outcome."""
        manager = manager if manager is not None else getattr(self, "manager", None)
        if (
            not isinstance(max_steps, int)
            or isinstance(max_steps, bool)
            or max_steps < 1
        ):
            raise ValueError("max_steps must be a positive integer.")
        from .response import AgentTurnResult, AgentTurnStatus
        from .exceptions import AgentTurnIncompleteError, LLMGenerationError

        def incomplete(kind: str, reason: str) -> AgentTurnResult:
            result = AgentTurnResult(
                agent_id=agent.agent_id,
                team_id=self.team_id,
                discussion_id=(
                    manager._active_discussion_id.get() if manager else None
                ),
                status=AgentTurnStatus.INCOMPLETE,
                error_kind=kind,
                reason=reason,
            )
            policy = (
                manager.config.turn_failure_policy.llm
                if manager
                else "isolate"
            )
            if policy == "abort":
                raise AgentTurnIncompleteError(result)
            return result

        if not agent.llm_client:
            return incomplete(
                "llm_client_missing", "Agent has no LLM client configured."
            )

        from .exceptions import TokenLimitExceededError

        max_failovers = len(manager.config.model_token_limits) if manager and getattr(manager, 'config', None) else 3
        failover_attempts = 0

        invocation = (
            manager.agent_invocation(
                agent,
                allow_runtime=bool(
                    getattr(self, "_runtime_only", False)
                ),
            )
            if manager is not None
            else agent.invocation_guard()
        )
        async with invocation:
            team_token = manager._active_team.set(self) if manager else None
            discussion_token = None
            if manager:
                discussion_id = manager._active_discussion_id.get()
                if discussion_id is None:
                    discussion_id = f"DISC-{uuid.uuid4().hex}"
                discussion_token = manager._active_discussion_id.set(discussion_id)
            try:
                while True:
                    try:
                        is_react_default = (
                            hasattr(self, "execute_react_step")
                            and getattr(
                                self.execute_react_step, "__func__", None
                            )
                            is AgentTeam.execute_react_step
                        )
                        if not is_react_default:
                            custom_result = await self.execute_react_step(
                                agent=agent,
                                prompt=prompt,
                                system_instruction=system_instruction,
                                max_steps=max_steps,
                                manager=manager,
                            )
                            if isinstance(custom_result, AgentTurnResult):
                                return custom_result
                            return AgentTurnResult(
                                agent_id=agent.agent_id,
                                team_id=self.team_id,
                                discussion_id=(
                                    manager._active_discussion_id.get()
                                    if manager
                                    else None
                                ),
                                status=AgentTurnStatus.COMPLETED,
                                answer=str(custom_result),
                            )

                        from .strategies import (
                            NativeReasoningStrategy,
                            TextReactReasoningStrategy,
                        )

                        mode = (
                            manager.config.tool_calling_mode
                            if manager
                            else "auto"
                        )
                        if mode == "auto":
                            native_check = getattr(
                                agent.llm_client,
                                "supports_native_tool_calling",
                                None,
                            )
                            is_native = (
                                manager.probe_native_tool_capability(
                                    agent.llm_client,
                                    agent=agent,
                                    team=self,
                                )
                                if manager
                                else self._probe_native_without_manager(
                                    native_check
                                )
                            )
                            strategy = (
                                NativeReasoningStrategy()
                                if is_native
                                else TextReactReasoningStrategy()
                            )
                        elif mode == "native":
                            strategy = NativeReasoningStrategy()
                        else:
                            strategy = TextReactReasoningStrategy()

                        result = await strategy.execute(
                            team=self,
                            agent=agent,
                            prompt=prompt,
                            system_instruction=system_instruction,
                            max_steps=max_steps,
                            manager=manager,
                        )
                        if (
                            result.status is AgentTurnStatus.INCOMPLETE
                            and manager
                            and manager.config.turn_failure_policy.tool
                            == "abort"
                        ):
                            raise AgentTurnIncompleteError(result)
                        return result
                    except TokenLimitExceededError as e:
                        if manager and failover_attempts < max_failovers:
                            swapped = await manager.handle_failover(agent, self, e)
                            if swapped:
                                failover_attempts += 1
                                if agent.messages and agent.messages[-1].get("role") == "user":
                                    agent.messages.pop()
                                continue
                        return incomplete("token_limit_exhausted", str(e))
                    except LLMGenerationError as exc:
                        return incomplete("llm_generation_failed", str(exc))
            finally:
                if manager and discussion_token is not None:
                    manager._active_discussion_id.reset(discussion_token)
                if manager and team_token is not None:
                    manager._active_team.reset(team_token)

    @staticmethod
    def _probe_native_without_manager(probe: Any) -> bool:
        """Safely probes native capability when no manager can emit events."""
        if not callable(probe):
            return False
        try:
            result = probe()
            if inspect.isawaitable(result):
                close = getattr(result, "close", None)
                if callable(close):
                    close()
                return False
            return result is True
        except Exception:
            return False

    async def execute_react_step(
        self,
        agent: Agent,
        prompt: str,
        system_instruction: str,
        max_steps: int = 5,
        manager: Optional['ATTManager'] = None
    ) -> str:
        """Alias for execute_reasoning_step for backward compatibility with existing tests."""
        return await self.execute_reasoning_step(
            agent=agent,
            prompt=prompt,
            system_instruction=system_instruction,
            max_steps=max_steps,
            manager=manager
        )
