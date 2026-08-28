"""Public ATTManager delegation methods for LibraryAPI."""

from typing import Any, Dict, List, Optional


from ...agent import Agent
from ..libraries import LibraryService


class LibraryAPI:
    def _new_document_library(self, *args: Any, **kwargs: Any) -> Any:
        return self._library_service._new_document_library(*args, **kwargs)

    def _build_document_library(self, *args: Any, **kwargs: Any) -> Any:
        return self._library_service._build_document_library(*args, **kwargs)

    def _on_library_change(self, lib_id: str, path: str, content: Optional[str]) -> None:
        return self._library_service._on_library_change(lib_id, path, content)

    @staticmethod
    def _agent_history(agent: Agent) -> List[Dict[str, Any]]:
        agent.sync_message_history()
        return agent.message_history

    def check_library_access(
        self,
        team_id: str,
        lib_id: str,
        path: str,
        required_permission: str,
    ) -> bool:
        return self._library_service.check_library_access(
            team_id, lib_id, path, required_permission
        )

    @staticmethod
    def normalize_library_path(path: str) -> str:
        return LibraryService.normalize_library_path(path)

    @staticmethod
    def _normalize_library_file_path(path: str) -> str:
        return LibraryService._normalize_library_file_path(path)

    def _resolve_library_target(self, *args: Any, **kwargs: Any) -> Any:
        return self._library_service._resolve_library_target(*args, **kwargs)

    async def create_library_link(
        self,
        team_id: str,
        source_lib_id: str,
        source_path: str,
        target_lib_id: str,
        target_path: str,
    ) -> None:
        await self._library_service.create_library_link(
            team_id,
            source_lib_id,
            source_path,
            target_lib_id,
            target_path,
        )

    async def read_library_file(
        self,
        team_id: str,
        lib_id: str,
        path: str,
        start_line: int = 1,
        end_line: Optional[int] = None,
    ) -> str:
        return await self._library_service.read_library_file(
            team_id, lib_id, path, start_line, end_line
        )

    async def write_library_file(self, team_id: str, lib_id: str, path: str, content: str) -> None:
        await self._library_service.write_library_file(team_id, lib_id, path, content)

    async def delete_library_path(self, team_id: str, lib_id: str, path: str) -> str:
        return await self._library_service.delete_library_path(team_id, lib_id, path)

    async def list_library_contents(self, team_id: str, lib_id: str, path: str = "/") -> List[str]:
        return await self._library_service.list_library_contents(team_id, lib_id, path)

    async def list_private_files(self, path: str = "/") -> List[str]:
        return await self._library_service.list_private_files(path)

    async def read_private_file(
        self,
        path: str,
        start_line: int = 1,
        end_line: Optional[int] = None,
    ) -> str:
        return await self._library_service.read_private_file(path, start_line, end_line)

    async def write_private_file(self, path: str, content: str) -> None:
        await self._library_service.write_private_file(path, content)

    async def delete_private_file(self, path: str) -> str:
        return await self._library_service.delete_private_file(path)

    async def move_private_file(
        self,
        source_path: str,
        target_path: str,
        overwrite: bool = False,
    ) -> None:
        await self._library_service.move_private_file(source_path, target_path, overwrite)

    async def publish_private_file(
        self,
        source_path: str,
        target_path: str,
        overwrite: bool = False,
    ) -> None:
        await self._library_service.publish_private_file(source_path, target_path, overwrite)

    async def move_library_file(
        self,
        team_id: str,
        lib_id: str,
        source_path: str,
        target_path: str,
        overwrite: bool = False,
    ) -> None:
        await self._library_service.move_library_file(
            team_id,
            lib_id,
            source_path,
            target_path,
            overwrite,
        )
