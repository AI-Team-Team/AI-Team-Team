"""Read-only directory tools for any active ordinary Agent invocation."""

from typing import Annotated, Any, Dict, List, Optional

from pydantic import Field

from ..core.discovery import (
    EntityDirectoryRecord,
    EntityDiscoveryResult,
    EntitySelection,
    EntityType,
)
from ..core.exceptions import ToolArgumentError, ToolBusinessError, ToolPermissionError
from .contract import Tool


def build_discovery_tools(manager: Any) -> Dict[str, Tool]:
    def require_actor():
        actor = manager._active_tool_agent.get() if manager is not None else None
        if (
            actor is None
            or manager._agents_by_id.get(actor.agent_id) is not actor
            or actor.lifecycle_state != "active"
            or manager.supervisor.is_supervisory_agent(actor.agent_id)
        ):
            raise ToolPermissionError(
                "Entity discovery requires an active ordinary Agent invocation."
            )

    # These wrappers are async so Tool does not move live-directory capture to
    # a worker thread. No suspension splits the selected directory snapshot.
    async def list_entities(
        entity_type: EntitySelection = "all",
        start_index: Annotated[int, Field(ge=1)] = 1,
        end_index: Optional[Annotated[int, Field(ge=1)]] = None,
    ) -> EntityDiscoveryResult:
        """Lists public Agents or AgentTeams alphabetically; inclusive entity positions default to 30 results."""
        require_actor()
        try:
            return manager.list_entities(entity_type, start_index, end_index)
        except ValueError as exc:
            raise ToolArgumentError(str(exc)) from exc

    async def search_entities(
        keywords: Annotated[List[str], Field(min_length=1)],
        entity_type: EntitySelection = "all",
        start_index: Annotated[int, Field(ge=1)] = 1,
        end_index: Optional[Annotated[int, Field(ge=1)]] = None,
    ) -> EntityDiscoveryResult:
        """Searches public directory fields by nonblank keywords using case-insensitive OR substrings; paginates matching entities."""
        require_actor()
        try:
            return manager.search_entities(keywords, entity_type, start_index, end_index)
        except ValueError as exc:
            raise ToolArgumentError(str(exc)) from exc

    async def inspect_entity(
        entity_type: EntityType, entity_id: Annotated[str, Field(min_length=1)]
    ) -> EntityDirectoryRecord:
        """Inspects the latest public Agent or AgentTeam record by stable ID; discovery grants no additional permissions."""
        require_actor()
        try:
            return manager.inspect_entity(entity_type, entity_id)
        except ValueError as exc:
            raise ToolArgumentError(str(exc)) from exc
        except KeyError as exc:
            raise ToolBusinessError(exc.args[0]) from exc

    return {
        function.__name__: Tool(function, memory_capture="content", retry_safe=True)
        for function in (list_entities, search_entities, inspect_entity)
    }
