"""Public ATTManager delegation methods for StateAPI."""

import asyncio
import contextvars
import os
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, Dict, Optional

from ...agent import Agent
from ...config import ATTConfig
from ...exceptions import StateRestoreError
from ..state import StateCoordinator
from ai_team_team.database.persistence.receipts import settle_commit

if TYPE_CHECKING:
    from .manager import ATTManager


class StateAPI:
    async def __aenter__(self) -> "ATTManager":
        self._callbacks.ensure_worker()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.close()

    @staticmethod
    def _new_dirty_state(full: bool = False, *, provisional: bool = False) -> Dict[str, Any]:
        return StateCoordinator._new_dirty_state(full, provisional=provisional)

    @staticmethod
    def _merge_dirty_state(target: Dict[str, Any], source: Dict[str, Any]) -> None:
        StateCoordinator._merge_dirty_state(target, source)

    @asynccontextmanager
    async def suppress_auto_save(self):
        """Batches auto-save deltas across nested and concurrent tasks."""
        async with self._state.suppress_auto_save():
            yield

    @staticmethod
    def _dirty_state_has_changes(dirty: Dict[str, Any]) -> bool:
        return StateCoordinator._dirty_state_has_changes(dirty)

    def _auto_save(self, *args: Any, **kwargs: Any) -> Any:
        return self._state._auto_save(*args, **kwargs)

    async def _commit_dirty_state(self, dirty: Dict[str, Any]) -> None:
        await self._state._commit_dirty_state(dirty)

    def _submit_dirty_state(self, dirty: Dict[str, Any]) -> None:
        self._state._submit_dirty_state(dirty)

    async def save_state(self, path: Optional[str] = None, full: bool = True) -> None:
        """Persists state asynchronously and waits for commit."""
        await self._state.save_state(path, full)

    async def flush_state(self) -> None:
        """Waits until every queued state delta has committed."""
        await self._state.flush_state()

    async def close(self) -> None:
        """Closes runtime work, callbacks, and persistence resources."""
        if self._closed:
            return
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._lifecycle.close())
        await settle_commit(self._close_task)

    async def load_state(self, path: str) -> None:
        """Restores a versioned state snapshot without blocking the event loop."""
        restoration_start = self._activity.clock.monotonic()
        async with self._runtime_gate:
            if self._closing:
                raise RuntimeError("ATTManager is closing and cannot restore state.")
            if self._restore_in_progress:
                raise StateRestoreError("Another state restoration is already in progress.")
            if self._topology.transition_pending:
                raise StateRestoreError("Cannot restore state while a topology transition is awaiting commit.")
            if self._agent_registry.pending:
                raise StateRestoreError("Cannot restore state while Agent registrations are awaiting membership commit.")
            if self._messaging.read_deliveries:
                raise StateRestoreError("Cannot restore state while a chat read delivery or its receipt cleanup is pending.")
            self._activity.assert_restore_ready()
            if self._active_formation_operations:
                raise StateRestoreError(
                    "Cannot restore state while a team formation operation is active."
                )
            if any(not task.done() for task in self._formations.tasks):
                raise StateRestoreError(
                    "Cannot restore state while detached team-formation work is active."
                )
            if not os.path.exists(path):
                raise FileNotFoundError(f"State database file '{path}' not found.")
            self._restore_in_progress = True
            self._restore_source_path = path
            try:
                self._resources.begin_publication()
                await self._memory.suspend_for_restore()
                # Reject corrupt references and missing host bindings before
                # crash reconciliation is allowed to rename any directories.
                state = await self._persistence.read(path, reconcile=False)
                await asyncio.to_thread(self._validate_state_snapshot, state)
                state = await self._persistence.read(path)
                # The accepted finalizer owns publication AND local recovery.
                # Its observer never holds the gate needed by recovery commits.
                publication = asyncio.create_task(
                    self._complete_state_restore(state, path, restoration_start),
                    context=contextvars.Context(),
                    name="att-restore-finalizer",
                )
                self._restore_finalizer = publication
                self._publication_tasks.add(publication)
                publication.add_done_callback(self._publication_tasks.discard)
            except BaseException:
                self._finish_restore_protection()
                raise
        await settle_commit(publication)

    def _finish_restore_protection(self) -> None:
        self._restore_source_path = None
        if self._resources.blocked:
            self._resources.finish_publication(committed=False)
        self._restore_in_progress = False
        self._restore_finalizer = None
        if self._memory._restore_suspended and not self._activity.recovery_required:
            self._memory.resume_after_restore()

    async def _complete_state_restore(self, state, path, restoration_start) -> None:
        """Settle accepted local work before exposing the restored generation."""
        recovered = False
        try:
            async with self._runtime_gate:
                await self._apply_state_snapshot(state)
                self.db_path = path
            async with self._activity.lock:
                await self._activity.after_restore(restoration_start=restoration_start)
            recovered = True
        finally:
            self._finish_restore_protection()
        if recovered and not self._closing:
            # These are synchronous queue handoffs, never external execution.
            self._activity.resume_after_restore()
            self.broker.resume_pending_requests()
            self._governance.resume()
            self._migration.resume()
            self._auto_save(governance_rounds={item.round_id for item in self._governance.rounds.values() if item.status == "EXPIRED"})

    @asynccontextmanager
    async def agent_invocation(self, agent: Agent, *, allow_runtime: bool = False):
        """Coordinates one invocation against restore and retirement."""
        async with self._lifecycle.agent_invocation(agent, allow_runtime=allow_runtime):
            yield

    def _emit_callback(self, name: str, *args: Any) -> None:
        """Queues an observational callback without blocking core execution."""
        self._callbacks.emit(name, *args)

    def _ensure_callback_dispatcher(self, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        self._callbacks.ensure_worker(loop)

    async def _dispatch_callbacks(self) -> None:
        await self._callbacks._dispatch()

    async def flush_callbacks(self) -> None:
        """Waits for queued observational callbacks."""
        await self._callbacks.flush()

    def _capture_state_snapshot(self, dirty: Dict[str, Any]) -> Dict[str, Any]:
        return self._snapshots._capture_state_snapshot(dirty)

    async def _apply_state_snapshot_unvalidated(self, state: Dict[str, Any]) -> None:
        await self._restore._apply_state_snapshot_unvalidated(state)

    async def _apply_state_snapshot(self, state: Dict[str, Any]) -> None:
        await self._restore._apply_state_snapshot(state)

    def _validate_state_snapshot(self, state: Dict[str, Any]) -> ATTConfig:
        return self._state_validator._validate_state_snapshot(state)

    def _validate_communication_state(self, *args: Any, **kwargs: Any) -> Any:
        return self._communication_validator._validate_communication_state(*args, **kwargs)

    def _normalized_library_links(
        self, state: Dict[str, Any]
    ) -> Dict[str, Dict[str, Dict[str, str]]]:
        return self._state_validator._normalized_library_links(state)

    def _publish_staged_libraries(self, *args: Any, **kwargs: Any) -> Any:
        return self._restore._publish_staged_libraries(*args, **kwargs)

    def _publish_new_staged_libraries(self, *args: Any, **kwargs: Any) -> Any:
        return self._restore._publish_new_staged_libraries(*args, **kwargs)

    def _rollback_published_libraries(self, *args: Any, **kwargs: Any) -> Any:
        return self._restore._rollback_published_libraries(*args, **kwargs)

    def _discard_library_backups(self, *args: Any, **kwargs: Any) -> Any:
        return self._restore._discard_library_backups(*args, **kwargs)
