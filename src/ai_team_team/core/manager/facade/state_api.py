"""Public ATTManager delegation methods for StateAPI."""

import asyncio
import os
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, Dict, Optional


from ...agent import Agent
from ...config import ATTConfig
from ..state import StateCoordinator

if TYPE_CHECKING:
    from .manager import ATTManager


class StateAPI:
    async def __aenter__(self) -> "ATTManager":
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.close()

    @staticmethod
    def _new_dirty_state(full: bool = False) -> Dict[str, Any]:
        return StateCoordinator._new_dirty_state(full)

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
        await self._lifecycle.close()

    async def load_state(self, path: str) -> None:
        """Restores a versioned state snapshot without blocking the event loop."""
        async with self._runtime_gate:
            if self._closing:
                raise RuntimeError("ATTManager is closing and cannot restore state.")
            if not os.path.exists(path):
                raise FileNotFoundError(f"State database file '{path}' not found.")
            state = await self._persistence.read(path)
            await self._apply_state_snapshot(state)
            self.db_path = path
            self.broker.resume_pending_requests()

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
