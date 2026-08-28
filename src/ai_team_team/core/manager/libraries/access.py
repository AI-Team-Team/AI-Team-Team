"""Library operations for LibraryAccessMixin."""

import asyncio
import os
from typing import Optional, Tuple

from ai_team_team.doc_library import DocumentLibrary


class LibraryAccessMixin:
    def check_library_access(
        self, team_id: str, lib_id: str, path: str, required_permission: str
    ) -> bool:
        """
        Checks if a team has the required permission ('READ' or 'WRITE') for a path in a DocLib.
        Owner of the library always has 'WRITE' (which includes 'READ') for all paths.
        """
        if lib_id not in self.manager.libraries:
            return False
        try:
            clean_path = self.manager.normalize_library_path(path)
        except PermissionError:
            return False
        lib = self.manager.libraries[lib_id]
        if lib.library_kind != "team":
            return False
        if lib.owner_team_id == team_id:
            return True

        # Check explicit permissions
        if lib_id not in self.manager.library_permissions:
            return False

        # Find prefix/parent path matches.
        if clean_path == "/":
            parts = ["/"]
        else:
            parts = []
            current = clean_path
            while current and current != "/":
                parts.append(current)
                current = os.path.dirname(current)
            parts.append("/")

        # Check permissions for each segment
        for p in parts:
            if p in self.manager.library_permissions[lib_id]:
                team_perms = self.manager.library_permissions[lib_id][p]
                if team_id in team_perms:
                    perm = team_perms[team_id]
                    if required_permission == "READ":
                        if perm in {"READ", "WRITE"}:
                            return True
                    elif required_permission == "WRITE":
                        if perm == "WRITE":
                            return True
        return False

    @staticmethod
    def normalize_library_path(path: str) -> str:
        """Returns one canonical virtual ACL path or raises on traversal."""
        if not isinstance(path, str) or not path.strip():
            raise PermissionError("Access denied: Empty library paths are not allowed.")
        normalized = DocumentLibrary._normalize_path(path, allow_root=True)
        return "/" if not normalized else f"/{normalized}"

    @staticmethod
    def _normalize_library_file_path(path: str) -> str:
        return DocumentLibrary._normalize_path(path, allow_root=False)

    def _resolve_library_target(
        self,
        team_id: str,
        lib_id: str,
        path: str,
        required_permission: str,
        *,
        initial_visited: Optional[set[Tuple[str, str]]] = None,
    ) -> Tuple[DocumentLibrary, str]:
        """Resolves a managed file-link chain with live ACL checks."""
        current_lib_id = lib_id
        current_path = self.manager._normalize_library_file_path(path)
        visited = set(initial_visited or set())
        while True:
            node = (current_lib_id, current_path)
            if node in visited:
                raise ValueError("Managed DocLib link cycle detected.")
            visited.add(node)
            if current_lib_id not in self.manager.libraries:
                raise FileNotFoundError(f"Document library '{current_lib_id}' not found.")
            if not self.manager.check_library_access(
                team_id,
                current_lib_id,
                current_path,
                required_permission,
            ):
                raise PermissionError(
                    f"Permission denied for {required_permission} on "
                    f"'{current_lib_id}:{current_path}'."
                )
            target = self.manager.library_links.get(current_lib_id, {}).get(current_path)
            if target is None:
                return self.manager.libraries[current_lib_id], current_path
            current_lib_id = target["target_lib_id"]
            current_path = self.manager._normalize_library_file_path(target["target_path"])

    async def create_library_link(
        self,
        team_id: str,
        source_lib_id: str,
        source_path: str,
        target_lib_id: str,
        target_path: str,
    ) -> None:
        """Creates one ACL-aware cross-library file link."""
        if source_lib_id == target_lib_id:
            raise ValueError("Managed links must target another DocLib.")
        source_path = self.manager._normalize_library_file_path(source_path)
        target_path = self.manager._normalize_library_file_path(target_path)
        if (
            source_lib_id not in self.manager.libraries
            or target_lib_id not in self.manager.libraries
        ):
            raise FileNotFoundError("Both source and target DocLibs must be registered.")
        if (
            self.manager.libraries[source_lib_id].library_kind != "team"
            or self.manager.libraries[target_lib_id].library_kind != "team"
        ):
            raise PermissionError("Private DocLibs cannot participate in links.")
        if not self.manager.check_library_access(team_id, source_lib_id, source_path, "WRITE"):
            raise PermissionError("WRITE permission is required for the link path.")
        if source_path in self.manager.library_links.get(source_lib_id, {}):
            raise FileExistsError("A managed link already exists at that path.")
        if await asyncio.to_thread(self.manager.libraries[source_lib_id].path_exists, source_path):
            raise FileExistsError("A physical file already exists at that path.")

        target_library, resolved_target = self.manager._resolve_library_target(
            team_id,
            target_lib_id,
            target_path,
            "READ",
            initial_visited={(source_lib_id, source_path)},
        )
        if not await asyncio.to_thread(target_library.is_file, resolved_target):
            raise FileNotFoundError("Managed links may target existing files only.")
        with self.manager._snapshot_lock:
            self.manager.library_links.setdefault(source_lib_id, {})[source_path] = {
                "target_lib_id": target_lib_id,
                "target_path": target_path,
            }
            self.manager._auto_save(links={source_lib_id})
