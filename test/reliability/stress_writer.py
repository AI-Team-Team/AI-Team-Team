"""Controlled slow disk retains accepted changes with two completion handles."""

import asyncio
import json
import os
import sqlite3
import threading
from contextlib import closing
from unittest.mock import patch

from ai_team_team.database.persistence import DatabaseStore
from test.async_waits import DEFAULT_RUNTIME_TIMEOUT
from test.test_att.test_autonomous_activity_phase1._support import make_manager

import unittest


class SlowWriterTests(unittest.IsolatedAsyncioTestCase):
    async def test_continuous_producers_coalesce_without_losing_keys_or_blocking_the_loop(self):
        manager, path, client = make_manager(self)
        await manager.save_state()
        expected = {}
        operations = int(os.environ.get("ATT_STRESS_OPERATIONS", "96"))
        if operations <= 0:
            raise ValueError("The producer workload must be positive.")
        original = DatabaseStore.write
        writes, heartbeats, peak_handles = 0, 0, 0
        for burst in range(4):
            entered, release = threading.Event(), threading.Event()
            first = True

            def held_write(store, snapshot):
                nonlocal first, writes
                writes += 1
                if first:
                    first = False
                    entered.set()
                    if not release.wait(DEFAULT_RUNTIME_TIMEOUT):
                        raise AssertionError("The workload did not release its writer barrier.")
                return original(store, snapshot)

            async def producer(number):
                nonlocal heartbeats
                for offset in range(operations):
                    key = f"burst-{burst}-producer-{number}-key-{offset}"
                    expected[key] = "accepted"
                    manager.config.model_registry[key] = "accepted"
                    manager._auto_save(configs=True)
                    if offset % 8 == 0:
                        tick = asyncio.Event()
                        asyncio.get_running_loop().call_soon(tick.set)
                        await tick.wait()
                        heartbeats += 1
                    else:
                        await asyncio.sleep(0)

            with patch.object(DatabaseStore, "write", held_write):
                manager._auto_save(configs=True)
                self.assertTrue(await asyncio.to_thread(entered.wait, DEFAULT_RUNTIME_TIMEOUT))
                tasks = [asyncio.create_task(producer(number)) for number in range(4)]
                close_task = None
                try:
                    await asyncio.gather(*tasks)
                    pending = manager._persistence._pending_completion
                    self.assertIsNotNone(pending)
                    self.assertFalse(pending.done())
                    manager._auto_save(configs=True)
                    self.assertIs(manager._persistence._pending_completion, pending)
                    with manager._persistence._lock:
                        self.assertIsNotNone(manager._persistence._active_completion)
                        self.assertEqual(len({id(manager._persistence._active_completion), id(pending)}), 2)
                        peak_handles = max(peak_handles, len({id(manager._persistence._active_completion), id(pending)}))
                    if burst == 3:
                        close_task = asyncio.create_task(manager.close())
                        while not manager._closing:
                            await asyncio.sleep(0)
                        self.assertFalse(close_task.done())
                finally:
                    release.set()
                    await asyncio.gather(*tasks, return_exceptions=True)
                if close_task is not None:
                    await close_task
                else:
                    await manager.flush_state()
            self.assertIsNone(manager._persistence._pending_completion)
            self.assertIsNone(manager._persistence._active_completion)
        self.assertEqual(writes, 8)
        self.assertGreater(heartbeats, 0)
        self.assertEqual(dict(manager.config.model_registry), expected)
        self.assertFalse(client.requests)
        with closing(sqlite3.connect(path)) as database:
            persisted = database.execute("SELECT config_value FROM manager_config WHERE config_key='att_config'").fetchone()
            self.assertIsNotNone(persisted)
            self.assertEqual(json.loads(persisted[0])["model_registry"], expected)
        # A completed close releases the cross-process ownership lease.
        from ai_team_team.database.persistence.lease import WriterLease
        lease = WriterLease(path)
        lease.close()
        self.acceptance_metrics = {"writer_commits": writes, "peak_completion_handles": peak_handles,
                                   "retained_config_keys": len(expected), "heartbeat_callbacks": heartbeats}
