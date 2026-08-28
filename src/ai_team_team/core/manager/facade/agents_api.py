"""Public ATTManager delegation methods for AgentAPI."""

from typing import Any, Optional, Tuple

from ai_team_team.doc_library import DocumentLibrary

from ...agent import Agent


class AgentAPI:
    def register_agent(self, agent: Agent, *, auto_save: bool = True) -> Agent:
        """Registers one stable Agent identity and its private DocLib."""
        return self._agent_registry.register(agent, auto_save=auto_save)

    def get_private_library_id(self, agent_id: str) -> str:
        """Returns the private library associated with an Agent identity."""
        return self._agent_registry.get_private_library_id(agent_id)

    def _require_private_agent_context(self) -> Tuple[Agent, DocumentLibrary]:
        """Resolves private ownership from invocation context."""
        return self._agent_registry.require_private_context()

    async def retire_agent(
        self,
        agent_id: str,
        policy: Optional[str] = None,
        confirm_delete: bool = False,
    ) -> None:
        """Retires one unused Agent under the configured data policy."""
        await self._agent_registry.retire(
            agent_id,
            policy=policy,
            confirm_delete=confirm_delete,
        )

    async def _retire_agent_locked(self, *args: Any, **kwargs: Any) -> Any:
        return await self._agent_registry.retire_locked(*args, **kwargs)

    async def reactivate_agent(self, agent_id: str, model_alias: str) -> Agent:
        """Reactivates a retained or archived identity."""
        return await self._agent_registry.reactivate(agent_id, model_alias)

    async def _reactivate_agent_locked(self, *args: Any, **kwargs: Any) -> Any:
        return await self._agent_registry.reactivate_locked(*args, **kwargs)
