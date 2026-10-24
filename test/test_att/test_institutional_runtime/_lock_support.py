"""Observe actual lock acquisition attempts without replacing their ordering."""

import asyncio

from test.async_waits import DEFAULT_RUNTIME_TIMEOUT


class ObservedLock:
    def __init__(self, lock):
        self.lock = lock
        self.attempts = {}

    async def acquire(self):
        self.attempts.setdefault(asyncio.current_task(), asyncio.Event()).set()
        return await self.lock.acquire()

    def release(self):
        self.lock.release()

    def locked(self):
        return self.lock.locked()

    async def __aenter__(self):
        await self.acquire()
        return self

    async def __aexit__(self, *_error):
        self.release()

    async def wait_for_attempt(self, task):
        event = self.attempts.setdefault(task, asyncio.Event())
        await asyncio.wait_for(event.wait(), DEFAULT_RUNTIME_TIMEOUT)
