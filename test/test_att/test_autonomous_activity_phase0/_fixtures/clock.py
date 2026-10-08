"""Monotonic and wall clocks advance only when a test explicitly advances them."""

import asyncio
import heapq
import itertools
import math


def _duration(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Clock durations must be finite nonnegative numbers.")
    try:
        duration = float(value)
    except OverflowError as exc:
        raise ValueError("Clock durations must be finite nonnegative numbers.") from exc
    if not math.isfinite(duration) or duration < 0:
        raise ValueError("Clock durations must be finite nonnegative numbers.")
    return duration


class LogicalClock:
    def __init__(self, *, wall_time: float = 0, monotonic: float = 0) -> None:
        self._wall = _duration(wall_time)
        self._monotonic = _duration(monotonic)
        self._sequence = itertools.count()
        self._waits: list[tuple[float, int, asyncio.Future]] = []

    def monotonic(self) -> float:
        return self._monotonic

    def wall_time(self) -> float:
        return self._wall

    @property
    def pending_waits(self) -> int:
        return sum(not future.done() for _, _, future in self._waits)

    async def sleep(self, seconds: float) -> None:
        seconds = _duration(seconds)
        if seconds == 0:
            await asyncio.sleep(0)
            return
        deadline = _duration(self._monotonic + seconds)
        future = asyncio.get_running_loop().create_future()
        heapq.heappush(self._waits, (deadline, next(self._sequence), future))
        try:
            await future
        finally:
            # Cancelled waits must not accumulate during cancellation stress tests.
            self._waits = [item for item in self._waits if item[2] is not future]
            heapq.heapify(self._waits)

    def advance(self, seconds: float) -> None:
        seconds = _duration(seconds)
        monotonic = _duration(self._monotonic + seconds)
        wall_time = _duration(self._wall + seconds)
        self._monotonic = monotonic
        self._wall = wall_time
        while self._waits and self._waits[0][0] <= self._monotonic:
            _, _, future = heapq.heappop(self._waits)
            if not future.done():
                future.set_result(None)

    def restarted(self, *, offline_seconds: float) -> "LogicalClock":
        return LogicalClock(wall_time=self._wall + _duration(offline_seconds))

    def close(self) -> None:
        for _, _, future in self._waits:
            future.cancel()
        self._waits.clear()


class CountdownCheckpoint:
    """Fixture evidence, not the production timer or persistence algorithm."""

    def __init__(self, clock: LogicalClock, remaining: float, *, anchor: float | None = None):
        self.clock = clock
        self.deadline = _duration(
            (clock.monotonic() if anchor is None else _duration(anchor)) + _duration(remaining)
        )

    def remaining(self) -> float:
        return max(0.0, self.deadline - self.clock.monotonic())
