"""DocLib ownership and file validation for restored state."""

from typing import Any, Dict, Set, Tuple

from ...exceptions import StateRestoreError
from .payload import StateValidationPayload


def validate_libraries(
    manager: Any,
    payload: StateValidationPayload,
    agent_id_set: Set[str],
    team_id_set: Set[str],
) -> Tuple[Set[str], Dict[str, str], Dict[str, Dict[str, str]]]:
    """Validate DocLib entities and return lookup structures for ACL checks."""
    library_ids = [row.get("lib_id") for row in payload.libraries]
    if None in library_ids or len(library_ids) != len(set(library_ids)):
        raise StateRestoreError("DocLib identifiers are missing or duplicated.")
    library_id_set = set(library_ids)
    library_kind_by_id: Dict[str, str] = {}
    library_row_by_id = {row["lib_id"]: row for row in payload.libraries}
    private_owner_counts = {agent_id: 0 for agent_id in agent_id_set}
    files_by_library: Dict[str, Dict[str, str]] = {}

    for row in payload.libraries:
        lib_id = row["lib_id"]
        _validate_library_id(lib_id)
        kind = row.get("library_kind")
        library_kind_by_id[lib_id] = kind
        if kind == "team":
            _validate_team_library(row, team_id_set)
        elif kind == "agent_private":
            owner_id = _validate_private_library(row, payload, agent_id_set)
            private_owner_counts[owner_id] += 1
        else:
            raise StateRestoreError(f"DocLib {lib_id!r} has invalid kind {kind!r}.")
        files_by_library[lib_id] = _validate_library_files(manager, row)

    _validate_built_in_libraries(team_id_set, library_row_by_id)
    invalid_private_counts = {
        agent_id: count for agent_id, count in private_owner_counts.items() if count != 1
    }
    if invalid_private_counts:
        details = ", ".join(
            f"{agent_id}={count}" for agent_id, count in sorted(invalid_private_counts.items())
        )
        raise StateRestoreError("Every agent must own exactly one private DocLib: " + details)
    return library_id_set, library_kind_by_id, files_by_library


def _validate_library_id(lib_id: object) -> None:
    if (
        not isinstance(lib_id, str)
        or lib_id in {"", ".", ".."}
        or "/" in lib_id
        or "\\" in lib_id
        or "\x00" in lib_id
    ):
        raise StateRestoreError(f"Invalid DocLib identifier {lib_id!r}.")


def _validate_team_library(row: dict, team_id_set: Set[str]) -> None:
    lib_id = row["lib_id"]
    if row.get("owner_team_id") not in team_id_set or row.get("owner_agent_id") is not None:
        raise StateRestoreError(f"Team DocLib {lib_id!r} has invalid ownership.")
    if row.get("lifecycle_state") != "active":
        raise StateRestoreError(f"Team DocLib {lib_id!r} must be active.")


def _validate_private_library(
    row: dict,
    payload: StateValidationPayload,
    agent_id_set: Set[str],
) -> str:
    lib_id = row["lib_id"]
    owner_agent_id = row.get("owner_agent_id")
    if owner_agent_id not in agent_id_set or row.get("owner_team_id") is not None:
        raise StateRestoreError(f"Private DocLib {lib_id!r} has invalid ownership.")
    if lib_id != f"PDL-{owner_agent_id}":
        raise StateRestoreError(f"Private DocLib {lib_id!r} has a non-canonical ID.")
    if row.get("is_public_visible"):
        raise StateRestoreError(f"Private DocLib {lib_id!r} cannot be public.")
    owner_state = next(
        agent_row.get("lifecycle_state")
        for agent_row in payload.agents
        if agent_row.get("agent_id") == owner_agent_id
    )
    if row.get("lifecycle_state") != owner_state:
        raise StateRestoreError(f"Private DocLib {lib_id!r} lifecycle does not match its owner.")
    return owner_agent_id


def _validate_library_files(manager: Any, row: dict) -> Dict[str, str]:
    lib_id = row["lib_id"]
    normalized_files: Dict[str, str] = {}
    for path, content in row.get("files", {}).items():
        clean = manager._normalize_library_file_path(path)
        if clean in normalized_files:
            raise StateRestoreError(f"DocLib {lib_id!r} contains duplicate file path {clean!r}.")
        if not isinstance(content, str):
            raise StateRestoreError(f"DocLib file {lib_id}:{clean} has non-text content.")
        normalized_files[clean] = content
    return normalized_files


def _validate_built_in_libraries(team_id_set: Set[str], library_row_by_id: Dict[str, dict]) -> None:
    for team_id in team_id_set:
        built_in_id = f"DL-{team_id}"
        built_in = library_row_by_id.get(built_in_id)
        if built_in is None:
            raise StateRestoreError(f"Team {team_id!r} is missing its built-in DocLib.")
        if (
            built_in.get("library_kind") != "team"
            or built_in.get("owner_team_id") != team_id
            or built_in.get("owner_agent_id") is not None
        ):
            raise StateRestoreError(f"Team {team_id!r} has an invalid built-in DocLib owner.")
