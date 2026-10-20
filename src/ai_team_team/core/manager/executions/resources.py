"""Cross-owner executor exclusion uses canonical resources, not alias spellings."""

import asyncio
from contextlib import asynccontextmanager

from ai_team_team.core.execution import ResourceClaim
from ai_team_team.doc_library import DocumentLibrary


def conflict(left, right):
    if left.namespace == "global" or right.namespace == "global":
        return left.access != "read" or right.access != "read"
    if (left.namespace, left.resource_id) != (right.namespace, right.resource_id):
        return False
    if left.access == right.access == "read":
        return False
    return (left.path == right.path
            or left.subtree and (not left.path or right.path.startswith(left.path + "/"))
            or right.subtree and (not right.path or left.path.startswith(right.path + "/")))


class ResourceCoordinator:
    def __init__(self):
        self.active = {}
        self.waiting = {}
        self.changed = asyncio.Event()

    def try_claim(self, execution_id, claims):
        if execution_id in self.active:
            if self.active[execution_id] != claims:
                raise ValueError("An accepted resource reservation cannot change its claims.")
            return True
        if any(conflict(left, right) for left in claims for key, held in self.active.items()
               if key != execution_id for right in held):
            return False
        for key, pending in self.waiting.items():
            if key == execution_id:
                break
            if any(conflict(left, right) for left in claims for right in pending):
                return False
        self.active[execution_id] = claims
        return True

    def release(self, execution_id):
        self.active.pop(execution_id, None)
        self.changed.set()

    @asynccontextmanager
    async def hold(self, execution_id, claims):
        self.waiting[execution_id] = claims
        try:
            while True:
                self.changed.clear()
                if self.try_claim(execution_id, claims):
                    break
                await self.changed.wait()
            self.waiting.pop(execution_id, None)
            yield
        finally:
            # The service retains a reservation while a real synchronous
            # callable is still running after its coroutine was cancelled.
            self.waiting.pop(execution_id, None)
            self.changed.set()


def builtin_resources(manager, owner, scope, name, arguments):
    """Resolve both link authority and physical targets before dispatch."""
    claims, sources = [], []
    team_id = getattr(scope, "team_id", None)

    def add(library, path, access, subtree=False):
        path = DocumentLibrary._normalize_path(path, allow_root=True)
        claims.append(ResourceClaim(namespace="library", resource_id=library.lib_id,
                                    path=path, access=access, subtree=subtree))
        if access == "read":
            sources.append({"kind": "library", "lib_id": library.lib_id, "path": path,
                            "scope_team_id": team_id})

    def read_chain(lib_id, path):
        # Resolution validates cycles and ACLs before traversing these records.
        library, resolved = manager._resolve_library_target(team_id, lib_id, path, "READ")
        while True:
            clean = DocumentLibrary._normalize_path(path, allow_root=True)
            sources.append({"kind": "library", "lib_id": lib_id, "path": clean, "scope_team_id": team_id})
            target = manager.library_links.get(lib_id, {}).get(clean)
            if target is None:
                break
            lib_id, path = target["target_lib_id"], target["target_path"]
        add(library, resolved, "read")

    if name in {"read_private_file", "write_private_file", "delete_private_file", "move_private_file", "list_private_files"}:
        library = manager.libraries[owner.private_doc_library_id]
        if name == "move_private_file":
            add(library, arguments["source_path"], "write")
            add(library, arguments["target_path"], "write")
        else:
            add(library, arguments.get("path", "/"),
                "read" if name in {"read_private_file", "list_private_files"} else "write",
                name in {"delete_private_file", "list_private_files"})
    elif name == "publish_private_file":
        library = manager.libraries[owner.private_doc_library_id]
        team = manager.teams.get(team_id)
        if team is None or owner not in team.members:
            raise PermissionError("Publication requires the captured current membership.")
        add(library, arguments["source_path"], "read")
        add(team.doc_library, arguments["target_path"], "write")
    elif name in {"read_library_file", "write_library_file"}:
        access = "READ" if name == "read_library_file" else "WRITE"
        library, path = manager._resolve_library_target(team_id, arguments["lib_id"], arguments["path"], access)
        add(library, path, access.lower())
        if access == "READ":
            read_chain(arguments["lib_id"], arguments["path"])
    elif name == "create_library_link":
        add(manager.libraries[arguments["source_lib_id"]], arguments["source_path"], "write")
        read_chain(arguments["target_lib_id"], arguments["target_path"])
    elif name in {"move_library_file", "delete_library_file", "list_library_files"}:
        library = manager.libraries[arguments["lib_id"]]
        if name == "move_library_file":
            add(library, arguments["source_path"], "write")
            add(library, arguments["target_path"], "write")
        else:
            add(library, arguments.get("path", "/"), "read" if name.startswith("list") else "write", True)
            if name == "list_library_files":
                directory = DocumentLibrary._normalize_path(arguments.get("path", "/"), allow_root=True)
                for source_path in sorted(manager.library_links.get(library.lib_id, {})):
                    if source_path.rpartition("/")[0] != directory:
                        continue
                    try:
                        read_chain(library.lib_id, source_path)
                    except (PermissionError, FileNotFoundError, ValueError):
                        continue
    return tuple(claims), tuple(sources)
