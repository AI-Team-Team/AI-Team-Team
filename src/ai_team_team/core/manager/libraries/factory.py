"""Library operations for LibraryFactoryMixin."""

from typing import Optional

from ai_team_team.doc_library import DocumentLibrary


class LibraryFactoryMixin:
    def _new_document_library(
        self,
        *,
        lib_id: str,
        name: str,
        owner_team_id: Optional[str] = None,
        owner_agent_id: Optional[str] = None,
        library_kind: str = "team",
        lifecycle_state: str = "active",
        description: str,
        is_public_visible: bool,
        storage_dir: Optional[str] = None,
    ) -> DocumentLibrary:
        manager = self.manager
        manager._library_files.setdefault(lib_id, {})
        return manager._build_document_library(
            lib_id=lib_id,
            name=name,
            owner_team_id=owner_team_id,
            owner_agent_id=owner_agent_id,
            library_kind=library_kind,
            lifecycle_state=lifecycle_state,
            description=description,
            is_public_visible=is_public_visible,
            storage_dir=storage_dir,
        )

    def _build_document_library(
        self,
        *,
        lib_id: str,
        name: str,
        owner_team_id: Optional[str] = None,
        owner_agent_id: Optional[str] = None,
        library_kind: str = "team",
        lifecycle_state: str = "active",
        description: str,
        is_public_visible: bool,
        storage_dir: Optional[str] = None,
    ) -> DocumentLibrary:
        """Builds a DocLib without publishing it in manager registries."""
        manager = self.manager
        return DocumentLibrary(
            lib_id=lib_id,
            name=name,
            owner_team_id=owner_team_id,
            owner_agent_id=owner_agent_id,
            library_kind=library_kind,
            lifecycle_state=lifecycle_state,
            description=description,
            is_public_visible=is_public_visible,
            root_dir=manager.config.workspace_root,
            on_change=manager._on_library_change,
            storage_dir=storage_dir,
        )

    def _on_library_change(self, lib_id: str, path: str, content: Optional[str]) -> None:
        manager = self.manager
        with manager._snapshot_lock:
            files = manager._library_files.setdefault(lib_id, {})
            if content is None:
                files.pop(path, None)
            else:
                files[path] = content
            manager._auto_save(
                libraries={lib_id},
                file_changes={lib_id: {path: content}},
            )
        library = manager.libraries.get(lib_id)
        if library is not None and library.library_kind == "agent_private":
            manager._emit_callback(
                "on_system_event",
                "private_library_file_changed",
                {
                    "agent_id": library.owner_agent_id,
                    "library_id": lib_id,
                    "path": path,
                    "operation": "delete" if content is None else "write",
                    "result": "success",
                },
            )
