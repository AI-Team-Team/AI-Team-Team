import os
import shutil
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
    ):
        self.lib_id = lib_id
        self.name = name
        self.owner_team_id = owner_team_id
        self.description = description
        self.is_public_visible = is_public_visible
        self._on_change = on_change
        self._suppress_notifications = False
        
        # Locate the files under a managed directory
        if root_dir is None:
            base_dir = ".att_doc_libs"
        else:
            base_dir = os.path.join(root_dir, ".att_doc_libs")
        self.root_dir = os.path.abspath(os.path.join(base_dir, lib_id))            
        os.makedirs(self.root_dir, exist_ok=True)
        self.gated_reader = GatedFileReader()

    def write_file(self, path: str, content: str) -> None:
        """Writes content to a file path within the library. Creates directories if necessary."""
        normalized_path = self._normalize_path(path, allow_root=False)
        safe_path = self._resolve_path(normalized_path, allow_root=False)
        os.makedirs(os.path.dirname(safe_path), exist_ok=True)
        with open(safe_path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info(f"Written file '{path}' in library '{self.lib_id}'.")
        self._notify_change(normalized_path, content)

    def read_file(self, path: str, start_line: int = 1, end_line: Optional[int] = None) -> str:
        """Reads a file path within the library, routing through GatedFileReader."""
        safe_path = self._resolve_path(path, allow_root=False)
        if not os.path.exists(safe_path):
            return f"Error: File '{path}' does not exist in library '{self.lib_id}'."
        return self.gated_reader.read_file(safe_path, start_line=start_line, end_line=end_line)

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
        """Atomically replaces local library contents during state restoration."""
        self._suppress_notifications = True
        try:
            shutil.rmtree(self.root_dir, ignore_errors=True)
            os.makedirs(self.root_dir, exist_ok=True)
            for path, content in files.items():
                self.write_file(path, content)
        finally:
            self._suppress_notifications = False

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
        return resolved

    def _notify_change(self, path: str, content: Optional[str]) -> None:
        if (
            not self._suppress_notifications
            and self._on_change is not None
        ):
            self._on_change(self.lib_id, path, content)
