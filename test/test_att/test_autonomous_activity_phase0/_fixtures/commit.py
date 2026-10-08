"""A receipt barrier records acceptance without inventing a durable write."""

import asyncio
import copy
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CommitReceipt:
    operation_id: str
    state_version: int


@dataclass
class CommitAttempt:
    operation_id: str
    captured_delta: Any
    result: asyncio.Future

    def succeed(self, state_version: int) -> None:
        self.result.set_result(CommitReceipt(self.operation_id, state_version))

    def fail(self, error: BaseException) -> None:
        self.result.set_exception(error)


class ControlledCommitter:
    def __init__(self):
        self.attempts: list[CommitAttempt] = []
        self._arrivals = asyncio.Queue()

    async def commit(self, operation_id: str, delta: Any) -> CommitReceipt:
        future = asyncio.get_running_loop().create_future()
        attempt = CommitAttempt(operation_id, copy.deepcopy(delta), future)
        self.attempts.append(attempt)
        self._arrivals.put_nowait(attempt)
        return await asyncio.shield(future)

    async def next_attempt(self) -> CommitAttempt:
        return await asyncio.wait_for(self._arrivals.get(), timeout=5)

    def close(self) -> None:
        for attempt in self.attempts:
            if not attempt.result.done():
                attempt.result.cancel()
            elif not attempt.result.cancelled():
                attempt.result.exception()
