"""Worker validation is observational until the real acceptance boundary."""

import asyncio
import threading
from unittest.mock import patch

from test.async_waits import DEFAULT_RUNTIME_TIMEOUT
from test.test_att.test_agent_activity._support import ActivityTestCase, idle


class VolatileValidationLifecycleTests(ActivityTestCase):
    async def test_slow_preparation_does_not_block_heartbeat_or_publish_baseline(self):
        cache = self.manager._records._validation
        original = cache.prepare
        entered, release = threading.Event(), threading.Event()

        def prepare(state):
            entered.set()
            if not release.wait(DEFAULT_RUNTIME_TIMEOUT):
                raise AssertionError("The test did not release validation.")
            return original(state)

        self.steps(idle())
        with patch.object(cache, "prepare", prepare):
            task = asyncio.create_task(self.manager.activate_agent(self.root.agent_id))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, DEFAULT_RUNTIME_TIMEOUT))
                heartbeat = asyncio.Event()
                asyncio.get_running_loop().call_soon(heartbeat.set)
                await heartbeat.wait()
                self.assertIsNone(cache._accepted)
                self.assertFalse(task.done())
            finally:
                release.set()
            admission = await task
        await self.wait(admission)
        self.assertIsNotNone(cache._accepted)

    async def test_cancelled_preparation_cannot_publish_a_late_candidate(self):
        cache = self.manager._records._validation
        original = cache.prepare
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()

        def prepare(state):
            entered.set()
            try:
                if not release.wait(DEFAULT_RUNTIME_TIMEOUT):
                    raise AssertionError("The test did not release validation.")
                return original(state)
            finally:
                finished.set()

        with patch.object(cache, "prepare", prepare):
            task = asyncio.create_task(self.manager.activate_agent(self.root.agent_id))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, DEFAULT_RUNTIME_TIMEOUT))
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                self.assertIsNone(cache._accepted)
            finally:
                release.set()
                self.assertTrue(await asyncio.to_thread(finished.wait, DEFAULT_RUNTIME_TIMEOUT))
        self.assertIsNone(cache._accepted)
        self.steps(idle())
        admission = await self.manager.activate_agent(self.root.agent_id)
        await self.wait(admission)
        self.assertIsNotNone(cache._accepted)
