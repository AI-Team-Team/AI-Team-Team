"""Ordered, non-blocking dispatch for observational ATT callbacks."""

import asyncio
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
        self.deferred: List[Tuple[Callable[..., Any], tuple]] = []
        self.lock = threading.RLock()

    def emit(self, name: str, *args: Any) -> None:
        callback = getattr(self.manager, name, None)
        if callback is None or self.manager._closing:
            return
        item = (callback, tuple(args))
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            with self.lock:
                self.deferred.append(item)
            return
        self.ensure_worker(loop)
        assert self.queue is not None
        self.queue.put_nowait(item)

    def ensure_worker(self, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        if self.worker is not None and not self.worker.done():
            return
        loop = loop or asyncio.get_running_loop()
        self.queue = asyncio.Queue()
        with self.lock:
            deferred = self.deferred
            self.deferred = []
        for item in deferred:
            self.queue.put_nowait(item)
        self.worker = loop.create_task(self._dispatch(), name=f"att-callbacks-{id(self.manager)}")

    async def _dispatch(self) -> None:
        assert self.queue is not None
        while True:
            callback, args = await self.queue.get()
            try:
                if inspect.iscoroutinefunction(callback):
                    await callback(*args)
                else:
                    result = await asyncio.to_thread(callback, *args)
                    if inspect.isawaitable(result):
                        await result
            except asyncio.CancelledError:
                raise
            except Exception:
                self.manager.logger.exception("Observational ATT callback failed.")
            finally:
                self.queue.task_done()

    async def flush(self) -> None:
        if self.manager._closing:
            return
        self.ensure_worker()
        assert self.queue is not None
        await self.queue.join()

    async def close(self) -> None:
        if self.worker is not None and not self.worker.done():
            self.worker.cancel()
            await asyncio.sleep(0)
