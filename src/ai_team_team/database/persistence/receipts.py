"""Exact operation acknowledgements and cancellation-safe commit settlement."""

import asyncio
from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class CommitReceipt:
    """Acknowledges one accepted operation, even when its delta was coalesced."""

    operation_id: str
    state_version: int
    durability: Literal["durable", "volatile"]
    dependencies: tuple[str, ...] = ()
    record_digest: str | None = None

    def __post_init__(self):
        if type(self.operation_id) is not str or not self.operation_id.strip():
            raise ValueError("Commit receipts require a nonblank operation identity.")
        if type(self.state_version) is not int or self.state_version < 1:
            raise ValueError("Commit receipts require a positive strict state version.")
        if self.durability not in {"durable", "volatile"}:
            raise ValueError("Invalid receipt durability.")
        if type(self.dependencies) is not tuple or any(type(key) is not str or not key for key in self.dependencies):
            raise ValueError("Commit receipt dependencies must be immutable identifiers.")
        if self.record_digest is not None and (type(self.record_digest) is not str
                or len(self.record_digest) != 64 or any(char not in "0123456789abcdef" for char in self.record_digest)):
            raise ValueError("A record digest must be a SHA-256 identity.")


async def settle_commit(future: asyncio.Future[Any]) -> Any:
    """Keep mutation protection until commit/rollback is known after any cancels.

    Shielding once is insufficient: a second cancellation can interrupt the
    cleanup wait. The underlying commit is never cancelled by its observer.
    Write errors take precedence over a cancelled observer's lost response.
    """
    cancelled = False
    while not future.done():
        try:
            await asyncio.shield(future)
        except asyncio.CancelledError:
            cancelled = True
    result = future.result()
    if cancelled:
        raise asyncio.CancelledError
    return result
