"""Thread emissions share the observer queue, order, flush, and neutral context."""

import asyncio
import tempfile
import threading
import unittest

from ai_team_team import ATTConfig, ATTManager, Agent
from test.test_att.test_autonomous_activity_phase0._fixtures import ScriptedModelClient

from ._support import make_manager


class ThreadedCallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_thread_event_is_delivered_without_an_explicit_flush(self):
        manager, _, _ = make_manager(self, volatile=True)
        delivered = asyncio.Event()
        async def callback(event, details):
            delivered.set()
        manager.on_system_event = callback
        await asyncio.to_thread(manager._emit_callback, "on_system_event", "first", {})
        await asyncio.wait_for(delivered.wait(), 2)
        self.assertEqual(manager._callbacks.deferred, [])

    async def test_context_entry_binds_a_manager_constructed_outside_the_loop(self):
        with tempfile.TemporaryDirectory(prefix="att-callback-outside-loop-") as workspace:
            manager = await asyncio.to_thread(ATTManager, Agent("Root", "Architect", ScriptedModelClient()),
                                               ATTConfig(workspace_root=workspace), persistence_mode="volatile")
            self.addAsyncCleanup(manager.close)
            self.assertIsNone(manager._callbacks.loop)
            delivered = asyncio.Event()
            async def callback(event, details):
                delivered.set()
            manager.on_system_event = callback
            async with manager:
                await asyncio.to_thread(manager._emit_callback, "on_system_event", "entered", {})
                await asyncio.wait_for(delivered.wait(), 2)
            self.assertTrue(manager._closed)

    async def test_worker_file_callback_wakes_an_already_running_dispatcher(self):
        manager, _, _ = make_manager(self, volatile=True)
        observed = []
        delivered = asyncio.Event()
        async def callback(event, details):
            observed.append((event, details))
            if event == "private_library_file_changed":
                delivered.set()
        manager.on_system_event = callback
        manager._emit_callback("on_system_event", "initial", {})
        await manager.flush_callbacks()
        library = manager.libraries[manager.root_ai.private_doc_library_id]
        await asyncio.to_thread(library.write_file, "worker.txt", "private fixture body")
        await asyncio.wait_for(delivered.wait(), 2)
        await manager.flush_callbacks()
        self.assertEqual([event for event, _ in observed], ["initial", "private_library_file_changed"])
        self.assertNotIn("private fixture body", repr(observed))
        self.assertEqual(manager._callbacks.deferred, [])

    async def test_flush_drains_thread_events_received_before_any_worker_exists(self):
        manager, _, _ = make_manager(self, volatile=True)
        observed = []
        manager.on_system_event = lambda event, details: observed.append(event)
        self.assertIsNone(manager._callbacks.worker)
        for index in range(8):
            await asyncio.to_thread(manager._emit_callback, "on_system_event", index, {})
        await manager.flush_callbacks()
        self.assertEqual(observed, list(range(8)))
        self.assertEqual(manager._callbacks.deferred, [])

    async def test_mixed_thread_and_loop_events_keep_order_while_observer_waits(self):
        manager, _, _ = make_manager(self, volatile=True)
        started, release = asyncio.Event(), asyncio.Event()
        observed = []
        async def callback(event, details):
            observed.append(event)
            if event == "slow":
                started.set()
                await release.wait()
        manager.on_system_event = callback
        manager._emit_callback("on_system_event", "slow", {})
        await asyncio.wait_for(started.wait(), 2)
        expected = ["slow"]
        for index in range(16):
            await asyncio.to_thread(manager._emit_callback, "on_system_event", f"thread-{index}", {})
            manager._emit_callback("on_system_event", f"loop-{index}", {})
            expected.extend((f"thread-{index}", f"loop-{index}"))
        flush = asyncio.create_task(manager.flush_callbacks())
        await asyncio.sleep(0)
        self.assertFalse(flush.done())
        release.set()
        await asyncio.wait_for(flush, 2)
        self.assertEqual(observed, expected)

    async def test_concurrent_thread_events_are_delivered_once_in_acceptance_order(self):
        manager, _, _ = make_manager(self, volatile=True)
        expected, observed = [], []
        lock = threading.Lock()
        async def callback(event, details):
            observed.append(event)
        manager.on_system_event = callback
        manager._ensure_callback_dispatcher()
        def emit(index):
            with lock:
                expected.append(index)
                manager._emit_callback("on_system_event", index, {})
        await asyncio.gather(*(asyncio.to_thread(emit, index) for index in range(64)))
        await manager.flush_callbacks()
        self.assertEqual(observed, expected)
        self.assertEqual(len(set(observed)), 64)
        self.assertEqual(manager._callbacks.deferred, [])

    async def test_observers_do_not_inherit_agent_or_team_authority(self):
        manager, _, _ = make_manager(self, volatile=True)
        team = manager.create_agent_team(manager.root_ai)
        contexts = []
        async def callback(event, details):
            contexts.append((manager._active_tool_agent.get(), manager._active_team.get()))
        manager.on_system_event = callback
        agent_token = manager._active_tool_agent.set(manager.root_ai)
        team_token = manager._active_team.set(team)
        try:
            await asyncio.to_thread(manager._emit_callback, "on_system_event", "worker", {})
            manager._emit_callback("on_system_event", "loop", {})
        finally:
            manager._active_team.reset(team_token)
            manager._active_tool_agent.reset(agent_token)
        await manager.flush_callbacks()
        self.assertEqual(contexts, [(None, None), (None, None)])

    async def test_callback_self_cancellation_does_not_drop_following_events(self):
        manager, _, _ = make_manager(self, volatile=True)
        observed = []
        async def callback(event, details):
            observed.append(event)
            if event == "cancelled":
                raise asyncio.CancelledError
        manager.on_system_event = callback
        with self.assertLogs(manager.logger, level="WARNING") as logs:
            await asyncio.to_thread(manager._emit_callback, "on_system_event", "cancelled", {})
            manager._emit_callback("on_system_event", "next", {})
            await asyncio.wait_for(manager.flush_callbacks(), 2)
        self.assertEqual(observed, ["cancelled", "next"])
        self.assertIn("callback cancelled itself", "\n".join(logs.output))

    async def test_closed_dispatcher_rejects_late_thread_events(self):
        manager, _, _ = make_manager(self, volatile=True)
        observed = []
        manager.on_system_event = lambda event, details: observed.append(event)
        manager._emit_callback("on_system_event", "before", {})
        await manager.flush_callbacks()
        await manager.close()
        await asyncio.to_thread(manager._emit_callback, "on_system_event", "late", {})
        await manager.flush_callbacks()
        self.assertEqual(observed, ["before"])
        self.assertEqual(manager._callbacks.deferred, [])

    async def test_task_self_cancellation_cannot_cancel_dispatch_or_flush(self):
        for checkpoint in (False, True):
            with self.subTest(checkpoint=checkpoint):
                manager, _, _ = make_manager(self, volatile=True)
                observed = []
                tasks = []
                async def callback(event, details):
                    observed.append(event)
                    tasks.append(asyncio.current_task())
                    if event == "cancelled":
                        asyncio.current_task().cancel()
                        if checkpoint:
                            await asyncio.sleep(0)
                manager.on_system_event = callback
                manager._emit_callback("on_system_event", "cancelled", {})
                manager._emit_callback("on_system_event", "next", {})
                with self.assertLogs(manager.logger, level="WARNING"):
                    await asyncio.wait_for(manager.flush_callbacks(), 2)
                self.assertEqual(observed, ["cancelled", "next"])
                self.assertTrue(all(task is not manager._callbacks.worker for task in tasks))
                self.assertFalse(manager._callbacks.worker.done())
                self.assertEqual(manager._callbacks.worker.cancelling(), 0)
                self.assertEqual(manager._callbacks.queue.qsize(), 0)

    async def test_sync_callback_returning_an_awaitable_has_its_own_cancellation(self):
        manager, _, _ = make_manager(self, volatile=True)
        observed = []
        async def observation(event):
            observed.append(event)
            if event == "cancelled":
                asyncio.current_task().cancel()
                await asyncio.sleep(0)
        manager.on_system_event = lambda event, details: observation(event)
        manager._emit_callback("on_system_event", "cancelled", {})
        manager._emit_callback("on_system_event", "next", {})
        with self.assertLogs(manager.logger, level="WARNING"):
            await asyncio.wait_for(manager.flush_callbacks(), 2)
        self.assertEqual(observed, ["cancelled", "next"])
        self.assertEqual(manager._callbacks.worker.cancelling(), 0)

    async def test_cancelling_a_flush_does_not_cancel_observations(self):
        manager, _, _ = make_manager(self, volatile=True)
        started, release = asyncio.Event(), asyncio.Event()
        observed = []
        async def callback(event, details):
            if event == "slow":
                started.set()
                await release.wait()
            observed.append(event)
        manager.on_system_event = callback
        manager._emit_callback("on_system_event", "slow", {})
        manager._emit_callback("on_system_event", "next", {})
        await asyncio.wait_for(started.wait(), 2)
        flush = asyncio.create_task(manager.flush_callbacks())
        await asyncio.sleep(0)
        flush.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await flush
        release.set()
        await asyncio.wait_for(manager.flush_callbacks(), 2)
        self.assertEqual(observed, ["slow", "next"])
        self.assertFalse(manager._callbacks.worker.done())

    async def test_close_cancels_the_observer_and_does_not_run_queued_events(self):
        manager, _, _ = make_manager(self, volatile=True)
        started, cancelled = asyncio.Event(), asyncio.Event()
        observed = []
        async def callback(event, details):
            observed.append(event)
            if event == "slow":
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()
        manager.on_system_event = callback
        manager._emit_callback("on_system_event", "slow", {})
        manager._emit_callback("on_system_event", "next", {})
        await asyncio.wait_for(started.wait(), 2)
        await asyncio.wait_for(manager.close(), 2)
        await asyncio.wait_for(cancelled.wait(), 2)
        self.assertEqual(observed, ["slow"])
        self.assertTrue(manager._callbacks.worker.cancelled())

    async def test_close_does_not_wait_for_an_observer_that_suppresses_cancellation(self):
        manager, _, _ = make_manager(self, volatile=True)
        started, release, cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()
        observed = []
        async def callback(event, details):
            observed.append(event)
            if event == "slow":
                started.set()
                while not release.is_set():
                    try:
                        await release.wait()
                    except asyncio.CancelledError:
                        cancelled.set()
                raise RuntimeError("Late observer fixture failure")
        manager.on_system_event = callback
        manager._emit_callback("on_system_event", "slow", {})
        manager._emit_callback("on_system_event", "next", {})
        await asyncio.wait_for(started.wait(), 2)
        observer = manager._callbacks.observer
        try:
            await asyncio.wait_for(manager.close(), 2)
            await asyncio.wait_for(cancelled.wait(), 2)
            self.assertTrue(manager._callbacks.worker.cancelled())
            self.assertFalse(observer.done())
            with self.assertLogs(manager.logger, level="ERROR") as logs:
                release.set()
                await asyncio.wait_for(observer, 2)
            self.assertIn("Observational ATT callback failed", "\n".join(logs.output))
            self.assertEqual(observed, ["slow"])
        finally:
            release.set()
            await asyncio.wait_for(observer, 2)
