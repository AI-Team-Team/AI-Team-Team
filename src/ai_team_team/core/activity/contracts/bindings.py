"""Host runtime bindings are injectable but never serialized."""

from typing import Protocol


class RuntimeClock(Protocol):
    def monotonic(self) -> float: ...

    def wall_time(self) -> float: ...

    async def sleep(self, seconds: float) -> None: ...
