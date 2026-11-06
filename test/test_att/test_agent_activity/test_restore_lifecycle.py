"""Required recovery settles in staging; publication and admission remain ordered."""

import asyncio
import sqlite3
import threading
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from ai_team_team import Agent, StatePersistenceError, StateRestoreError
from ai_team_team.core.exceptions import RuntimeAdmissionClosedError
from ai_team_team.core.manager.restore import preparation
from test.test_att.test_runtime_contracts._fixtures import AsyncBarrier, ModelStep, ScriptedModelClient

from ._support import ActivityTestCase, idle


class RestoreLifecycleTests(ActivityTestCase):
    async def interrupted_checkpoint(self):
        await self.manager.close()
        self.manager = self.make_manager(self.root, durable=True)
        self.manager.config.activity.model_requests_per_invocation = 1
        barrier = AsyncBarrier()
        self.client.steps.append(ModelStep(idle(), barrier))
        checkpoint = str(Path(self.workspace.name) / "interrupted.sqlite")
        try:
            await self.manager.activate_agent(self.root.agent_id)
            await barrier.wait_entered()
            await self.manager.save_state()
            with closing(sqlite3.connect(self.manager.db_path)) as source:
                with closing(sqlite3.connect(checkpoint)) as target:
                    source.backup(target)
            owner = self.root.agent_id
            await self.manager.close()
        finally:
            barrier.release()
        client = ScriptedModelClient()
        self.manager = self.make_manager(Agent("RestoreHost", "Architect", client))
        return checkpoint, owner, client

    async def test_new_admission_cannot_overlap_detached_recovery(self):
        checkpoint, owner, client = await self.interrupted_checkpoint()
        entered, release = asyncio.Event(), asyncio.Event()
        original = preparation.prepare_domain_recovery
        old_root = self.manager.root_ai
        client.steps.append(ModelStep(idle()))

        async def prepare(*args, **kwargs):
            result = await original(*args, **kwargs)
            entered.set()
            await release.wait()
            return result

        with patch.object(preparation, "prepare_domain_recovery", prepare):
            loading = asyncio.create_task(self.manager.load_state(checkpoint))
            try:
                await asyncio.wait_for(entered.wait(), 10)
                self.assertIs(self.manager.root_ai, old_root)
                self.assertTrue(self.manager._restore_in_progress)
                with self.assertRaises(RuntimeAdmissionClosedError):
                    await self.manager.activate_agent(old_root.agent_id)
                self.assertFalse(client.requests)
            finally:
                release.set()
                await asyncio.wait_for(loading, 10)
        await self.settle()
        self.assertEqual(len(client.requests), 1)
        self.assertEqual(self.manager.inspect_agent_activity(owner).intent, "idle")

    async def test_cancellation_after_publication_still_completes_activity_recovery(self):
        checkpoint, owner, client = await self.interrupted_checkpoint()
        client.steps.append(ModelStep(idle()))
        entered, release = threading.Event(), threading.Event()
        original = self.manager._discard_library_backups

        def cleanup(published):
            entered.set()
            if not release.wait(10):
                raise TimeoutError("The publication cleanup was not released.")
            return original(published)

        with patch.object(self.manager, "_discard_library_backups", cleanup):
            loading = asyncio.create_task(self.manager.load_state(checkpoint))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 5))
                self.assertEqual(self.manager.root_ai.agent_id, owner)
                loading.cancel()
                release.set()
                with self.assertRaises(asyncio.CancelledError):
                    await loading
            finally:
                release.set()
                await asyncio.gather(loading, return_exceptions=True)
        await self.settle()
        self.assertEqual(len(client.requests), 1)
        self.assertEqual(self.manager.inspect_agent_activity(owner).intent, "idle")
        self.assertFalse(self.manager._restore_in_progress)
        self.assertFalse(self.manager._activity.recovery_required)
        self.assertTrue(all(row.values["outcome"] != "pending" for row in self.records("model_requests")))

    async def test_failed_required_recovery_preserves_the_original_manager(self):
        checkpoint, owner, client = await self.interrupted_checkpoint()
        original = preparation.prepare_domain_recovery
        old_root, old_records = self.manager.root_ai, self.manager._records.snapshot()

        async def reject(*args, **kwargs):
            await original(*args, **kwargs)
            raise StatePersistenceError("Synthetic rejected recovery bookkeeping")

        with patch.object(preparation, "prepare_domain_recovery", reject):
            with self.assertRaises(StateRestoreError):
                await self.manager.load_state(checkpoint)
        self.assertIs(self.manager.root_ai, old_root)
        self.assertEqual(self.manager._records.snapshot(), old_records)
        self.assertFalse(self.manager._restore_in_progress)
        self.assertFalse(self.manager._activity.recovery_required)
        self.assertFalse(client.requests)
        client.steps.append(ModelStep(idle()))
        await self.manager.load_state(checkpoint)
        await self.settle()
        self.assertEqual(self.manager.inspect_agent_activity(owner).intent, "idle")

    async def test_required_recovery_failure_takes_precedence_over_observer_cancellation(self):
        checkpoint, _owner, client = await self.interrupted_checkpoint()
        entered, release = asyncio.Event(), asyncio.Event()
        old_root = self.manager.root_ai

        async def reject(*args, **kwargs):
            entered.set()
            await release.wait()
            raise StatePersistenceError("Synthetic rejected recovery bookkeeping")

        with patch.object(preparation, "prepare_domain_recovery", reject):
            loading = asyncio.create_task(self.manager.load_state(checkpoint))
            try:
                await asyncio.wait_for(entered.wait(), 10)
                loading.cancel()
                release.set()
                with self.assertRaises(StateRestoreError):
                    await loading
            finally:
                release.set()
                await asyncio.gather(loading, return_exceptions=True)
        self.assertIs(self.manager.root_ai, old_root)
        self.assertFalse(client.requests)

    async def test_close_waits_for_accepted_recovery_without_closing_the_writer_early(self):
        checkpoint, owner, client = await self.interrupted_checkpoint()
        entered, release, close_entered = asyncio.Event(), asyncio.Event(), asyncio.Event()
        original = preparation.prepare_domain_recovery
        acquire = self.manager._runtime_gate.acquire

        async def prepare(*args, **kwargs):
            result = await original(*args, **kwargs)
            entered.set()
            await release.wait()
            return result

        async def observed_acquire():
            if asyncio.current_task() is self.manager._close_task:
                close_entered.set()
            return await acquire()

        with patch.object(preparation, "prepare_domain_recovery", prepare), patch.object(self.manager._runtime_gate, "acquire", observed_acquire):
            loading = asyncio.create_task(self.manager.load_state(checkpoint))
            close_task = None
            try:
                await asyncio.wait_for(entered.wait(), 10)
                close_task = asyncio.create_task(self.manager.close())
                await asyncio.wait_for(close_entered.wait(), 5)
                self.assertFalse(close_task.done())
                self.assertFalse(self.manager._persistence._closed)
            finally:
                release.set()
                await asyncio.wait_for(asyncio.gather(loading, *([close_task] if close_task else [])), 10)
        self.assertTrue(self.manager._closed)
        self.assertEqual(self.manager.root_ai.agent_id, owner)
        self.assertFalse(client.requests)
        with closing(sqlite3.connect(checkpoint)) as database:
            self.assertNotIn(("pending",), database.execute("SELECT outcome FROM model_requests WHERE agent_id=?", (owner,)).fetchall())
