"""Explicit exports cannot publish an obsolete generation during restoration."""

import asyncio
import json
import threading
from pathlib import Path
from unittest.mock import patch

from ._support import ActivityTestCase


class RestoreSaveExclusionTests(ActivityTestCase):
    async def durable_checkpoint(self):
        await self.manager.close()
        self.manager = self.make_manager(self.root, durable=True)
        self.manager.config.activity.model_requests_per_invocation = 7
        await self.manager.save_state()
        self.manager.config.activity.model_requests_per_invocation = 3
        return self.manager.db_path

    async def test_save_queued_before_restore_cannot_overwrite_its_source(self):
        path = await self.durable_checkpoint()
        loading_waits, saving_waits = asyncio.Event(), asyncio.Event()
        read_entered, read_release = threading.Event(), threading.Event()
        original_acquire = self.manager._runtime_gate.acquire
        original_read = self.manager._persistence._read
        loading = saving = None

        async def acquire():
            current = asyncio.current_task()
            if current is loading:
                loading_waits.set()
            elif current is saving:
                saving_waits.set()
            return await original_acquire()

        def read(db_path, reconcile=True):
            if reconcile:
                read_entered.set()
                if not read_release.wait(10):
                    raise TimeoutError("The restore read was not released.")
            return original_read(db_path, reconcile=reconcile)

        with (
            patch.object(self.manager._runtime_gate, "acquire", acquire),
            patch.object(self.manager._persistence, "_read", read),
        ):
            try:
                async with self.manager._runtime_gate:
                    loading = asyncio.create_task(self.manager.load_state(path))
                    await asyncio.wait_for(loading_waits.wait(), 5)
                    saving = asyncio.create_task(self.manager.save_state())
                    await asyncio.wait_for(saving_waits.wait(), 5)
                    self.assertFalse(self.manager._restore_in_progress)
                self.assertTrue(await asyncio.to_thread(read_entered.wait, 5))
                self.assertTrue(self.manager._restore_in_progress)
                self.assertFalse(saving.done())
                read_release.set()
                with self.assertRaisesRegex(RuntimeError, "restoring"):
                    await asyncio.wait_for(saving, 10)
                await asyncio.wait_for(loading, 15)
            finally:
                read_release.set()
                await asyncio.gather(
                    *(task for task in (loading, saving) if task), return_exceptions=True
                )
        self.assertEqual(self.manager.config.activity.model_requests_per_invocation, 7)
        stored = await self.manager._persistence.read(path, reconcile=False)
        self.assertEqual(json.loads(stored["configs"]["att_config"])["activity"]["model_requests_per_invocation"], 7)
        # Once the entire restore lifetime ends, a new explicit save is valid.
        self.manager.config.activity.model_requests_per_invocation = 5
        await self.manager.save_state()
        stored = await self.manager._persistence.read(path, reconcile=False)
        self.assertEqual(json.loads(stored["configs"]["att_config"])["activity"]["model_requests_per_invocation"], 5)

    async def test_postpublication_recovery_rejects_even_another_export_path(self):
        path = await self.durable_checkpoint()
        entered, release = asyncio.Event(), asyncio.Event()
        original = self.manager._activity.after_restore
        export = str(Path(self.workspace.name) / "obsolete-export.sqlite")

        async def recover(**kwargs):
            entered.set()
            await release.wait()
            return await original(**kwargs)

        with patch.object(self.manager._activity, "after_restore", recover):
            loading = asyncio.create_task(self.manager.load_state(path))
            try:
                await asyncio.wait_for(entered.wait(), 10)
                with self.assertRaisesRegex(RuntimeError, "restoring"):
                    await self.manager.save_state(export)
                self.assertFalse(Path(export).exists())
            finally:
                release.set()
                await asyncio.wait_for(loading, 10)

    async def test_save_rechecks_shutdown_after_waiting_for_the_runtime_gate(self):
        await self.durable_checkpoint()
        waiting, close_waiting = asyncio.Event(), asyncio.Event()
        original = self.manager._runtime_gate.acquire
        saving = closing = None

        async def acquire():
            current = asyncio.current_task()
            if current is saving:
                waiting.set()
            elif current is self.manager._close_task:
                close_waiting.set()
            return await original()

        with patch.object(self.manager._runtime_gate, "acquire", acquire):
            try:
                async with self.manager._runtime_gate:
                    saving = asyncio.create_task(self.manager.save_state())
                    await asyncio.wait_for(waiting.wait(), 5)
                    closing = asyncio.create_task(self.manager.close())
                    await asyncio.wait_for(close_waiting.wait(), 5)
                with self.assertRaisesRegex(RuntimeError, "closing"):
                    await asyncio.wait_for(saving, 10)
                await asyncio.wait_for(closing, 10)
            finally:
                await asyncio.gather(
                    *(task for task in (saving, closing) if task), return_exceptions=True
                )
