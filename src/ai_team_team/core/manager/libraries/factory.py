"""Library operations for LibraryFactoryMixin."""

from typing import Optional
import asyncio
import os
import shutil
import tempfile
import uuid

from ai_team_team.doc_library import DocumentLibrary


class LibraryFactoryMixin:
    async def create_team_library(self, team, name, description, is_public=False):
        """Provision off-registry and publish with the captured execution lease."""
        manager = self.manager
        workspace = os.path.realpath(os.path.abspath(manager.config.workspace_root))
        lib_id = f"DL-{uuid.uuid4().hex}"

        def provision():
            managed = os.path.join(workspace, ".att_doc_libs")
            if os.path.islink(managed):
                raise PermissionError("A managed library namespace cannot be a symlink.")
            os.makedirs(managed, exist_ok=True)
            staging = tempfile.mkdtemp(prefix=".att-library-stage-", dir=managed)
            published = False
            try:
                library = manager._build_document_library(lib_id=lib_id, name=name, owner_team_id=team.team_id,
                    description=description, is_public_visible=is_public, storage_dir=staging)
                with manager._resources.topology_mutation(), manager._snapshot_lock:
                    if (manager.teams.get(team.team_id) is not team or getattr(team, "_lifecycle_state", "active") != "active"
                            or os.path.realpath(os.path.abspath(manager.config.workspace_root)) != workspace):
                        raise PermissionError("The creating team or workspace changed before library publication.")
                    manager._resources.authorize(team.doc_library, "write_file", ("/",))
                    target = os.path.join(managed, lib_id)
                    if lib_id in manager.libraries or os.path.lexists(target):
                        raise FileExistsError("The reserved library identity is occupied.")
                    os.rename(staging, target)
                    library.root_dir = target
                    manager._resources.bind(library)
                    manager.libraries[lib_id] = library
                    manager._library_files[lib_id] = {}
                    try:
                        manager._auto_save(libraries={lib_id})
                    except BaseException:
                        manager.libraries.pop(lib_id, None)
                        manager._library_files.pop(lib_id, None)
                        os.rename(target, staging)
                        library.root_dir = staging
                        raise
                    published = True
                return library
            finally:
                if not published:
                    shutil.rmtree(staging, ignore_errors=True)

        return await asyncio.to_thread(provision)

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
        library = manager._build_document_library(
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
        manager._resources.bind(library)
        return library

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
