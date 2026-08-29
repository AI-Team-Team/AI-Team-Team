"""Team and private DocLib tools."""

from typing import Any, Dict, Optional

from ..core.exceptions import (
    ToolArgumentError,
    ToolBusinessError,
    ToolError,
    ToolPermissionError,
)
from .context import _resolve_actual_team
from .contract import Tool


def build_library_tools(att_manager: Any, caller_node: Any) -> Dict[str, Tool]:
    async def create_doc_library(name: str, description: str, is_public: bool = False) -> str:
        """Creates a new document library owned by the caller's team. Arguments: name (str), description (str), is_public (bool)"""
        if not att_manager:
            raise ToolBusinessError("ATTManager is not available in tools context.")
        
        caller_team = _resolve_actual_team(caller_node, att_manager)
        if not caller_team:
            raise ToolPermissionError("The active AgentTeam could not be resolved.")
            
        import uuid
        lib_id = f"DL-{uuid.uuid4().hex[:6]}"
        lib = att_manager._new_document_library(
            lib_id=lib_id,
            name=name,
            owner_team_id=caller_team.team_id,
            description=description,
            is_public_visible=is_public,
        )
        att_manager.libraries[lib_id] = lib
        att_manager._auto_save(libraries={lib_id})
        return f"Successfully created document library '{name}' with ID '{lib_id}'."

    async def update_library_metadata(lib_id: str, description: Optional[str] = None, is_public: Optional[bool] = None) -> str:
        """Updates description or visibility of a library owned by the caller's team. Arguments: lib_id (str), description (str, optional), is_public (bool, optional)"""
        if not att_manager:
            raise ToolBusinessError("ATTManager is not available in tools context.")
        if lib_id not in att_manager.libraries:
            raise ToolBusinessError(f"Document library {lib_id!r} was not found.")
            
        lib = att_manager.libraries[lib_id]
        caller_team = _resolve_actual_team(caller_node, att_manager)
        if not caller_team or lib.owner_team_id != caller_team.team_id:
            raise ToolPermissionError(
                f"Permission denied: the active AgentTeam does not own library {lib_id!r}."
            )
            
        if description is not None:
            lib.description = description
        if is_public is not None:
            lib.is_public_visible = is_public
        att_manager._auto_save(libraries={lib_id})
        return f"Successfully updated metadata for library '{lib_id}'."

    async def list_public_libraries() -> str:
        """Lists all document libraries registered as publicly visible. Arguments: none"""
        if not att_manager:
            raise ToolBusinessError("ATTManager is not available in tools context.")
        libs = []
        for lib in att_manager.libraries.values():
            if lib.is_public_visible:
                libs.append(f"- ID: {lib.lib_id} | Name: {lib.name} | Owner: {lib.owner_team_id} | Description: {lib.description}")
        if not libs:
            return "No public document libraries found."
        return "Public Document Libraries:\n" + "\n".join(libs)

    async def grant_library_permission(lib_id: str, path: str, target_team_id: str, permission: str) -> str:
        """Grants permission ('READ' or 'WRITE') to a target team for a path in a library owned by the caller's team. Arguments: lib_id (str), path (str), target_team_id (str), permission (str)"""
        if not att_manager:
            raise ToolBusinessError("ATTManager is not available in tools context.")
        if lib_id not in att_manager.libraries:
            raise ToolBusinessError(f"Document library {lib_id!r} was not found.")
        if target_team_id not in att_manager.teams:
            raise ToolBusinessError(f"Target AgentTeam {target_team_id!r} was not found.")
        if permission not in {"READ", "WRITE"}:
            raise ToolArgumentError("permission must be 'READ' or 'WRITE'.")
            
        lib = att_manager.libraries[lib_id]
        caller_team = _resolve_actual_team(caller_node, att_manager)
        if not caller_team or lib.owner_team_id != caller_team.team_id:
            raise ToolPermissionError(
                f"Permission denied: the active AgentTeam does not own library {lib_id!r}."
            )
            
        try:
            clean_path = att_manager.normalize_library_path(path)
        except PermissionError as exc:
            raise ToolPermissionError(str(exc)) from exc
        if lib_id not in att_manager.library_permissions:
            att_manager.library_permissions[lib_id] = {}
        if clean_path not in att_manager.library_permissions[lib_id]:
            att_manager.library_permissions[lib_id][clean_path] = {}
            
        att_manager.library_permissions[lib_id][clean_path][target_team_id] = permission
        att_manager._auto_save(permissions={lib_id})
        return f"Successfully granted '{permission}' permission for path '{clean_path}' in library '{lib_id}' to team '{target_team_id}'."

    async def revoke_library_permission(lib_id: str, path: str, target_team_id: str) -> str:
        """Revokes all permissions for a target team under a path in a library owned by the caller's team. Arguments: lib_id (str), path (str), target_team_id (str)"""
        if not att_manager:
            raise ToolBusinessError("ATTManager is not available in tools context.")
        if lib_id not in att_manager.libraries:
            raise ToolBusinessError(f"Document library {lib_id!r} was not found.")
            
        lib = att_manager.libraries[lib_id]
        caller_team = _resolve_actual_team(caller_node, att_manager)
        if not caller_team or lib.owner_team_id != caller_team.team_id:
            raise ToolPermissionError(
                f"Permission denied: the active AgentTeam does not own library {lib_id!r}."
            )
            
        try:
            clean_path = att_manager.normalize_library_path(path)
        except PermissionError as exc:
            raise ToolPermissionError(str(exc)) from exc
        if lib_id in att_manager.library_permissions and clean_path in att_manager.library_permissions[lib_id]:
            if target_team_id in att_manager.library_permissions[lib_id][clean_path]:
                del att_manager.library_permissions[lib_id][clean_path][target_team_id]
                att_manager._auto_save(permissions={lib_id})
                return f"Successfully revoked permissions for path '{clean_path}' in library '{lib_id}' for team '{target_team_id}'."
        return f"No permissions found for path '{clean_path}' in library '{lib_id}' for team '{target_team_id}'."

    async def create_library_link(
        source_lib_id: str,
        source_path: str,
        target_lib_id: str,
        target_path: str,
    ) -> str:
        """Creates an ACL-aware cross-DocLib file link."""
        if not att_manager:
            raise ToolBusinessError("ATTManager is not available in tools context.")
        caller_team = _resolve_actual_team(caller_node, att_manager)
        if not caller_team:
            raise ToolPermissionError("The active AgentTeam could not be resolved.")
        try:
            await att_manager.create_library_link(
                caller_team.team_id,
                source_lib_id,
                source_path,
                target_lib_id,
                target_path,
            )
            return (
                f"Successfully linked '{source_lib_id}:{source_path}' to "
                f"'{target_lib_id}:{target_path}'."
            )
        except PermissionError as exc:
            raise ToolPermissionError(str(exc)) from exc
        except Exception as exc:
            raise ToolBusinessError(
                f"Managed library link creation failed: {exc}"
            ) from exc

    async def write_library_file(lib_id: str, path: str, content: str) -> str:
        """Writes content to a file in a library. Requires 'WRITE' permission. Arguments: lib_id (str), path (str), content (str)"""
        if not att_manager:
            raise ToolBusinessError("ATTManager is not available in tools context.")
        if lib_id not in att_manager.libraries:
            raise ToolBusinessError(f"Document library {lib_id!r} was not found.")
            
        caller_team = _resolve_actual_team(caller_node, att_manager)
        if not caller_team:
            raise ToolPermissionError("The active AgentTeam could not be resolved.")
            
        if not att_manager.check_library_access(caller_team.team_id, lib_id, path, "WRITE"):
            raise ToolPermissionError(
                f"Permission denied: WRITE permission is required for path {path!r} in library {lib_id!r}."
            )
            
        try:
            await att_manager.write_library_file(
                caller_team.team_id, lib_id, path, content
            )
            return f"Successfully written file '{path}' in library '{lib_id}'."
        except PermissionError as exc:
            raise ToolPermissionError(str(exc)) from exc
        except Exception as exc:
            raise ToolBusinessError(
                f"Writing path {path!r} in library {lib_id!r} failed: {exc}"
            ) from exc

    async def read_library_file(lib_id: str, path: str, start_line: int = 1, end_line: Optional[int] = None) -> str:
        """Reads a file chunk from a library. Requires 'READ' permission. Arguments: lib_id (str), path (str), start_line (int, default 1), end_line (int, optional)"""
        if not att_manager:
            raise ToolBusinessError("ATTManager is not available in tools context.")
        if lib_id not in att_manager.libraries:
            raise ToolBusinessError(f"Document library {lib_id!r} was not found.")
            
        caller_team = _resolve_actual_team(caller_node, att_manager)
        if not caller_team:
            raise ToolPermissionError("The active AgentTeam could not be resolved.")
            
        if not att_manager.check_library_access(caller_team.team_id, lib_id, path, "READ"):
            raise ToolPermissionError(
                f"Permission denied: READ permission is required for path {path!r} in library {lib_id!r}."
            )
            
        try:
            content = await att_manager.read_library_file(
                caller_team.team_id,
                lib_id,
                path,
                start_line,
                end_line,
            )
            if content.startswith("Error: "):
                raise ToolBusinessError(content.removeprefix("Error: "))
            return content
        except ToolError:
            raise
        except PermissionError as exc:
            raise ToolPermissionError(str(exc)) from exc
        except Exception as exc:
            raise ToolBusinessError(
                f"Reading path {path!r} in library {lib_id!r} failed: {exc}"
            ) from exc

    async def delete_library_file(lib_id: str, path: str) -> str:
        """Deletes a file or directory in a library. Requires 'WRITE' permission. Arguments: lib_id (str), path (str)"""
        if not att_manager:
            raise ToolBusinessError("ATTManager is not available in tools context.")
        if lib_id not in att_manager.libraries:
            raise ToolBusinessError(f"Document library {lib_id!r} was not found.")
            
        caller_team = _resolve_actual_team(caller_node, att_manager)
        if not caller_team:
            raise ToolPermissionError("The active AgentTeam could not be resolved.")
            
        if not att_manager.check_library_access(caller_team.team_id, lib_id, path, "WRITE"):
            raise ToolPermissionError(
                f"Permission denied: WRITE permission is required for path {path!r} in library {lib_id!r}."
            )
            
        try:
            result = await att_manager.delete_library_path(
                caller_team.team_id, lib_id, path
            )
            if result.startswith("Error: "):
                raise ToolBusinessError(result.removeprefix("Error: "))
            return result
        except ToolError:
            raise
        except PermissionError as exc:
            raise ToolPermissionError(str(exc)) from exc
        except Exception as exc:
            raise ToolBusinessError(
                f"Deleting path {path!r} in library {lib_id!r} failed: {exc}"
            ) from exc

    async def list_library_files(lib_id: str, path: str = "/") -> str:
        """Lists files and directories under a path in a library. Requires 'READ' permission. Arguments: lib_id (str), path (str, default '/')"""
        if not att_manager:
            raise ToolBusinessError("ATTManager is not available in tools context.")
        if lib_id not in att_manager.libraries:
            raise ToolBusinessError(f"Document library {lib_id!r} was not found.")
            
        caller_team = _resolve_actual_team(caller_node, att_manager)
        if not caller_team:
            raise ToolPermissionError("The active AgentTeam could not be resolved.")
            
        if not att_manager.check_library_access(caller_team.team_id, lib_id, path, "READ"):
            raise ToolPermissionError(
                f"Permission denied: READ permission is required for path {path!r} in library {lib_id!r}."
            )
            
        try:
            items = await att_manager.list_library_contents(
                caller_team.team_id, lib_id, path
            )
            if not items:
                return f"Library '{lib_id}' path '{path}' is empty or not a directory."
            return f"Contents of library '{lib_id}' path '{path}':\n" + "\n".join(items)
        except PermissionError as exc:
            raise ToolPermissionError(str(exc)) from exc
        except Exception as exc:
            raise ToolBusinessError(
                f"Listing path {path!r} in library {lib_id!r} failed: {exc}"
            ) from exc

    async def list_private_files(path: str = "/") -> str:
        """Lists the current AI's private files. Arguments: path (str)."""
        if not att_manager:
            raise ToolBusinessError("ATTManager is not available in tools context.")
        try:
            items = await att_manager.list_private_files(path)
            return "Private workspace is empty." if not items else "\n".join(items)
        except PermissionError as exc:
            raise ToolPermissionError(str(exc)) from exc
        except Exception as exc:
            raise ToolBusinessError("Private file listing failed.") from exc

    async def read_private_file(
        path: str,
        start_line: int = 1,
        end_line: Optional[int] = None,
    ) -> str:
        """Reads one private file for the current AI."""
        if not att_manager:
            raise ToolBusinessError("ATTManager is not available in tools context.")
        try:
            return await att_manager.read_private_file(path, start_line, end_line)
        except PermissionError as exc:
            raise ToolPermissionError(str(exc)) from exc
        except Exception as exc:
            raise ToolBusinessError("Private file reading failed.") from exc

    async def write_private_file(path: str, content: str) -> str:
        """Writes one private file for the current AI."""
        if not att_manager:
            raise ToolBusinessError("ATTManager is not available in tools context.")
        try:
            await att_manager.write_private_file(path, content)
            return f"Successfully wrote private file '{path}'."
        except PermissionError as exc:
            raise ToolPermissionError(str(exc)) from exc
        except Exception as exc:
            raise ToolBusinessError("Private file writing failed.") from exc

    async def delete_private_file(path: str) -> str:
        """Deletes one private file for the current AI."""
        if not att_manager:
            raise ToolBusinessError("ATTManager is not available in tools context.")
        try:
            return await att_manager.delete_private_file(path)
        except PermissionError as exc:
            raise ToolPermissionError(str(exc)) from exc
        except Exception as exc:
            raise ToolBusinessError("Private file deletion failed.") from exc

    async def move_private_file(
        source_path: str,
        target_path: str,
        overwrite: bool = False,
    ) -> str:
        """Moves one private file for the current AI."""
        if not att_manager:
            raise ToolBusinessError("ATTManager is not available in tools context.")
        try:
            await att_manager.move_private_file(
                source_path, target_path, overwrite
            )
            return f"Successfully moved private file to '{target_path}'."
        except PermissionError as exc:
            raise ToolPermissionError(str(exc)) from exc
        except Exception as exc:
            raise ToolBusinessError("Private file move failed.") from exc

    async def publish_private_file(
        source_path: str,
        target_path: str,
        overwrite: bool = False,
    ) -> str:
        """Copies one private file into the current team's built-in DocLib."""
        if not att_manager:
            raise ToolBusinessError("ATTManager is not available in tools context.")
        try:
            await att_manager.publish_private_file(
                source_path, target_path, overwrite
            )
            return f"Successfully published private file to '{target_path}'."
        except FileExistsError as exc:
            raise ToolBusinessError(
                f"The publication target already exists: {exc}. Rename the private source, move or rename the team file with WRITE permission on both paths, or retry with overwrite=true."
            ) from exc
        except PermissionError as exc:
            raise ToolPermissionError(str(exc)) from exc
        except Exception as exc:
            raise ToolBusinessError("Private file publication failed.") from exc

    async def move_library_file(
        lib_id: str,
        source_path: str,
        target_path: str,
        overwrite: bool = False,
    ) -> str:
        """Moves one normal team-library file with source and target ACL checks."""
        if not att_manager:
            raise ToolBusinessError("ATTManager is not available in tools context.")
        caller_team = _resolve_actual_team(caller_node, att_manager)
        if not caller_team:
            raise ToolPermissionError("The active AgentTeam could not be resolved.")
        try:
            await att_manager.move_library_file(
                caller_team.team_id,
                lib_id,
                source_path,
                target_path,
                overwrite,
            )
            return f"Successfully moved library file to '{target_path}'."
        except PermissionError as exc:
            raise ToolPermissionError(str(exc)) from exc
        except Exception as exc:
            raise ToolBusinessError(
                f"Library file move failed: {exc}"
            ) from exc

    return {
        "create_doc_library": Tool(
            "create_doc_library",
            "Creates a new document library owned by the caller's team. Arguments: name (str), description (str), is_public (bool)",
            create_doc_library,
        ),
        "update_library_metadata": Tool(
            "update_library_metadata",
            "Updates description or visibility of a library owned by the caller's team. Arguments: lib_id (str), description (str, optional), is_public (bool, optional)",
            update_library_metadata,
        ),
        "list_public_libraries": Tool(
            "list_public_libraries",
            "Lists all document libraries registered as publicly visible. Arguments: none",
            list_public_libraries,
        ),
        "grant_library_permission": Tool(
            "grant_library_permission",
            "Grants permission ('READ' or 'WRITE') to a target team for a path in a library owned by the caller's team. Arguments: lib_id (str), path (str), target_team_id (str), permission (str)",
            grant_library_permission,
        ),
        "revoke_library_permission": Tool(
            "revoke_library_permission",
            "Revokes all permissions for a target team under a path in a library owned by the caller's team. Arguments: lib_id (str), path (str), target_team_id (str)",
            revoke_library_permission,
        ),
        "create_library_link": Tool(
            "create_library_link",
            "Creates an ACL-aware file link between registered DocLibs. The caller needs WRITE on the source path and READ on the target path. Arguments: source_lib_id (str), source_path (str), target_lib_id (str), target_path (str)",
            create_library_link,
        ),
        "write_library_file": Tool(
            "write_library_file",
            "Writes content to a file in a library. Requires 'WRITE' permission. Arguments: lib_id (str), path (str), content (str)",
            write_library_file,
        ),
        "read_library_file": Tool(
            "read_library_file",
            "Reads a file chunk from a library. Requires 'READ' permission. Arguments: lib_id (str), path (str), start_line (int, default 1), end_line (int, optional)",
            read_library_file,
        ),
        "delete_library_file": Tool(
            "delete_library_file",
            "Deletes a file or directory in a library. Requires 'WRITE' permission. Arguments: lib_id (str), path (str)",
            delete_library_file,
        ),
        "list_library_files": Tool(
            "list_library_files",
            "Lists files and directories under a path in a library. Requires 'READ' permission. Arguments: lib_id (str), path (str, default '/')",
            list_library_files,
        ),
        "list_private_files": Tool(
            "list_private_files",
            "Lists files in the current AI's private workspace. Arguments: path (str, default '/')",
            list_private_files,
        ),
        "read_private_file": Tool(
            "read_private_file",
            "Reads a file from the current AI's private workspace. Arguments: path (str), start_line (int), end_line (int, optional)",
            read_private_file,
        ),
        "write_private_file": Tool(
            "write_private_file",
            "Writes a file in the current AI's private workspace. Arguments: path (str), content (str)",
            write_private_file,
        ),
        "delete_private_file": Tool(
            "delete_private_file",
            "Deletes a file from the current AI's private workspace. Arguments: path (str)",
            delete_private_file,
        ),
        "move_private_file": Tool(
            "move_private_file",
            "Moves a file in the current AI's private workspace. Arguments: source_path (str), target_path (str), overwrite (bool)",
            move_private_file,
        ),
        "publish_private_file": Tool(
            "publish_private_file",
            "Copies a private file to the current team's built-in DocLib. Arguments: source_path (str), target_path (str), overwrite (bool)",
            publish_private_file,
        ),
        "move_library_file": Tool(
            "move_library_file",
            "Moves a normal team-library file after source and target WRITE checks. Arguments: lib_id (str), source_path (str), target_path (str), overwrite (bool)",
            move_library_file,
        ),
    }

