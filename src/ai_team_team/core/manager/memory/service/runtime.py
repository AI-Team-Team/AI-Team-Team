"""Concrete selective episodic-memory service composition."""

import asyncio
import threading
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from ai_team_team.core.memory import (
    AgentMemoryCard,
    AgentMemorySegment,
    RetainedMemoryReference,
    SystemMemoryEvent,
)

from .catalog import MemoryCatalogMixin
from .indexing import MemoryIndexingMixin
from .journal import MemoryJournalMixin
from .state import MemoryStateMixin

if TYPE_CHECKING:
    from ai_team_team.core.manager.facade import ATTManager


class MemoryService(
    MemoryJournalMixin,
    MemoryIndexingMixin,
    MemoryCatalogMixin,
    MemoryStateMixin,
):
    """Owns Agent-keyed memory without deriving ownership from team membership."""

    def __init__(self, manager: "ATTManager") -> None:
        self.manager = manager
        self.events: Dict[str, SystemMemoryEvent] = {}
        self.segments: Dict[str, AgentMemorySegment] = {}
        self.cards: Dict[str, AgentMemoryCard] = {}
        self.references: Dict[str, RetainedMemoryReference] = {}
        self._event_ids_by_turn: Dict[str, List[str]] = {}
        self._card_id_by_turn: Dict[str, str] = {}
        self._recalled_by_turn: Dict[str, set[str]] = {}
        self._sequence = 0
        self._lock = threading.RLock()
        self._queue: Optional[asyncio.Queue[str]] = None
        self._workers: List[asyncio.Task[Any]] = []
        self._queued_segment_ids: set[str] = set()
        self._closing = False
        self._restore_suspended = False
        self._fts_checked = False
        self._fts_sync_active = False
        if manager.config.episodic_memory.enabled:
            self.ensure_enabled(synchronize=False)
