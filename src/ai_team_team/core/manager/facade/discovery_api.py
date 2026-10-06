"""Public live-directory APIs, independent of communication and membership."""

from typing import List, Optional

from ...discovery import EntityDirectoryRecord, EntityDiscoveryResult, EntitySelection, EntityType


class DiscoveryAPI:
    def list_entities(
        self,
        entity_type: EntitySelection = "all",
        start_index: int = 1,
        end_index: Optional[int] = None,
    ) -> EntityDiscoveryResult:
        """Lists eligible public directory records in one-based inclusive positions."""
        return self._discovery.list_entities(entity_type, start_index, end_index)

    def search_entities(
        self,
        keywords: List[str],
        entity_type: EntitySelection = "all",
        start_index: int = 1,
        end_index: Optional[int] = None,
    ) -> EntityDiscoveryResult:
        """Searches public fields using case-insensitive OR substring matching."""
        return self._discovery.search_entities(keywords, entity_type, start_index, end_index)

    def inspect_entity(self, entity_type: EntityType, entity_id: str) -> EntityDirectoryRecord:
        """Returns the latest eligible public record, never private entity state."""
        return self._discovery.inspect_entity(entity_type, entity_id)
