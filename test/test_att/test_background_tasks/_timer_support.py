"""Delay one timer's first deadline calculation, not its admitted execution."""

import asyncio

from ai_team_team.core.manager.timing import wait_until


class TimerStartGate:
    def __init__(self):
        self.entered = asyncio.Event()
        self.released = asyncio.Event()
        self.finished = asyncio.Event()
        self.task = None
        self.deadline = None
        self.calls = 0

    async def __call__(self, clock, deadline):
        self.calls += 1
        if self.calls != 1:
            return await wait_until(clock, deadline)
        self.task = asyncio.current_task()
        self.deadline = deadline
        self.entered.set()
        try:
            await self.released.wait()
            await wait_until(clock, deadline)
        finally:
            self.finished.set()


async def wait_registered(clock, deadline):
    """A backoff or model timer is not proof this deadline was registered."""
    async with asyncio.timeout(5):
        while not any(when == deadline and not future.done() for when, _index, future in clock._waits):
            await asyncio.sleep(0)
