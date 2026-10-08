"""Explicit scheduling boundaries instead of timing-dependent test sleeps."""

import asyncio


class AsyncBarrier:
    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.released = asyncio.Event()
        self.entries = 0
        self.cancellations = 0

    async def pause(self) -> None:
        self.entries += 1
        self.entered.set()
        try:
            await self.released.wait()
        except asyncio.CancelledError:
            self.cancellations += 1
            raise

    async def wait_entered(self) -> None:
        # A watchdog diagnoses deadlocks; it never advances the simulated clock.
        await asyncio.wait_for(self.entered.wait(), timeout=5)

    def release(self) -> None:
        self.released.set()


async def cancel_and_drain(*tasks: asyncio.Task) -> None:
    for task in tasks:
        if not task.done():
            task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
