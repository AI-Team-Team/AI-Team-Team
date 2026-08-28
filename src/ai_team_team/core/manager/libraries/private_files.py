"""Library operations for PrivateFileMixin."""

import asyncio
from typing import List, Optional


class PrivateFileMixin:
    async def list_private_files(self, path: str = "/") -> List[str]:
        """Lists the current invocation agent's private workspace."""
        _, library = self.manager._require_private_agent_context()
        return await asyncio.to_thread(library.list_contents, path)

    async def read_private_file(
        self,
        path: str,
        start_line: int = 1,
        end_line: Optional[int] = None,
    ) -> str:
        """Reads private content only for the current invocation agent."""
        _, library = self.manager._require_private_agent_context()
        return await asyncio.to_thread(library.read_file, path, start_line, end_line)

    async def write_private_file(self, path: str, content: str) -> None:
        """Writes private content only for the current invocation agent."""
        _, library = self.manager._require_private_agent_context()
        await asyncio.to_thread(library.write_file, path, content)

    async def delete_private_file(self, path: str) -> str:
        """Deletes private content only for the current invocation agent."""
        _, library = self.manager._require_private_agent_context()
        return await asyncio.to_thread(library.delete_file, path)

    async def move_private_file(
        self,
        source_path: str,
        target_path: str,
        overwrite: bool = False,
    ) -> None:
        """Atomically moves a private file within its owner's workspace."""
        _, library = self.manager._require_private_agent_context()
        async with self.manager.suppress_auto_save():
            await asyncio.to_thread(library.move_file, source_path, target_path, overwrite)

    async def publish_private_file(
        self,
        source_path: str,
        target_path: str,
        overwrite: bool = False,
    ) -> None:
        """Copies one private file to the active team's built-in DocLib."""
        agent, private_library = self.manager._require_private_agent_context()
        team = self.manager._active_team.get()
        if team is None or agent not in team.members:
            raise PermissionError(
                "Publishing requires an active team containing the current agent."
            )
        target_library = team.doc_library
        expected_library = self.manager.libraries.get(f"DL-{team.team_id}")
        if (
            self.manager.teams.get(team.team_id) is not team
            or target_library is None
            or target_library is not expected_library
            or target_library.library_kind != "team"
            or target_library.owner_team_id != team.team_id
        ):
            raise RuntimeError("The active team has no built-in DocLib.")
        clean_source = self.manager._normalize_library_file_path(source_path)
        clean_target = self.manager._normalize_library_file_path(target_path)
        if not self.manager.check_library_access(
            team.team_id, target_library.lib_id, clean_target, "WRITE"
        ):
            raise PermissionError("WRITE permission is required on the target path.")
        if clean_target in self.manager.library_links.get(target_library.lib_id, {}):
            raise FileExistsError("The target path is a managed link and cannot be overwritten.")

        def copy_under_locks() -> None:
            ordered = sorted((private_library, target_library), key=lambda item: item.lib_id)
            with ordered[0]._lock:
                with ordered[1]._lock:
                    if not private_library.is_file(clean_source):
                        raise FileNotFoundError(f"Private file {source_path!r} does not exist.")
                    content = private_library.read_text(clean_source)
                    target_library.write_file_atomic(clean_target, content, overwrite=overwrite)

        await asyncio.to_thread(copy_under_locks)
        self.manager._emit_callback(
            "on_system_event",
            "private_library_published",
            {
                "agent_id": agent.agent_id,
                "team_id": team.team_id,
                "source_library_id": private_library.lib_id,
                "source_path": clean_source,
                "target_library_id": target_library.lib_id,
                "target_path": clean_target,
                "operation": "copy",
                "result": "success",
            },
        )
