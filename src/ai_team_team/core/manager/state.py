"""Incremental state batching and authoritative persistence commits."""

import asyncio
import contextvars
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, Dict, Optional

from ai_team_team.database.persistence import PersistenceCoordinator

from ..exceptions import ATTException, StatePersistenceError

if TYPE_CHECKING:
    from ..manager import ATTManager


class StateCoordinator:
    """Owns dirty-state batching and the single-writer persistence queue."""

    def __init__(self, manager: "ATTManager", db_path: Optional[str]) -> None:
        self.manager = manager
        self.persistence = PersistenceCoordinator(db_path)
        self.batch: contextvars.ContextVar[Optional[Dict[str, Any]]] = contextvars.ContextVar(
            f"att_persistence_batch_{id(manager)}", default=None
        )

    @staticmethod
    def _new_dirty_state(full: bool = False) -> Dict[str, Any]:
        return {
            "full": full,
            "configs": full,
            "agents": set(),
            "teams": set(),
            "inboxes": set(),
            "proposals": set(),
            "communication_requests": set(),
            "communication_approvals": set(),
            "communication_agreements": set(),
            "peer_messages": set(),
            "memory_events": set(),
            "memory_segments": set(),
            "memory_cards": set(),
            "memory_references": set(),
            "libraries": set(),
            "permissions": set(),
            "links": set(),
            "file_changes": {},
            "deleted_agents": set(),
            "deleted_libraries": set(),
            "deleted_memory_references": set(),
        }

    @staticmethod
    def _merge_dirty_state(target: Dict[str, Any], source: Dict[str, Any]) -> None:
        target["full"] = target["full"] or source["full"]
        target["configs"] = target["configs"] or source["configs"]
        for key in (
            "agents",
            "teams",
            "inboxes",
            "proposals",
            "libraries",
            "permissions",
            "links",
            "communication_requests",
            "communication_approvals",
            "communication_agreements",
            "peer_messages",
            "memory_events",
            "memory_segments",
            "memory_cards",
            "memory_references",
        ):
            target[key].update(source[key])
        for lib_id, changes in source["file_changes"].items():
            target["file_changes"].setdefault(lib_id, {}).update(changes)
        target["deleted_agents"].update(source["deleted_agents"])
        target["deleted_libraries"].update(source["deleted_libraries"])
        target["deleted_memory_references"].update(
            source["deleted_memory_references"]
        )

    @asynccontextmanager
    async def suppress_auto_save(self):
        """Batches auto-save deltas across nested and concurrent child tasks."""
        parent_batch = self.manager._persistence_batch.get()
        is_root = parent_batch is None
        token = None
        if is_root:
            parent_batch = self.manager._new_dirty_state()
            token = self.manager._persistence_batch.set(parent_batch)
        try:
            yield
        finally:
            if is_root:
                self.manager._persistence_batch.reset(token)
                if self.manager.db_path and self.manager._dirty_state_has_changes(parent_batch):
                    self.manager._submit_dirty_state(parent_batch)

    @staticmethod
    def _dirty_state_has_changes(dirty: Dict[str, Any]) -> bool:
        return bool(
            dirty["full"]
            or dirty["configs"]
            or dirty["communication_requests"]
            or dirty["communication_approvals"]
            or dirty["communication_agreements"]
            or dirty["peer_messages"]
            or dirty["memory_events"]
            or dirty["memory_segments"]
            or dirty["memory_cards"]
            or dirty["memory_references"]
            or dirty["agents"]
            or dirty["teams"]
            or dirty["inboxes"]
            or dirty["proposals"]
            or dirty["libraries"]
            or dirty["permissions"]
            or dirty["links"]
            or dirty["file_changes"]
            or dirty["deleted_agents"]
            or dirty["deleted_libraries"]
            or dirty["deleted_memory_references"]
        )

    def _auto_save(
        self,
        *,
        configs: bool = False,
        agents: Optional[set[str]] = None,
        teams: Optional[set[str]] = None,
        inboxes: Optional[set[str]] = None,
        proposals: Optional[set[str]] = None,
        communication_requests: Optional[set[str]] = None,
        communication_approvals: Optional[set[str]] = None,
        communication_agreements: Optional[set[str]] = None,
        peer_messages: Optional[set[str]] = None,
        memory_events: Optional[set[str]] = None,
        memory_segments: Optional[set[str]] = None,
        memory_cards: Optional[set[str]] = None,
        memory_references: Optional[set[str]] = None,
        libraries: Optional[set[str]] = None,
        permissions: Optional[set[str]] = None,
        links: Optional[set[str]] = None,
        file_changes: Optional[Dict[str, Dict[str, Optional[str]]]] = None,
        full: bool = False,
        deleted_agents: Optional[set[str]] = None,
        deleted_libraries: Optional[set[str]] = None,
        deleted_memory_references: Optional[set[str]] = None,
    ) -> None:
        """Records an immutable incremental state delta for the single writer."""
        if not self.manager.db_path:
            return
        dirty = self.manager._new_dirty_state(full=full)
        dirty["configs"] = configs or full
        dirty["agents"].update(agents or set())
        dirty["teams"].update(teams or set())
        dirty["inboxes"].update(inboxes or set())
        dirty["proposals"].update(proposals or set())
        dirty["communication_requests"].update(communication_requests or set())
        dirty["communication_approvals"].update(communication_approvals or set())
        dirty["communication_agreements"].update(communication_agreements or set())
        dirty["peer_messages"].update(peer_messages or set())
        dirty["memory_events"].update(memory_events or set())
        dirty["memory_segments"].update(memory_segments or set())
        dirty["memory_cards"].update(memory_cards or set())
        dirty["memory_references"].update(memory_references or set())
        dirty["libraries"].update(libraries or set())
        dirty["permissions"].update(permissions or set())
        dirty["links"].update(links or set())
        dirty["deleted_agents"].update(deleted_agents or set())
        dirty["deleted_libraries"].update(deleted_libraries or set())
        dirty["deleted_memory_references"].update(
            deleted_memory_references or set()
        )
        for lib_id, changes in (file_changes or {}).items():
            dirty["file_changes"].setdefault(lib_id, {}).update(changes)

        if not self.manager._dirty_state_has_changes(dirty):
            return
        with self.manager._snapshot_lock:
            self.manager._state_version += 1
        batch = self.manager._persistence_batch.get()
        if batch is not None:
            self.manager._merge_dirty_state(batch, dirty)
            return
        self.manager._submit_dirty_state(dirty)

    async def _commit_dirty_state(self, dirty: Dict[str, Any]) -> None:
        """Commits one authoritative domain delta and propagates write errors."""
        if not self.manager.db_path or not self.manager._dirty_state_has_changes(dirty):
            return
        with self.manager._snapshot_lock:
            self.manager._state_version += 1
            snapshot = self.manager._capture_state_snapshot(dirty)
            future = self.manager._persistence.submit(self.manager.db_path, snapshot)
        wrapped = asyncio.wrap_future(future)
        try:
            await asyncio.shield(wrapped)
        except asyncio.CancelledError:
            # Once an authoritative domain commit is accepted, keep its
            # transaction lock until the exact delta finishes. Cancellation
            # is delivered to the caller only after durability is known.
            await asyncio.shield(wrapped)
            raise
        except ATTException:
            raise
        except Exception as exc:
            raise StatePersistenceError(
                "The authoritative state delta could not be committed."
            ) from exc

    def _submit_dirty_state(self, dirty: Dict[str, Any]) -> None:
        with self.manager._snapshot_lock:
            try:
                snapshot = self.manager._capture_state_snapshot(dirty)
            except Exception as exc:
                snapshot = {"_capture_error": exc}
            self.manager._persistence.submit(self.manager.db_path, snapshot)

    async def save_state(self, path: Optional[str] = None, full: bool = True) -> None:
        """Persists state asynchronously and waits for the write to commit."""
        if self.manager._closing:
            raise RuntimeError("ATTManager is closing and cannot accept saves.")
        target_path = path or self.manager.db_path
        if not target_path:
            return
        await self.manager.flush_state()
        dirty = self.manager._new_dirty_state(full=full)
        if not full:
            dirty["configs"] = True
        with self.manager._snapshot_lock:
            snapshot = self.manager._capture_state_snapshot(dirty)
            future = self.manager._persistence.submit(target_path, snapshot)
        await asyncio.shield(asyncio.wrap_future(future))

    async def flush_state(self) -> None:
        """Waits until every queued state delta has committed."""
        await self.manager._persistence.flush()
