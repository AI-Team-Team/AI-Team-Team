"""Controllable provider outcome; a cancellation request is not acknowledgement."""

import asyncio
from dataclasses import dataclass
from typing import Any

from .barriers import AsyncBarrier


@dataclass(frozen=True)
class ExecutorOutcome:
    state: str
    value: Any = None


class ControlledExecutor:
    def __init__(self, *, dispatch_barrier: AsyncBarrier | None = None):
        self.dispatch_barrier = dispatch_barrier
        self.entered = asyncio.Event()
        self.started = asyncio.Event()
        self.calls = 0
        self.side_effects = 0
        self.cancellation_requested = False
        self.outcome: ExecutorOutcome | None = None
        self._result: asyncio.Future | None = None

    async def __call__(self) -> ExecutorOutcome:
        self.calls += 1
        if self.calls != 1:
            raise AssertionError("The admitted execution was unexpectedly replayed.")
        self._result = asyncio.get_running_loop().create_future()
        self.entered.set()
        if self.dispatch_barrier is not None:
            await self.dispatch_barrier.pause()
        if self.outcome is None:
            self.side_effects += 1
            self.started.set()
        elif not self._result.done():
            self._result.set_result(self.outcome)
        # Stopping a local wait does not prove that the provider cancelled.
        return await asyncio.shield(self._result)

    def request_cancellation(self) -> None:
        self.cancellation_requested = True

    def acknowledge_cancellation(self) -> bool:
        if not self.cancellation_requested:
            raise AssertionError("An acknowledgement needs a cancellation request.")
        return self._finish(ExecutorOutcome("cancelled"))

    def complete(self, value: Any = None) -> bool:
        if self.outcome is not None:
            return False
        if not self.started.is_set():
            raise AssertionError("Completion requires an actual executor dispatch.")
        return self._finish(ExecutorOutcome("completed", value))

    def _finish(self, outcome: ExecutorOutcome) -> bool:
        if self.outcome is not None:
            return False
        self.outcome = outcome
        if self._result is not None and not self._result.done():
            self._result.set_result(outcome)
        return True

    def close(self) -> None:
        if self._result is not None and not self._result.done():
            self._result.cancel()
