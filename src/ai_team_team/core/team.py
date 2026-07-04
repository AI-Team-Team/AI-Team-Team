import uuid
import asyncio
import logging
import json
import re
import ast
import inspect
from typing import List, Dict, Optional, Tuple, Any, Union
from ai_team_team.tool import Tool
from ai_team_team.doc_library import DocumentLibrary
from .agent import Agent
from .exceptions import ATTException
from .utils import generate_with_retry

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
        self.communication_rules: Dict[str, Any] = {
            "allow_sibling_talk": False,
            "rules": []
        }
        self.logger = logging.getLogger(f"AgentTeam:{self.team_id}")
        self.message_inbox: List[Dict[str, Any]] = []
        self.tools: Dict[str, Tool] = {}
        self._parent_team: Optional['AgentTeam'] = None
        self.migration_count = 0
        self.doc_library: Optional[DocumentLibrary] = None
        self.is_running = False


    @property
    def parent_team(self) -> Optional['AgentTeam']:
        if self._parent_team is not None:
            return self._parent_team
        if isinstance(self.creator, AgentTeam):
            return self.creator
        return None

    @property
    def depth(self) -> int:
        parent = self.parent_team
        return (parent.depth + 1) if parent else 1

    def add_child_team(self, child: 'AgentTeam'):
        self.child_teams.append(child)

    def launch_att(
        self,
        manager: 'ATTManager',
        member_count: int = 3,
        roles_and_presets: Optional[List[Tuple[str, str]]] = None,
        system_instructions: str = "",
        team_purpose: str = "Unspecified team purpose",
        roles_and_models: Optional[Dict[str, str]] = None,
        member_configs: Optional[Dict[str, Dict[str, Any]]] = None,
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
            is_public_visible=is_public_visible,
            initial_docs=initial_docs
        )
        child.chapter_num = self.chapter_num
        return child


    def receive_message(self, message: Dict[str, Any]):
        self.message_inbox.append(message)
        self.logger.info(f"Team {self.team_id} received message of type '{message.get('type')}' from '{message.get('from')}'")
        manager = getattr(self, "manager", None)
        if manager:
            # Check for high-priority alert types and trigger active wakeup if idle
            if message.get("type") in {"child_failure_escalation", "escalation_spawn"}:
                if not self.is_running and getattr(manager.config, "enable_emergency_wakeup", True):
                    self.logger.warning(f"Active wakeup triggered for idle team {self.team_id}")
                    try:
                        asyncio.create_task(manager.execute_emergency_discussion(self, message))
                    except RuntimeError:
                        # In case no event loop is running (e.g. some synchronous test setup)
                        pass
                
                # Check for callback hook
                if getattr(manager, "on_emergency_escalation", None):
                    try:
                        manager.on_emergency_escalation(
                            self.team_id,
                            message.get("type"),
                            message.get("reason") or message.get("objective") or str(message)
                        )
                    except Exception as e:
                        self.logger.error(f"Error in on_emergency_escalation callback: {e}")
            
            manager._auto_save()

    async def execute_reasoning_step(
        self,
        agent: Agent,
        prompt: str,
        system_instruction: str,
        max_steps: int = 5,
        manager: Optional['ATTManager'] = None
    ) -> str:
        """Executes a reasoning step (ReAct or Native tool calling) for a single agent inside the AT."""
        manager = manager if manager is not None else getattr(self, "manager", None)
        if not agent.llm_client:
            return "Error: Agent has no LLM client configured."

        from .exceptions import TokenLimitExceededError

        max_failovers = len(manager.config.model_token_limits) if manager and getattr(manager, 'config', None) else 3
        failover_attempts = 0

        async with agent.lock:
            while True:
                try:
                    # Check if subclass overrides execute_react_step (for legacy support)
                    is_overridden = False
                    try:
                        if hasattr(self, "execute_react_step") and self.execute_react_step.__func__ is not AgentTeam.execute_react_step:
                            is_overridden = True
                    except AttributeError:
                        is_overridden = True
                    if is_overridden:
                        return await self.execute_react_step(
                            agent=agent,
                            prompt=prompt,
                            system_instruction=system_instruction,
                            max_steps=max_steps,
                            manager=manager
                        )

                    from .strategies import TextReactReasoningStrategy, NativeReasoningStrategy

                    mode = manager.config.tool_calling_mode if manager else "auto"
                    if mode == "auto":
                        is_native = False
                        if hasattr(agent.llm_client, "supports_native_tool_calling"):
                            is_native = bool(agent.llm_client.supports_native_tool_calling())
                        
                        if is_native:
                            strategy = NativeReasoningStrategy()
                        else:
                            strategy = TextReactReasoningStrategy()
                    elif mode == "native":
                        strategy = NativeReasoningStrategy()
                    else:
                        strategy = TextReactReasoningStrategy()

                    return await strategy.execute(
                        team=self,
                        agent=agent,
                        prompt=prompt,
                        system_instruction=system_instruction,
                        max_steps=max_steps,
                        manager=manager
                    )
                except TokenLimitExceededError as e:
                    if manager and failover_attempts < max_failovers:
                        swapped = await manager.handle_failover(agent, self, e)
                        if swapped:
                            failover_attempts += 1
                            continue
                    raise e

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
