import os
import shutil
import tempfile
import uuid
import logging
from pathlib import PurePosixPath
from typing import Optional, List, Callable, Dict
from .gated_reader import GatedFileReader

logger = logging.getLogger("ATT.DocLib")


class DocumentLibrary:
    """
    Manages a persistent folder of text/code documents for an Agent Team.
    Supports file creation, reading via GatedFileReader, listing, and deletion.
    """
    def __init__(
        self,
        lib_id: str,
        name: str,
        owner_team_id: str,
        description: str = "",
        is_public_visible: bool = False,
        root_dir: Optional[str] = None,
        on_change: Optional[
            Callable[[str, str, Optional[str]], None]
        ] = None,
        storage_dir: Optional[str] = None,
    ):
        self.lib_id = lib_id
        self.name = name
        self.owner_team_id = owner_team_id
        self.description = description
        self.is_public_visible = is_public_visible
        self._on_change = on_change
        self._suppress_notifications = False
        
        # Locate the files under a managed directory
        if storage_dir is not None:
            target_root = os.path.abspath(storage_dir)
        else:
            workspace = os.path.realpath(
                os.path.abspath(root_dir if root_dir is not None else ".")
            )
            base_dir = os.path.join(workspace, ".att_doc_libs")
            if os.path.lexists(base_dir) and os.path.islink(base_dir):
                raise PermissionError(
                    "Access denied: Managed DocLib roots cannot be symlinks."
                )
            target_root = os.path.join(base_dir, lib_id)
        if os.path.lexists(target_root) and os.path.islink(target_root):
            raise PermissionError(
                "Access denied: A DocLib root cannot be a symlink."
            )
        self.root_dir = os.path.abspath(target_root)
        os.makedirs(self.root_dir, exist_ok=True)
        self.gated_reader = GatedFileReader()

    def write_file(self, path: str, content: str) -> None:
        """Writes content to a file path within the library. Creates directories if necessary."""
        normalized_path = self._normalize_path(path, allow_root=False)
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        fd = self._open_file_descriptor(
            normalized_path, flags, create_parents=True
        )
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info(f"Written file '{path}' in library '{self.lib_id}'.")
        self._notify_change(normalized_path, content)

    def read_file(self, path: str, start_line: int = 1, end_line: Optional[int] = None) -> str:
        """Reads a file path within the library, routing through GatedFileReader."""
        normalized_path = self._normalize_path(path, allow_root=False)
        try:
            fd = self._open_file_descriptor(
                normalized_path, os.O_RDONLY, create_parents=False
            )
        except FileNotFoundError:
            return f"Error: File '{path}' does not exist in library '{self.lib_id}'."
        with os.fdopen(fd, "r", encoding="utf-8", errors="ignore") as stream:
            return self.gated_reader.read_stream(
                stream,
                os.path.basename(normalized_path),
                start_line,
                end_line,
            )

    def delete_file(self, path: str) -> str:
        """Deletes a file or directory path within the library."""
        normalized_path = self._normalize_path(path, allow_root=False)
        safe_path = self._resolve_path(normalized_path, allow_root=False)
        if not os.path.exists(safe_path):
            return f"Error: Path '{path}' does not exist in library '{self.lib_id}'."
        
        try:
            if os.path.isdir(safe_path):
                deleted_paths = []
                for root, _, files in os.walk(safe_path):
                    for filename in files:
                        deleted_paths.append(
                            os.path.relpath(
                                os.path.join(root, filename), self.root_dir
                            ).replace(os.sep, "/")
                        )
                shutil.rmtree(safe_path)
                for deleted_path in deleted_paths:
                    self._notify_change(deleted_path, None)
                return f"Successfully deleted directory '{path}' in library '{self.lib_id}'."
            else:
                os.remove(safe_path)
                self._notify_change(normalized_path, None)
                return f"Successfully deleted file '{path}' in library '{self.lib_id}'."
        except Exception as e:
            return f"Error deleting '{path}' in library '{self.lib_id}': {e}"

    def list_contents(self, path: str = "/") -> List[str]:
        """Lists files and directories under a path within the library."""
        try:
            safe_dir = self._resolve_path(path, allow_root=True)
        except Exception as e:
            return [f"Error: {e}"]
            
        if not os.path.exists(safe_dir):
            return []
        if not os.path.isdir(safe_dir):
            # If it's a file, just return it
            rel = os.path.relpath(safe_dir, self.root_dir)
            clean_rel = "/" + rel.replace(os.sep, "/")
            return [f"[FILE] {clean_rel}"]
        
        contents = []
        try:
            for item in os.listdir(safe_dir):
                full_item_path = os.path.join(safe_dir, item)
                if os.path.islink(full_item_path):
                    logger.warning(
                        "Blocked native symlink '%s' in library '%s'.",
                        full_item_path,
                        self.lib_id,
                    )
                    continue
                rel_path = os.path.relpath(full_item_path, self.root_dir)
                clean_rel_path = "/" + rel_path.replace(os.sep, "/")
                if os.path.isdir(full_item_path):
                    contents.append(f"[DIR] {clean_rel_path}")
                else:
                    contents.append(f"[FILE] {clean_rel_path}")
        except Exception as e:
            logger.error(f"Error listing contents of '{path}' in library '{self.lib_id}': {e}")
        return sorted(contents)

    def replace_all_files(self, files: Dict[str, str]) -> None:
        """Stages all content and atomically publishes the completed directory."""
        parent = os.path.dirname(self.root_dir)
        os.makedirs(parent, exist_ok=True)
        staging = tempfile.mkdtemp(prefix=f".{self.lib_id}-stage-", dir=parent)
        backup = os.path.join(parent, f".{self.lib_id}-backup-{uuid.uuid4().hex}")
        moved_old = False
        try:
            staged = DocumentLibrary(
                lib_id=self.lib_id,
                name=self.name,
                owner_team_id=self.owner_team_id,
                description=self.description,
                is_public_visible=self.is_public_visible,
                storage_dir=staging,
            )
            staged._suppress_notifications = True
            for path, content in files.items():
                staged.write_file(path, content)
            if os.path.lexists(self.root_dir):
                if os.path.islink(self.root_dir):
                    raise PermissionError(
                        "Access denied: A DocLib root cannot be a symlink."
                    )
                os.replace(self.root_dir, backup)
                moved_old = True
            os.replace(staging, self.root_dir)
            staging = ""
            if moved_old:
                shutil.rmtree(backup, ignore_errors=True)
        except Exception:
            if moved_old and not os.path.exists(self.root_dir):
                os.replace(backup, self.root_dir)
            raise
        finally:
            if staging and os.path.exists(staging):
                shutil.rmtree(staging, ignore_errors=True)
            if os.path.exists(backup):
                shutil.rmtree(backup, ignore_errors=True)

    @staticmethod
    def _normalize_path(path: str, allow_root: bool) -> str:
        if not isinstance(path, str) or "\x00" in path:
            raise PermissionError("Access denied: Invalid library path.")
        candidate = path.replace("\\", "/").strip()
        if candidate == "":
            raise PermissionError(
                "Access denied: Empty library paths are not allowed."
            )
        if candidate.strip("/") == "":
            if allow_root:
                return ""
            raise PermissionError("Access denied: Library root is not a file target.")
        parts = PurePosixPath(candidate.lstrip("/")).parts
        if not parts or any(part in {"", ".", ".."} for part in parts):
            raise PermissionError("Access denied: Path traversal attempted.")
        return "/".join(parts)

    def _resolve_path(self, path: str, allow_root: bool = True) -> str:
        """Sanitizes and resolves target path relative to root_dir to prevent directory traversal."""
        clean_path = self._normalize_path(path, allow_root=allow_root)
        resolved = os.path.abspath(os.path.join(self.root_dir, clean_path))
        try:
            if os.path.commonpath([self.root_dir, resolved]) != self.root_dir:
                raise PermissionError("Access denied: Path traversal attempted.")
        except Exception:
            raise PermissionError("Access denied: Path traversal attempted.")
        self._reject_native_symlinks(clean_path)
        return resolved

    def _reject_native_symlinks(self, clean_path: str) -> None:
        if os.path.islink(self.root_dir):
            raise PermissionError(
                "Access denied: Native filesystem symlinks are not allowed."
            )
        current = self.root_dir
        for part in PurePosixPath(clean_path).parts:
            current = os.path.join(current, part)
            if os.path.lexists(current) and os.path.islink(current):
                raise PermissionError(
                    "Access denied: Native filesystem symlinks are not allowed."
                )

    def _open_file_descriptor(
        self,
        clean_path: str,
        flags: int,
        *,
        create_parents: bool,
    ) -> int:
        clean_path = self._normalize_path(clean_path, allow_root=False)
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | nofollow
        current_fd = os.open(self.root_dir, directory_flags)
        parts = PurePosixPath(clean_path).parts
        try:
            for part in parts[:-1]:
                if create_parents:
                    try:
                        os.mkdir(part, mode=0o700, dir_fd=current_fd)
                    except FileExistsError:
                        pass
                next_fd = os.open(
                    part, directory_flags, dir_fd=current_fd
                )
                os.close(current_fd)
                current_fd = next_fd
            return os.open(
                parts[-1],
                flags | nofollow,
                0o600,
                dir_fd=current_fd,
            )
        except OSError as exc:
            if exc.errno in {getattr(os, "ELOOP", 62), 40}:
                raise PermissionError(
                    "Access denied: Native filesystem symlinks are not allowed."
                ) from exc
            raise
        finally:
            os.close(current_fd)

    def path_exists(self, path: str) -> bool:
        safe_path = self._resolve_path(path, allow_root=False)
        return os.path.exists(safe_path)

    def is_file(self, path: str) -> bool:
        safe_path = self._resolve_path(path, allow_root=False)
        return os.path.isfile(safe_path)

    def _notify_change(self, path: str, content: Optional[str]) -> None:
        if (
            not self._suppress_notifications
            and self._on_change is not None
        ):
            self._on_change(self.lib_id, path, content)
