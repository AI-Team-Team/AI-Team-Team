"""State restore workflow for RestorePublicationMixin."""

import os
import shutil
import uuid
from typing import Dict, List, Optional, Tuple

from ai_team_team.doc_library import DocumentLibrary


class RestorePublicationMixin:
    def _publish_staged_libraries(
        self,
        libraries: Dict[str, DocumentLibrary],
        managed_root: str,
    ) -> List[Tuple[str, Optional[str]]]:
        manager = self.manager
        published: List[Tuple[str, Optional[str]]] = []
        try:
            staged_ids = set(libraries)
            for lib_id, old_library in manager.libraries.items():
                final_root = os.path.join(managed_root, lib_id)
                if (
                    lib_id in staged_ids
                    or os.path.abspath(old_library.root_dir) != os.path.abspath(final_root)
                    or not os.path.exists(final_root)
                ):
                    continue
                backup = os.path.join(
                    managed_root,
                    f".{lib_id}-restore-backup-{uuid.uuid4().hex}",
                )
                os.replace(final_root, backup)
                published.append((final_root, backup))
            for lib_id, library in libraries.items():
                final_root = os.path.join(managed_root, lib_id)
                if os.path.lexists(final_root) and os.path.islink(final_root):
                    raise PermissionError(f"DocLib root {final_root!r} is a symbolic link.")
                backup = None
                if os.path.exists(final_root):
                    backup = os.path.join(
                        managed_root,
                        f".{lib_id}-restore-backup-{uuid.uuid4().hex}",
                    )
                    os.replace(final_root, backup)
                published.append((final_root, backup))
                os.replace(library.root_dir, final_root)
                library.root_dir = final_root
            return published
        except Exception:
            manager._rollback_published_libraries(published)
            raise

    def _publish_new_staged_libraries(
        self,
        libraries: Dict[str, DocumentLibrary],
        managed_root: str,
    ) -> List[Tuple[str, Optional[str]]]:
        """Atomically publishes only newly created DocLib directories."""
        manager = self.manager
        published: List[Tuple[str, Optional[str]]] = []
        try:
            for lib_id, library in libraries.items():
                final_root = os.path.join(managed_root, lib_id)
                if os.path.lexists(final_root):
                    raise FileExistsError(f"DocLib storage already exists for {lib_id!r}.")
                os.replace(library.root_dir, final_root)
                library.root_dir = final_root
                published.append((final_root, None))
            return published
        except Exception:
            manager._rollback_published_libraries(published)
            raise

    def _rollback_published_libraries(self, published: List[Tuple[str, Optional[str]]]) -> None:
        manager = self.manager
        for final_root, backup in reversed(published):
            if os.path.exists(final_root):
                shutil.rmtree(final_root, ignore_errors=True)
            if backup and os.path.exists(backup):
                os.replace(backup, final_root)

    def _discard_library_backups(self, published: List[Tuple[str, Optional[str]]]) -> None:
        manager = self.manager
        for _, backup in published:
            if backup:
                shutil.rmtree(backup, ignore_errors=True)
