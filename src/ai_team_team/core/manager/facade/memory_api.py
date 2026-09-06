"""Public host APIs for selective episodic memory."""

from typing import TYPE_CHECKING, Any, List, Optional

if TYPE_CHECKING:
    from ..memory import MemoryService


class MemoryAPI:
    _memory: "MemoryService"

    async def flush_memory_indexing(self) -> None:
        """Waits for every currently runnable memory-index job."""
        await self._memory.flush_indexing()

    async def retry_memory_index(self, segment_id: str) -> None:
        """Returns one failed or pending segment to the indexing queue."""
        await self._memory.retry_index(segment_id)

    def list_memory_index_failures(self, agent_id: Optional[str] = None) -> List[Any]:
        """Returns failed index segments, optionally restricted to one Agent."""
        from ...memory import MemoryIndexStatus

        return [
            segment.model_copy(deep=True)
            for segment in self._memory.segments.values()
            if segment.status is MemoryIndexStatus.FAILED
            and (agent_id is None or segment.agent_id == agent_id)
        ]

    async def restore_forgotten_memory(self, agent_id: str, memory_id: str) -> Any:
        """Restores a forgotten card through the trusted host API."""
        return await self._memory.restore_forgotten(agent_id, memory_id)

    def list_agent_history(self, agent_id: str) -> List[Any]:
        """Returns an ordered host-only journal view for one Agent identity."""
        return sorted(
            (
                event.model_copy(deep=True)
                for event in self._memory.events.values()
                if event.agent_id == agent_id
            ),
            key=lambda event: event.sequence,
        )
