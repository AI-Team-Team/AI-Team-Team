"""Invocation-scoped tools for an Agent's optional episodic-memory catalog."""

from typing import Any, Dict, List, Optional

from ..core.exceptions import ToolBusinessError, ToolPermissionError
from .contract import Tool


def build_memory_tools(att_manager: Any) -> Dict[str, Tool]:
    """Builds memory tools only when the optional catalog is enabled."""
    if att_manager is None or not att_manager.config.episodic_memory.enabled:
        return {}

    async def search_memories(
        query: Optional[str] = None,
        tags: Optional[List[str]] = None,
        team_id: Optional[str] = None,
        discussion_id: Optional[str] = None,
        limit: int = 20,
        cursor: Optional[str] = None,
    ) -> Any:
        """Searches the current Agent's own Memory Cards."""
        try:
            return await att_manager._memory.search(
                query=query,
                tags=tags,
                team_id=team_id,
                discussion_id=discussion_id,
                limit=limit,
                cursor=cursor,
            )
        except PermissionError as exc:
            raise ToolPermissionError(str(exc)) from exc
        except Exception as exc:
            raise ToolBusinessError(f"Memory search failed: {exc}") from exc

    async def recall_memory(
        memory_id: str,
        start_line: int = 1,
        end_line: Optional[int] = None,
    ) -> Any:
        """Temporarily recalls one active Memory Card owned by the current Agent."""
        try:
            return await att_manager._memory.recall(
                memory_id, start_line=start_line, end_line=end_line
            )
        except PermissionError as exc:
            raise ToolPermissionError(str(exc)) from exc
        except Exception as exc:
            raise ToolBusinessError(f"Memory recall failed: {exc}") from exc

    async def keep_memory_in_context(
        memory_id: str, note: Optional[str] = None
    ) -> Any:
        """Retains a compact reference after recall in the same Agent turn."""
        try:
            return await att_manager._memory.keep(memory_id, note)
        except PermissionError as exc:
            raise ToolPermissionError(str(exc)) from exc
        except Exception as exc:
            raise ToolBusinessError(f"Memory retention failed: {exc}") from exc

    async def forget_memory(
        memory_id: str, reason: Optional[str] = None
    ) -> Any:
        """Hides one owned Memory Card without changing the system journal."""
        try:
            return await att_manager._memory.forget(memory_id, reason)
        except PermissionError as exc:
            raise ToolPermissionError(str(exc)) from exc
        except Exception as exc:
            raise ToolBusinessError(f"Memory forgetting failed: {exc}") from exc

    return {
        "search_memories": Tool(
            "search_memories",
            "Searches this Agent's own episodic-memory titles, summaries, tags, and provenance.",
            search_memories,
            memory_capture="metadata_only",
        ),
        "recall_memory": Tool(
            "recall_memory",
            "Temporarily recalls a paginated historical memory owned by this Agent.",
            recall_memory,
            memory_capture="metadata_only",
        ),
        "keep_memory_in_context": Tool(
            "keep_memory_in_context",
            "Retains a compact summary or note for a memory recalled earlier in this Agent turn.",
            keep_memory_in_context,
            memory_capture="metadata_only",
        ),
        "forget_memory": Tool(
            "forget_memory",
            "Hides one owned Memory Card without deleting the immutable system journal.",
            forget_memory,
            memory_capture="metadata_only",
        ),
    }
