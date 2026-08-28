"""Persisted state validation for LinkNormalizationMixin."""

from typing import Dict

from ...exceptions import StateRestoreError


class LinkNormalizationMixin:
    def _normalized_library_links(
        self, links: Dict[str, Dict[str, Dict[str, str]]]
    ) -> Dict[str, Dict[str, Dict[str, str]]]:
        manager = self.manager
        normalized: Dict[str, Dict[str, Dict[str, str]]] = {}
        try:
            for source_lib_id, path_map in links.items():
                for source_path, target in path_map.items():
                    clean_source = manager._normalize_library_file_path(source_path)
                    clean_target = manager._normalize_library_file_path(target["target_path"])
                    source_map = normalized.setdefault(source_lib_id, {})
                    if clean_source in source_map:
                        raise ValueError(f"Duplicate normalized link path {clean_source!r}.")
                    source_map[clean_source] = {
                        "target_lib_id": target["target_lib_id"],
                        "target_path": clean_target,
                    }
        except Exception as exc:
            raise StateRestoreError(f"Invalid managed DocLib link metadata: {exc}") from exc
        return normalized
