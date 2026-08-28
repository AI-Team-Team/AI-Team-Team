"""Library operations for TeamFileMixin."""

import asyncio
import os
from typing import List, Optional


class TeamFileMixin:
    async def read_library_file(
        self,
        team_id: str,
        lib_id: str,
        path: str,
        start_line: int = 1,
        end_line: Optional[int] = None,
    ) -> str:
        library, resolved_path = self.manager._resolve_library_target(team_id, lib_id, path, "READ")
        return await asyncio.to_thread(library.read_file, resolved_path, start_line, end_line)

    async def write_library_file(
        self,
        team_id: str,
        lib_id: str,
        path: str,
        content: str,
    ) -> None:
        library, resolved_path = self.manager._resolve_library_target(
            team_id, lib_id, path, "WRITE"
        )
        await asyncio.to_thread(library.write_file, resolved_path, content)

    async def delete_library_path(self, team_id: str, lib_id: str, path: str) -> str:
        clean_path = self.manager._normalize_library_file_path(path)
        if not self.manager.check_library_access(team_id, lib_id, clean_path, "WRITE"):
            raise PermissionError(f"Permission denied for WRITE on '{lib_id}:{clean_path}'.")
        with self.manager._snapshot_lock:
            link_map = self.manager.library_links.get(lib_id, {})
            if clean_path in link_map:
                del link_map[clean_path]
                self.manager._auto_save(links={lib_id})
                return f"Successfully deleted managed link '{path}' in library '{lib_id}'."
        return await asyncio.to_thread(self.manager.libraries[lib_id].delete_file, clean_path)

    async def list_library_contents(self, team_id: str, lib_id: str, path: str = "/") -> List[str]:
        clean_acl_path = self.manager.normalize_library_path(path)
        if not self.manager.check_library_access(team_id, lib_id, clean_acl_path, "READ"):
            raise PermissionError(f"Permission denied for READ on '{lib_id}:{path}'.")
        clean_dir = "" if clean_acl_path == "/" else clean_acl_path.lstrip("/")
        if clean_dir in self.manager.library_links.get(lib_id, {}):
            raise NotADirectoryError("Managed links are file links only.")
        items = await asyncio.to_thread(self.manager.libraries[lib_id].list_contents, path)
        for source_path, target in self.manager.library_links.get(lib_id, {}).items():
            if os.path.dirname(source_path) != clean_dir:
                continue
            try:
                target_library, target_path = self.manager._resolve_library_target(
                    team_id, lib_id, source_path, "READ"
                )
                if not await asyncio.to_thread(target_library.is_file, target_path):
                    continue
            except (FileNotFoundError, PermissionError, ValueError):
                continue
            items.append(
                f"[LINK] /{source_path} -> {target['target_lib_id']}:{target['target_path']}"
            )
        return sorted(items)

    async def move_library_file(
        self,
        team_id: str,
        lib_id: str,
        source_path: str,
        target_path: str,
        overwrite: bool = False,
    ) -> None:
        """Moves a team-library file after checking both ACL paths."""
        if lib_id not in self.manager.libraries:
            raise FileNotFoundError(f"Document library {lib_id!r} not found.")
        library = self.manager.libraries[lib_id]
        if library.library_kind != "team":
            raise PermissionError("Private DocLibs require private tools.")
        clean_source = self.manager._normalize_library_file_path(source_path)
        clean_target = self.manager._normalize_library_file_path(target_path)
        if not self.manager.check_library_access(team_id, lib_id, clean_source, "WRITE"):
            raise PermissionError("WRITE permission is required on the source path.")
        if not self.manager.check_library_access(team_id, lib_id, clean_target, "WRITE"):
            raise PermissionError("WRITE permission is required on the target path.")
        links = self.manager.library_links.get(lib_id, {})
        if clean_source in links or clean_target in links:
            raise FileExistsError("Managed-link paths cannot be moved or overwritten.")
        async with self.manager.suppress_auto_save():
            await asyncio.to_thread(library.move_file, clean_source, clean_target, overwrite)
