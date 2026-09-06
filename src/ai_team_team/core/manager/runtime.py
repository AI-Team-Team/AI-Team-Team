"""Model, tool, preset, and invocation capability registries."""

import inspect
import os
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

from ai_team_team.tool import Tool

from ..adapters import HandlerClientAdapter
from ..agent import Agent
from ..team import AgentTeam

if TYPE_CHECKING:
    from .facade import ATTManager


class RuntimeRegistry:
    """Owns model bindings, tool registration, tokenization, and capability views."""

    def __init__(self, manager: "ATTManager") -> None:
        self.manager = manager

    def register_tool(
        self,
        name: Any = None,
        description: Optional[str] = None,
        func: Optional[Callable[..., Any]] = None,
        schema: Optional[Any] = None,
        *,
        memory_capture: str = "metadata_only",
    ):
        """Registers a custom utility tool to all teams."""
        manager = self.manager
        tool = Tool(name, description, func, schema, memory_capture=memory_capture)
        manager.global_tools[tool.name] = tool
        # Bind to existing teams
        for team in manager.teams.values():
            team.tools[tool.name] = tool

    def register_tool_auditor(self, tool_name: str, auditor_func: Callable[..., Tuple[bool, str]]):
        """Registers an auditing hook executed before specific tool calls."""
        manager = self.manager
        manager.tool_auditors[tool_name] = auditor_func

    def register_model(
        self,
        name: str,
        config: Dict[str, Any],
        client: Optional[Any] = None,
    ):
        """Registers a unified model configuration (e.g. metadata, type, ai_note)."""
        manager = self.manager
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Model alias must be a non-empty string.")
        if not isinstance(config, dict):
            raise ValueError("Model configuration must be a dictionary.")
        manager.model_configs[name] = dict(config)
        if client is not None:
            manager.register_llm_client(name, client)
        manager._auto_save(configs=True)

    def register_llm_client(self, alias: str, client: Any) -> None:
        """Binds one stable alias to one runtime client identity."""
        manager = self.manager
        if not isinstance(alias, str) or not alias.strip():
            raise ValueError("LLM client alias must be a non-empty string.")
        if client is None:
            raise ValueError("LLM client cannot be None.")
        conflicting = [
            name
            for name, registered in manager.llm_clients.items()
            if registered is client and name != alias
        ]
        if conflicting:
            raise ValueError(
                f"LLM client is already registered as {conflicting[0]!r}; "
                "one client identity may have only one stable alias."
            )
        existing = manager.llm_clients.get(alias)
        if existing is not None and existing is not client:
            raise ValueError(f"LLM client alias {alias!r} is already bound to another client.")
        manager.llm_clients[alias] = client

    def register_generator_handler(self, handler: Callable[..., str]):
        """Registers a global callback handler for generating text from a model alias."""
        manager = self.manager
        manager.generator_handler = handler

    def count_tokens(self, text: str, model_alias: str) -> int:
        """Counts tokens for the given text using tokenizers or falls back to len(text)//4."""
        manager = self.manager
        if not text:
            return 0

        tokenizer_name_or_path = manager.config.model_tokenizer_configs.get(model_alias)
        if not tokenizer_name_or_path:
            tokenizer_name_or_path = manager.config.model_tokenizer_configs.get("default")

        if tokenizer_name_or_path:
            try:
                if not hasattr(manager, "_tokenizer_cache"):
                    manager._tokenizer_cache = {}

                if tokenizer_name_or_path not in manager._tokenizer_cache:
                    from tokenizers import Tokenizer

                    if tokenizer_name_or_path.endswith(".json") and os.path.exists(
                        tokenizer_name_or_path
                    ):
                        tokenizer = Tokenizer.from_file(tokenizer_name_or_path)
                    else:
                        tokenizer = Tokenizer.from_pretrained(tokenizer_name_or_path)
                    manager._tokenizer_cache[tokenizer_name_or_path] = tokenizer

                tokenizer = manager._tokenizer_cache[tokenizer_name_or_path]
                encoded = tokenizer.encode(text)
                return len(encoded.ids)
            except Exception as e:
                manager.logger.warning(
                    f"Tokenizer error for {tokenizer_name_or_path}: {e}. Falling back to character-based heuristic."
                )

        return max(1, len(text) // 4)

    def resolve_model_alias(self, llm_client: Any) -> str:
        """Returns a stable alias or fails instead of collapsing to default."""
        manager = self.manager
        from ..adapters import ManagerDefaultClientAdapter

        if isinstance(llm_client, ManagerDefaultClientAdapter):
            return "default"
        if isinstance(llm_client, HandlerClientAdapter):
            alias = llm_client.model_name
            if llm_client.handler is manager.generator_handler and (
                alias == "default" or alias in manager.model_configs
            ):
                return alias

        aliases = [name for name, client in manager.llm_clients.items() if client is llm_client]
        if len(aliases) == 1:
            return aliases[0]
        if len(aliases) > 1:
            raise ValueError(
                "LLM client identity is registered under multiple aliases: "
                + ", ".join(sorted(aliases))
            )

        model_name = getattr(llm_client, "model_name", None)
        if isinstance(model_name, str) and manager.llm_clients.get(model_name) is llm_client:
            return model_name
        raise ValueError(
            "LLM client has no stable registered alias. Call "
            "register_llm_client(alias, client) before persistence."
        )

    def resolve_runtime_model_alias(self, llm_client: Any) -> str:
        """Resolves operational budgets without making an alias persistable."""
        manager = self.manager
        try:
            return manager.resolve_model_alias(llm_client)
        except ValueError:
            if llm_client is getattr(manager.root_ai, "llm_client", None):
                return "default"
            return "unregistered"

    def register_preset(
        self, name: str, description: str, system_instructions: str, roles: List[Tuple[str, str]]
    ):
        """Registers a custom dynamic committee preset."""
        manager = self.manager
        manager.presets[name] = {
            "description": description,
            "system_instructions": system_instructions,
            "roles": roles,
        }
        manager._auto_save(configs=True)

    def get_preset(self, name: str) -> dict:
        manager = self.manager
        return manager.presets.get(name, manager.presets["generic"])

    def register_tools_context(self, context: Dict[str, Any]):
        """Registers system dependencies/resources context for binding tools to AIs."""
        manager = self.manager
        safe_context = dict(context)
        safe_context.pop("att_manager", None)
        manager.tools_context.update(safe_context)
        manager.tools_context["att_manager"] = manager
        from ai_team_team.tool import get_default_tools

        # Bind generic tools to existing teams
        for team in manager.teams.values():
            team.tools.update(get_default_tools(manager.tools_context, team))
            # Also bind globally registered tools
            team.tools.update(manager.global_tools)

    def get_available_tools(self, team: AgentTeam, agent: Optional[Agent] = None) -> Dict[str, Any]:
        """Returns the invocation-time tool view for one AgentTeam."""
        manager = self.manager
        tools = dict(getattr(team, "tools", {}) or {})
        if (
            not manager.config.enable_dynamic_delegation
            or team.depth >= manager.config.max_delegation_depth
        ):
            tools.pop("dispatch_subagent", None)
        if team.parent_team is None and manager.find_parent_team(team) is None:
            tools.pop("delegate_escalation", None)
        if not manager.config.enable_membership_voting:
            for name in {
                "initiate_membership_vote",
                "cast_vote",
                "retract_membership_vote",
            }:
                tools.pop(name, None)
        manager._memory.ensure_enabled()
        if not manager.config.episodic_memory.enabled:
            for name in {
                "search_memories",
                "recall_memory",
                "keep_memory_in_context",
                "forget_memory",
            }:
                tools.pop(name, None)
        else:
            from ai_team_team.tool.memory import build_memory_tools

            tools.update(build_memory_tools(manager))
        return tools

    def probe_native_tool_capability(
        self,
        client: Any,
        *,
        agent: Optional[Agent] = None,
        team: Optional[AgentTeam] = None,
    ) -> bool:
        """Safely probes a synchronous native-tool capability contract."""
        manager = self.manager
        probe = getattr(client, "supports_native_tool_calling", None)
        if not callable(probe):
            return False
        try:
            result = probe()
            if inspect.isawaitable(result):
                close = getattr(result, "close", None)
                if callable(close):
                    close()
                raise TypeError("supports_native_tool_calling() must be synchronous.")
            if result is True:
                return True
            if result is False:
                return False
            raise TypeError("supports_native_tool_calling() must return a literal boolean.")
        except Exception as exc:
            payload = {
                "agent_id": agent.agent_id if agent else None,
                "team_id": team.team_id if team else None,
                "error_type": type(exc).__name__,
            }
            manager.logger.info(
                "Native tool capability probe failed for Agent %s: %s",
                payload["agent_id"],
                exc,
            )
            manager._emit_callback("on_system_event", "tool_capability_probe_failed", payload)
            return False
