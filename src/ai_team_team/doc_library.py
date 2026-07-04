import os
import shutil
import logging
from typing import Optional, List
from .gated_reader import GatedFileReader

logger = logging.getLogger("ATT.DocLib")

class DocumentLibrary:
    """
    Manages a persistent folder of text/code documents for an Agent Team.
    Supports file creation, reading via GatedFileReader, listing, and deletion.
    """
    def __init__(self, lib_id: str, name: str, owner_team_id: str, description: str = "", is_public_visible: bool = False, root_dir: Optional[str] = None):
        self.lib_id = lib_id
        self.name = name
        self.owner_team_id = owner_team_id
        self.description = description
        self.is_public_visible = is_public_visible
        
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
        safe_path = self._resolve_path(path)
        os.makedirs(os.path.dirname(safe_path), exist_ok=True)
        with open(safe_path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info(f"Written file '{path}' in library '{self.lib_id}'.")

    def read_file(self, path: str, start_line: int = 1, end_line: Optional[int] = None) -> str:
        """Reads a file path within the library, routing through GatedFileReader."""
        safe_path = self._resolve_path(path)
        if not os.path.exists(safe_path):
            return f"Error: File '{path}' does not exist in library '{self.lib_id}'."
        return self.gated_reader.read_file(safe_path, start_line=start_line, end_line=end_line)

    def delete_file(self, path: str) -> str:
        """Deletes a file or directory path within the library."""
        safe_path = self._resolve_path(path)
        if not os.path.exists(safe_path):
            return f"Error: Path '{path}' does not exist in library '{self.lib_id}'."
        
        try:
            if os.path.isdir(safe_path):
                shutil.rmtree(safe_path)
                return f"Successfully deleted directory '{path}' in library '{self.lib_id}'."
            else:
                os.remove(safe_path)
                return f"Successfully deleted file '{path}' in library '{self.lib_id}'."
        except Exception as e:
            return f"Error deleting '{path}' in library '{self.lib_id}': {e}"

    def list_contents(self, path: str = "/") -> List[str]:
        """Lists files and directories under a path within the library."""
        try:
            safe_dir = self._resolve_path(path)
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

    def _resolve_path(self, path: str) -> str:
        """Sanitizes and resolves target path relative to root_dir to prevent directory traversal."""
        clean_path = path.lstrip("/")
        # Replace backslashes to avoid bypasses on platforms (though OS is mac, standard code checks)
        clean_path = clean_path.replace("\\", "/")
        resolved = os.path.abspath(os.path.join(self.root_dir, clean_path))
        try:
            if os.path.commonpath([self.root_dir, resolved]) != self.root_dir:
                raise PermissionError("Access denied: Path traversal attempted.")
        except Exception:
            raise PermissionError("Access denied: Path traversal attempted.")
        return resolved
