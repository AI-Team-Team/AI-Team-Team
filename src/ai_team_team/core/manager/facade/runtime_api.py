"""Public ATTManager delegation methods for RuntimeAPI."""

from typing import Any, Callable, Dict, List, Optional, Tuple


from ...agent import Agent
from ...exceptions import TokenLimitExceededError
from ...team import AgentTeam


class RuntimeAPI:
    def register_tool(
        self,
        name: Any = None,
        description: Optional[str] = None,
        func: Optional[Callable[..., Any]] = None,
        schema: Optional[Any] = None,
        *,
        memory_capture: str = "metadata_only",
    ):
        return self._runtime.register_tool(
            name,
            description,
            func,
            schema,
            memory_capture=memory_capture,
        )

    def register_tool_auditor(self, tool_name: str, auditor_func: Callable[..., Tuple[bool, str]]):
        return self._runtime.register_tool_auditor(tool_name, auditor_func)

    def register_model(
        self,
        name: str,
        config: Dict[str, Any],
        client: Optional[Any] = None,
    ):
        return self._runtime.register_model(name, config, client)

    def register_llm_client(self, alias: str, client: Any) -> None:
        return self._runtime.register_llm_client(alias, client)

    def register_generator_handler(self, handler: Callable[..., str]):
        return self._runtime.register_generator_handler(handler)

    def count_tokens(self, text: str, model_alias: str) -> int:
        return self._runtime.count_tokens(text, model_alias)

    def resolve_model_alias(self, llm_client: Any) -> str:
        return self._runtime.resolve_model_alias(llm_client)

    def resolve_runtime_model_alias(self, llm_client: Any) -> str:
        return self._runtime.resolve_runtime_model_alias(llm_client)

    async def handle_failover(
        self, agent: Agent, team: AgentTeam, error: TokenLimitExceededError
    ) -> bool:
        return await self._failover.handle_failover(agent, team, error)

    def register_preset(
        self, name: str, description: str, system_instructions: str, roles: List[Tuple[str, str]]
    ):
        return self._runtime.register_preset(name, description, system_instructions, roles)

    def get_preset(self, name: str) -> dict:
        return self._runtime.get_preset(name)

    def register_tools_context(self, context: Dict[str, Any]):
        return self._runtime.register_tools_context(context)

    def get_available_tools(self, team: AgentTeam, agent: Optional[Agent] = None) -> Dict[str, Any]:
        return self._runtime.get_available_tools(team, agent)

    def probe_native_tool_capability(
        self,
        client: Any,
        *,
        agent: Optional[Agent] = None,
        team: Optional[AgentTeam] = None,
    ) -> bool:
        return self._runtime.probe_native_tool_capability(client, agent=agent, team=team)
