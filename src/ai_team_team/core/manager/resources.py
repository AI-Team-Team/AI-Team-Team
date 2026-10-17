"""Generation leases for managed resources; never held over external awaits."""

import threading
import contextvars
from dataclasses import dataclass
from typing import Any
from pathlib import Path
from contextlib import contextmanager

from ..exceptions import StateRestoreError


@dataclass
class ExecutionAuthority:
    """A revocable local capability, shared by inherited executor contexts."""

    generation: int
    parent: "ExecutionAuthority | None" = None
    active: bool = True


@dataclass
class AcceptedResourceOperation:
    library: Any
    active: bool = True


class ResourceGate:
    """Reject stale objects and refuse publication while managed IO is active."""

    def __init__(self, manager):
        self.manager = manager
        self.generation = 1
        self._lock = threading.RLock()
        self._active = 0
        self._blocked = False
        self._closed = False
        self._authority = contextvars.ContextVar(f"att_execution_authority_{id(self)}", default=None)
        self._operations = contextvars.ContextVar(f"att_resource_operations_{id(self)}", default=())

    def check_authority(self):
        """Reject newly initiated operations from an ended or cancelled executor."""
        with self._lock:
            authority = self._authority.get()
            while authority is not None:
                if not authority.active or authority.generation != self.generation:
                    raise PermissionError("The captured tool execution authority is no longer active.")
                authority = authority.parent

    @contextmanager
    def execution(self):
        with self._lock:
            self.check_authority()
            authority = ExecutionAuthority(self.generation, self._authority.get())
        token = self._authority.set(authority)
        try:
            yield authority
        finally:
            self.revoke(authority)
            self._authority.reset(token)

    def revoke(self, authority):
        with self._lock:
            authority.active = False

    @contextmanager
    def settlement(self):
        """Trusted runtime evidence may settle work that was already accepted."""
        token = self._authority.set(None)
        try:
            yield
        finally:
            self._authority.reset(token)

    def bind(self, library):
        library._resource_gate = self
        library._resource_generation = self.generation

    def _validate(self, library, *, accepted=False):
        if not accepted:
            self.check_authority()
        if self._closed or self._blocked or self.manager._restore_in_progress:
            raise RuntimeError("Managed resources are closed or being published.")
        if library._resource_generation != self.generation:
            raise RuntimeError("The managed resource belongs to an obsolete runtime generation.")
        if self.manager.libraries.get(library.lib_id) is not library:
            raise RuntimeError("The document library is no longer registered.")
        if (Path(library.root_dir).parent / ".att-publication.json").exists():
            journal = getattr(self.manager, "_publication_journal", None)
            decision = self.manager._records.index.get(("publication_manifests", (journal.publication_id,))) if journal else None
            if decision is None or decision.values["status"] != "published" or decision.values["target_generation"] != self.generation:
                raise RuntimeError("An unresolved publication must be recovered before managed resource access.")
        actor = self.manager._active_tool_agent.get()
        if actor is not None and (self.manager._agents_by_id.get(actor.agent_id) is not actor or actor.lifecycle_state != "active"):
            raise PermissionError("The captured resource owner is no longer active.")

    def authorize(self, library, method, paths):
        actor = self.manager._active_tool_agent.get()
        if actor is None:
            return  # The host process remains the trusted administrator.
        if library.library_kind == "agent_private":
            if library.owner_agent_id != actor.agent_id:
                raise PermissionError("A private library requires its live owner.")
            return
        team = self.manager._active_team.get()
        if team is None or self.manager.teams.get(team.team_id) is not team or actor not in team.members:
            raise PermissionError("Managed team resources require the captured current membership.")
        permission = "WRITE" if method in {"write_file", "write_file_atomic", "delete_file", "move_file", "replace_all_files"} else "READ"
        for path in paths:
            if not self.manager.check_library_access(team.team_id, library.lib_id, path, permission):
                raise PermissionError("The current document-library ACL no longer permits this operation.")

    @contextmanager
    def operation(self, library):
        with self._lock:
            self._validate(library)
            self._active += 1
        # Only this already-entered physical operation may finish after a local
        # executor cancellation; inherited contexts cannot start another one.
        accepted = AcceptedResourceOperation(library)
        token = self._operations.set((*self._operations.get(), accepted))
        try:
            yield
        finally:
            with self._lock:
                accepted.active = False
                self._active -= 1
            self._operations.reset(token)

    @contextmanager
    def mutation(self):
        """Order short permission/membership changes with final file commits."""
        with self._lock:
            self._check_mutation()
            yield

    def _check_mutation(self):
        self.check_authority()
        if self._closed or self._blocked or self.manager._restore_in_progress:
            raise RuntimeError("Managed resources are closed or being published.")

    @contextmanager
    def topology_mutation(self):
        """Authorize publication with resource-before-topology lock ordering.

        A contended topology lock must not retain the resource lock: executor
        cancellation and shutdown need that lock to revoke waiting writers.
        Retry the pair after waiting without authority, then validate again.
        Internal callers holding topology must already own the resource lock.
        """
        topology = self.manager._topology_lock
        while True:
            self._lock.acquire()
            try:
                self._check_mutation()
                acquired = topology.acquire(blocking=False)
            except BaseException:
                self._lock.release()
                raise
            if acquired:
                break
            self._lock.release()
            # The timeout also lets revoked synchronous executors leave without
            # waiting indefinitely for an unrelated topology reader.
            if topology.acquire(timeout=0.05):
                topology.release()
        try:
            yield
        finally:
            topology.release()
            self._lock.release()

    @contextmanager
    def commit(self, library, method, paths):
        """Validate again at the short destructive filesystem boundary."""
        with self._lock:
            accepted = any(item.library is library and item.active for item in self._operations.get())
            self._validate(library, accepted=accepted)
            self.authorize(library, method, paths)
            yield

    def begin_publication(self):
        with self._lock:
            if self._closed or self._blocked or self._active:
                raise StateRestoreError("Cannot publish state while managed resource operations are active.")
            self._blocked = True

    def finish_publication(self, *, committed, generation=None):
        with self._lock:
            if committed:
                self.generation = max(self.generation + 1, generation or 1)
                for library in self.manager.libraries.values():
                    self.bind(library)
            self._blocked = False

    def fence(self):
        with self._lock:
            self._closed = True
            self.generation += 1

    @property
    def blocked(self):
        return self._blocked
