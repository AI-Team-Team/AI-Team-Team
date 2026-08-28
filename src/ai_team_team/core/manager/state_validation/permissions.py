"""ACL and managed-link validation for restored state."""

from typing import Any, Dict, Set

from ...exceptions import StateRestoreError


def validate_permissions_and_links(
    manager: Any,
    state: Dict[str, Any],
    permissions: Dict[str, Any],
    library_id_set: Set[str],
    library_kind_by_id: Dict[str, str],
    files_by_library: Dict[str, Dict[str, str]],
    team_id_set: Set[str],
) -> None:
    """Validate restored ACL entries and every managed-link target chain."""
    _validate_permissions(
        manager,
        permissions,
        library_id_set,
        library_kind_by_id,
        team_id_set,
    )
    _validate_links(
        manager,
        state,
        library_id_set,
        library_kind_by_id,
        files_by_library,
    )


def _validate_permissions(
    manager: Any,
    permissions: Dict[str, Any],
    library_id_set: Set[str],
    library_kind_by_id: Dict[str, str],
    team_id_set: Set[str],
) -> None:
    for lib_id, path_map in permissions.items():
        if lib_id not in library_id_set:
            raise StateRestoreError(f"Permissions reference missing DocLib {lib_id!r}.")
        if library_kind_by_id[lib_id] != "team" and path_map:
            raise StateRestoreError(f"Private DocLib {lib_id!r} cannot have team ACL entries.")
        for path, team_map in path_map.items():
            manager.normalize_library_path(path)
            for team_id, permission in team_map.items():
                if team_id not in team_id_set:
                    raise StateRestoreError(f"Permissions reference missing team {team_id!r}.")
                if permission not in {"READ", "WRITE"}:
                    raise StateRestoreError(f"Invalid DocLib permission {permission!r}.")


def _validate_links(
    manager: Any,
    state: Dict[str, Any],
    library_id_set: Set[str],
    library_kind_by_id: Dict[str, str],
    files_by_library: Dict[str, Dict[str, str]],
) -> None:
    normalized_links = manager._normalized_library_links(state.get("links", {}))
    for source_lib_id, path_map in normalized_links.items():
        if source_lib_id not in library_id_set:
            raise StateRestoreError(f"Link references missing source DocLib {source_lib_id!r}.")
        if library_kind_by_id[source_lib_id] != "team" and path_map:
            raise StateRestoreError(
                f"Private DocLib {source_lib_id!r} cannot contain managed links."
            )
        for source_path, target in path_map.items():
            target_lib_id = target["target_lib_id"]
            if target_lib_id not in library_id_set:
                raise StateRestoreError(f"Link references missing target DocLib {target_lib_id!r}.")
            if library_kind_by_id[target_lib_id] != "team":
                raise StateRestoreError(
                    f"Managed links cannot target private DocLib {target_lib_id!r}."
                )
            if source_lib_id == target_lib_id:
                raise StateRestoreError("Managed links must target another DocLib.")
            if source_path in files_by_library[source_lib_id]:
                raise StateRestoreError(
                    f"Link path {source_lib_id}:{source_path} collides with a file."
                )
            _validate_link_chain(
                normalized_links,
                files_by_library,
                source_lib_id,
                source_path,
            )


def _validate_link_chain(
    normalized_links: Dict[str, Dict[str, Dict[str, str]]],
    files_by_library: Dict[str, Dict[str, str]],
    source_lib_id: str,
    source_path: str,
) -> None:
    visited = set()
    node = (source_lib_id, source_path)
    while True:
        if node in visited:
            raise StateRestoreError(f"Managed DocLib link cycle detected at {node!r}.")
        visited.add(node)
        link = normalized_links.get(node[0], {}).get(node[1])
        if link is None:
            if node[1] not in files_by_library.get(node[0], {}):
                raise StateRestoreError(f"Managed link resolves to missing file {node!r}.")
            return
        node = (link["target_lib_id"], link["target_path"])
