"""Ordered, non-blocking dispatch for observational ATT callbacks."""

import asyncio
import contextvars
import inspect
import threading
from typing import TYPE_CHECKING, Any, Callable, List, Optional, Tuple

if TYPE_CHECKING:
    from ..manager import ATTManager


class CallbackDispatcher:
    """Owns callback queueing and isolates callback failures from core work."""

    def __init__(self, manager: "ATTManager") -> None:
        self.manager = manager
        self.queue: Optional[asyncio.Queue[Any]] = None
        self.worker: Optional[asyncio.Task[Any]] = None
        self.observer: Optional[asyncio.Task[None]] = None
        self.deferred: List[Tuple[Callable[..., Any], tuple]] = []
        self.lock = threading.RLock()
        try:
            self.loop: Optional[asyncio.AbstractEventLoop] = asyncio.get_running_loop()
        except RuntimeError:
            self.loop = None
        self.closed = False

    def emit(self, name: str, *args: Any) -> None:
        callback = getattr(self.manager, name, None)
        if callback is None:
            return
        item = (callback, tuple(args))
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None
        with self.lock:
            if self.closed or self.manager._closing:
                return
            # All producers use the same ingress order, including threads.
            # Only the owning event loop may touch the asyncio queue.
            self.deferred.append(item)
            if self.loop is None:
                self.loop = running_loop
            if self.loop is not None and not self.loop.is_closed():
                try:
                    self.loop.call_soon_threadsafe(self.ensure_worker, self.loop)
                except RuntimeError:
                    # Loop shutdown cannot turn an observation into a core
                    # business failure. Pending items remain visible to flush.
                    pass

    def ensure_worker(self, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        loop = loop or asyncio.get_running_loop()
        with self.lock:
            if self.closed:
                return
            if self.loop is None:
                self.loop = loop
            elif self.loop is not loop:
                raise RuntimeError("ATT callbacks must be flushed on their owning event loop.")
            if self.queue is None:
                self.queue = asyncio.Queue()
            if self.worker is None or self.worker.done():
                self.worker = loop.create_task(self._dispatch(), name=f"att-callbacks-{id(self.manager)}", context=contextvars.Context())
            deferred = self.deferred
            self.deferred = []
            for item in deferred:
                self.queue.put_nowait(item)

    async def _dispatch(self) -> None:
        assert self.queue is not None
        while True:
            callback, args = await self.queue.get()
            # An observer owns its cancellation state, not the dispatcher that
            # serializes all observations. Shield only this boundary: shutdown
            # cancels the observer without waiting on an uncooperative extension.
            observer = asyncio.create_task(self._invoke(callback, args), name=f"att-observer-{id(self.manager)}")
            self.observer = observer
            observer.add_done_callback(self._observer_finished)
            try:
                await asyncio.shield(observer)
            except asyncio.CancelledError:
                task = asyncio.current_task()
                if task is not None and task.cancelling():
                    observer.cancel()
                    raise
                self.manager.logger.warning("Observational ATT callback cancelled itself.")
            finally:
                if observer.done():
                    self.observer = None
                self.queue.task_done()

    def _observer_finished(self, observer: asyncio.Task[None]) -> None:
        if self.observer is observer:
            self.observer = None

    async def _invoke(self, callback: Callable[..., Any], args: tuple) -> None:
        """Isolate both callback forms without changing source transactions."""
        try:
            if inspect.iscoroutinefunction(callback):
                await callback(*args)
            else:
                result = await asyncio.to_thread(callback, *args)
                if inspect.isawaitable(result):
                    await result
        except Exception:
            self.manager.logger.exception("Observational ATT callback failed.")

    async def flush(self) -> None:
        if self.closed or self.manager._closing:
            return
        self.ensure_worker()
        assert self.queue is not None
        await self.queue.join()

    async def close(self) -> None:
        with self.lock:
            self.closed = True
            self.deferred = []
        if self.worker is not None and not self.worker.done():
            self.worker.cancel()
            await asyncio.sleep(0)
        if self.observer is not None and not self.observer.done() and not self.observer.cancelling():
            self.observer.cancel()
