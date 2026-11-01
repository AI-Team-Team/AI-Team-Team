"""Indexing workers stop after a cooperative cancellation loses to a returned label."""

import asyncio
import json
from unittest.mock import patch

from test.async_waits import wait_for_runtime
from test.personal_activity import interact_and_idle

from ._support import EpisodicMemoryTestCase


class IndexingLifecycleTests(EpisodicMemoryTestCase):
    async def test_disabling_indexing_drains_a_backlog_and_reenable_preserves_pending_work(self):
        self.manager.config.episodic_memory.index_worker_count = 1
        entered, release, flushing = asyncio.Event(), asyncio.Event(), asyncio.Event()
        observer = None

        async def held_index(*args, **kwargs):
            entered.set()
            await release.wait()
            return json.dumps(self.client.labels)

        with patch.object(self.manager._activity.models, "index", held_index):
            try:
                await interact_and_idle(self.manager, self.agent, "First remembered operation.")
                await wait_for_runtime(self.manager, entered.wait(), label="Index provider is waiting")
                self.client.responses = ["Final Answer: Another operation.", "Action: set_activity_intent(intent={'kind': 'idle'})"]
                await interact_and_idle(self.manager, self.agent, "Second remembered operation.")
                queue = self.manager._memory._queue
                self.assertGreater(queue.qsize(), 0)
                original_join = queue.join

                async def observed_join():
                    flushing.set()
                    await original_join()

                with patch.object(queue, "join", observed_join):
                    observer = asyncio.create_task(self.manager.flush_memory_indexing())
                    await flushing.wait()
                    self.manager.config.episodic_memory.enabled = False
                    release.set()
                    await wait_for_runtime(self.manager, observer, label="Disabled indexing releases its flush observer")
                self.assertFalse(self.manager._memory.cards)
                self.assertFalse(self.manager._memory._queued_segment_ids)
                self.assertTrue(all(segment.status.value == "pending" for segment in self.manager._memory.segments.values()))
                self.manager.config.episodic_memory.enabled = True
                await wait_for_runtime(self.manager, self.manager.flush_memory_indexing(),
                    label="Reenabled indexing completes the retained backlog")
                self.assertEqual(len(self.manager._memory.cards), len(self.manager._memory.segments))
            finally:
                release.set()
                if observer is not None and not observer.done():
                    observer.cancel()
                    await asyncio.gather(observer, return_exceptions=True)

    async def test_close_releases_a_flush_observer_without_discarding_pending_segments(self):
        self.manager.config.episodic_memory.index_worker_count = 1
        entered, flushing = asyncio.Event(), asyncio.Event()
        original_join = None
        observer = None

        async def held_index(*args, **kwargs):
            entered.set()
            await asyncio.Event().wait()

        async def observed_join():
            flushing.set()
            await original_join()

        with patch.object(self.manager._activity.models, "index", held_index):
            try:
                await interact_and_idle(self.manager, self.agent, "First remembered operation.")
                await wait_for_runtime(self.manager, entered.wait(), label="Index provider is waiting")
                self.client.responses = ["Final Answer: Another operation.", "Action: set_activity_intent(intent={'kind': 'idle'})"]
                await interact_and_idle(self.manager, self.agent, "Second remembered operation.")
                queue = self.manager._memory._queue
                self.assertGreater(queue.qsize(), 0)
                original_join = queue.join
                with patch.object(queue, "join", observed_join):
                    observer = asyncio.create_task(self.manager.flush_memory_indexing())
                    await flushing.wait()
                    await self.manager.close()
                    with self.assertRaisesRegex(RuntimeError, "closed"):
                        await wait_for_runtime(self.manager, observer, label="Closed indexing releases its flush observer")
                self.assertFalse(self.manager._memory._queued_segment_ids)
                self.assertTrue(all(segment.status.value == "pending" for segment in self.manager._memory.segments.values()))
            finally:
                if observer is not None and not observer.done():
                    observer.cancel()
                    await asyncio.gather(observer, return_exceptions=True)

    async def returned_during_cancellation(self, operation):
        entered = asyncio.Event()
        workers = ()

        async def returned_label(*args, **kwargs):
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                # A provider may win its cancellation race with a factual result.
                return json.dumps(self.client.labels)

        with patch.object(self.manager._activity.models, "index", returned_label):
            try:
                await interact_and_idle(self.manager, self.agent, "Remember one personal result.")
                await wait_for_runtime(self.manager, entered.wait(), label="Indexing starts")
                if self.manager._activity.workers:
                    await asyncio.gather(*tuple(self.manager._activity.workers))
                workers = tuple(self.manager._memory._workers)
                await operation(workers)
                self.assertTrue(all(worker.done() for worker in workers))
                self.assertFalse(self.manager._memory._queued_segment_ids)
            finally:
                # Also clean up a deliberately failing pre-fix reproduction.
                self.manager._memory._closing = True
                for worker in workers:
                    if not worker.done():
                        worker.cancel()
                await asyncio.gather(*workers, return_exceptions=True)

    async def test_close_cannot_leave_a_cancelled_indexer_waiting_for_another_item(self):
        async def close(workers):
            await self.manager.close()
        await self.returned_during_cancellation(close)

    async def test_restore_suspension_finishes_when_an_index_result_wins_cancellation(self):
        async def suspend(workers):
            await wait_for_runtime(self.manager, self.manager._memory.suspend_for_restore(),
                label="Indexing suspension drains cooperative workers")
        await self.returned_during_cancellation(suspend)
