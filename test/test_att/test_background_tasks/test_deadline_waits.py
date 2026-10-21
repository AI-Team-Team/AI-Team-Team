"""Absolute waits do not rebase a deadline when their Task starts late."""

import asyncio
import unittest

from ai_team_team.core.manager.timing import wait_until
from test.test_att.test_autonomous_activity_phase0._fixtures import LogicalClock

from ._timer_support import wait_registered


class DeadlineWaitTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clock = LogicalClock()
        self.addCleanup(self.clock.close)

    async def test_deadline_reached_before_the_timer_task_starts(self):
        timer = asyncio.create_task(wait_until(self.clock, 120.0))
        self.clock.advance(120)
        await asyncio.wait_for(timer, 5)
        self.assertEqual(self.clock.pending_waits, 0)
        self.assertEqual(self.clock.monotonic(), 120)

    async def test_late_start_waits_only_for_the_remaining_time(self):
        timer = asyncio.create_task(wait_until(self.clock, 120.0))
        try:
            self.clock.advance(40)
            await wait_registered(self.clock, 120)
            self.assertFalse(timer.done())
            self.clock.advance(80)
            await asyncio.wait_for(timer, 5)
        finally:
            timer.cancel()
            await asyncio.gather(timer, return_exceptions=True)
        self.assertEqual(self.clock.pending_waits, 0)

    async def test_already_expired_deadline_needs_no_further_clock_advance(self):
        self.clock.advance(121)
        await asyncio.wait_for(wait_until(self.clock, 120.0), 5)
        self.assertEqual(self.clock.pending_waits, 0)
        self.assertEqual(self.clock.monotonic(), 121)

    async def test_cancelling_a_registered_wait_removes_its_clock_future(self):
        timer = asyncio.create_task(wait_until(self.clock, 120.0))
        await wait_registered(self.clock, 120)
        timer.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await timer
        self.assertEqual(self.clock.pending_waits, 0)

    async def test_cancelling_before_task_start_does_not_register_a_wait(self):
        timer = asyncio.create_task(wait_until(self.clock, 120.0))
        timer.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await timer
        self.assertEqual(self.clock.pending_waits, 0)
