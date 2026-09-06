"""DocLib metadata, ACL, file, and managed-link writes."""

from typing import Any, Dict, Iterable, Optional

from ai_team_team.database.models import (
    DocLibFileModel,
    DocLibLinkModel,
    LibraryModel,
    LibraryPermissionModel,
)


class LibraryWriteMixin:
    @staticmethod
    def _write_libraries(session: Any, libraries: Iterable[Dict[str, Any]]) -> None:
        for library in libraries:
            session.merge(
                LibraryModel(
                    lib_id=library["lib_id"],
                    name=library["name"],
                    owner_team_id=library["owner_team_id"],
                    owner_agent_id=library.get("owner_agent_id"),
                    library_kind=library.get("library_kind", "team"),
                    lifecycle_state=library.get("lifecycle_state", "active"),
                    description=library["description"],
                    is_public_visible=int(library["is_public_visible"]),
                )
            )

    @classmethod
    def _write_library_dependencies(
        cls,
        session: Any,
        libraries: Iterable[Dict[str, Any]],
    ) -> None:
        """Inserts a missing private library dependency without updating an existing one."""
        for library in libraries:
            if session.get(LibraryModel, library["lib_id"]) is not None:
                continue
            cls._write_libraries(session, (library,))
            for path, content in library.get("files", {}).items():
                session.add(
                    DocLibFileModel(
                        lib_id=library["lib_id"],
                        path=path,
                        content=content,
                    )
                )

    @staticmethod
    def _write_permissions(
        session: Any,
        permissions: Dict[str, Dict[str, Dict[str, str]]],
    ) -> None:
        for lib_id, path_map in permissions.items():
            session.query(LibraryPermissionModel).filter_by(lib_id=lib_id).delete(
                synchronize_session=False
            )
            for path, team_map in path_map.items():
                for team_id, permission in team_map.items():
                    session.add(
                        LibraryPermissionModel(
                            lib_id=lib_id,
                            path=path,
                            team_id=team_id,
                            permission=permission,
                        )
                    )

    @staticmethod
    def _write_file_changes(
        session: Any, file_changes: Dict[str, Dict[str, Optional[str]]]
    ) -> None:
        for lib_id, changes in file_changes.items():
            for path, content in changes.items():
                session.query(DocLibFileModel).filter_by(lib_id=lib_id, path=path).delete(
                    synchronize_session=False
                )
                if content is not None:
                    session.add(
                        DocLibFileModel(
                            lib_id=lib_id,
                            path=path,
                            content=content,
                        )
                    )

    @staticmethod
    def _write_links(
        session: Any,
        links: Optional[Dict[str, Dict[str, Dict[str, str]]]],
    ) -> None:
        if links is None:
            return
        for source_lib_id, path_map in links.items():
            session.query(DocLibLinkModel).filter_by(source_lib_id=source_lib_id).delete(
                synchronize_session=False
            )
            for source_path, target in path_map.items():
                session.add(
                    DocLibLinkModel(
                        source_lib_id=source_lib_id,
                        source_path=source_path,
                        target_lib_id=target["target_lib_id"],
                        target_path=target["target_path"],
                    )
                )
