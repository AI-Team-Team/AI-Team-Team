"""Timeout diagnostics preserve cancellation, domain errors, and privacy."""

import asyncio
import io
from contextlib import redirect_stderr

from test.async_waits import runtime_state, runtime_watchdog, wait_for_runtime
from test.test_att.test_agent_activity._support import ActivityTestCase


class RuntimeWatchdogTests(ActivityTestCase):
    async def test_internal_timeout_is_not_reclassified(self):
        error = TimeoutError("Domain timeout")
        with self.assertRaises(TimeoutError) as caught:
            async with runtime_watchdog(self.manager):
                raise error
        self.assertIs(caught.exception, error)

    async def test_external_cancellation_propagates(self):
        entered = asyncio.Event()

        async def wait():
            async with runtime_watchdog(self.manager):
                entered.set()
                await asyncio.Event().wait()

        task = asyncio.create_task(wait())
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

    async def test_expiration_emits_metadata_before_cancellation(self):
        secret = "Private watchdog sentinel must not appear."
        self.root.messages.append({"role": "user", "content": secret})
        output = io.StringIO()
        cancelled = False

        async def blocked():
            nonlocal cancelled
            try:
                await asyncio.Event().wait()
            finally:
                cancelled = True
                self.assertIn("Runtime state:", output.getvalue())

        with redirect_stderr(output):
            with self.assertRaisesRegex(AssertionError, "Runtime state:") as caught:
                await wait_for_runtime(self.manager, blocked(), timeout=0)
        self.assertTrue(cancelled)
        self.assertIn("state_version", str(caught.exception))
        self.assertNotIn(secret, str(caught.exception))
        self.assertNotIn(secret, output.getvalue())

    async def test_snapshot_reports_locks_and_progress_without_mutation(self):
        before = self.manager._state_version
        snapshot = runtime_state(self.manager)
        self.assertEqual(snapshot["state_version"], before)
        self.assertEqual(snapshot["locks"], {"runtime": False, "activity": False, "records": False})
        self.assertEqual(self.manager._state_version, before)

    async def test_suppressing_the_observer_cancel_does_not_hide_expiration(self):
        with redirect_stderr(io.StringIO()):
            with self.assertRaisesRegex(AssertionError, "Runtime state:"):
                async with runtime_watchdog(self.manager, timeout=0):
                    try:
                        await asyncio.Event().wait()
                    except asyncio.CancelledError:
                        pass

    async def test_domain_timeout_after_observer_expiry_takes_precedence(self):
        error = TimeoutError("The accepted writer failed while cancellation settled.")
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(TimeoutError) as caught:
                async with runtime_watchdog(self.manager, timeout=0):
                    try:
                        await asyncio.Event().wait()
                    except asyncio.CancelledError:
                        raise error
        self.assertIs(caught.exception, error)
