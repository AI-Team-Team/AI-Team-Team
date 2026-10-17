"""Publication, activity reconstruction, and admission share one restore lifetime."""

import asyncio
import sqlite3
import threading
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from ai_team_team import Agent, LLMResponse, StatePersistenceError
from test.test_att.test_autonomous_activity_phase0._fixtures import (
    AsyncBarrier,
    ModelStep,
    ScriptedModelClient,
)

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

    async def test_new_admission_cannot_overlap_postpublication_reconstruction(self):
        checkpoint, owner, client = await self.interrupted_checkpoint()
        committed, release, admission_waiting = asyncio.Event(), asyncio.Event(), asyncio.Event()
        response = AsyncBarrier()
        client.steps.extend(
            (
                ModelStep(LLMResponse(text="Continuing after recovery"), response),
                ModelStep(idle()),
            )
        )
        original_commit = self.manager._records.commit
        original_acquire = self.manager._activity.lock.acquire
        activating = None

        async def commit(records, **kwargs):
            receipt = await original_commit(records, **kwargs)
            if any(
                row.table_name == "activity_admissions"
                and row.values["disposition"] == "interrupted"
                for row in records
            ):
                committed.set()
                await release.wait()
            return receipt

        async def acquire():
            if asyncio.current_task() is activating:
                admission_waiting.set()
            return await original_acquire()

        with (
            patch.object(self.manager._records, "commit", commit),
            patch.object(self.manager._activity.lock, "acquire", acquire),
        ):
            loading = asyncio.create_task(self.manager.load_state(checkpoint))
            try:
                await asyncio.wait_for(committed.wait(), 10)
                activating = asyncio.create_task(self.manager.activate_agent(owner))
                await asyncio.wait_for(admission_waiting.wait(), 5)
                self.assertFalse(activating.done())
                self.assertTrue(self.manager._restore_in_progress)
                self.assertFalse(client.requests)
                release.set()
                await asyncio.wait_for(loading, 10)
                admission = await asyncio.wait_for(activating, 10)
                await response.wait_entered()
                self.assertTrue(self.manager._activity.sessions[owner].active)
                response.release()
                await asyncio.wait_for(
                    self.manager.wait_for_activity_checkpoint(
                        admission.admission_id, intent="idle"
                    ),
                    10,
                )
                await self.settle()
            finally:
                release.set()
                response.release()
                await asyncio.gather(
                    loading, *([activating] if activating else []), return_exceptions=True
                )
        self.assertEqual(len(client.requests), 2)
        self.assertEqual(self.manager.inspect_agent_activity(owner).intent, "idle")
        self.assertFalse(self.manager._activity.workers)

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
        self.assertTrue(
            all(row.values["outcome"] != "pending" for row in self.records("model_requests"))
        )
        self.assertFalse(self.manager._activity.pending_notices(owner))

    async def test_failed_postpublication_reset_is_reported_and_blocks_activity(self):
        checkpoint, owner, client = await self.interrupted_checkpoint()
        original = self.manager._records.commit

        async def reject_reset(records, **kwargs):
            if any(
                row.table_name == "activity_admissions"
                and row.values["disposition"] == "interrupted"
                for row in records
            ):
                raise StatePersistenceError("Synthetic rejected recovery bookkeeping")
            return await original(records, **kwargs)

        with patch.object(self.manager._records, "commit", reject_reset):
            with self.assertRaises(StatePersistenceError):
                await self.manager.load_state(checkpoint)
        self.assertEqual(self.manager.root_ai.agent_id, owner)
        self.assertTrue(self.manager._activity.recovery_required)
        self.assertFalse(self.manager._restore_in_progress)
        with self.assertRaises(RuntimeError):
            await self.manager.activate_agent(owner)
        self.assertFalse(client.requests)
        # A later successful restore can repair the local recovery boundary.
        client.steps.append(ModelStep(idle()))
        await self.manager.load_state(checkpoint)
        await self.settle()
        self.assertFalse(self.manager._activity.recovery_required)
        self.assertEqual(self.manager.inspect_agent_activity(owner).intent, "idle")

    async def test_reset_failure_takes_precedence_over_cancellation_of_the_observer(self):
        checkpoint, owner, client = await self.interrupted_checkpoint()
        entered, release = asyncio.Event(), asyncio.Event()
        original = self.manager._records.commit

        async def reject_reset(records, **kwargs):
            if any(
                row.table_name == "activity_admissions"
                and row.values["disposition"] == "interrupted"
                for row in records
            ):
                entered.set()
                await release.wait()
                raise StatePersistenceError("Synthetic rejected recovery bookkeeping")
            return await original(records, **kwargs)

        with patch.object(self.manager._records, "commit", reject_reset):
            loading = asyncio.create_task(self.manager.load_state(checkpoint))
            try:
                await asyncio.wait_for(entered.wait(), 10)
                loading.cancel()
                release.set()
                with self.assertRaises(StatePersistenceError):
                    await loading
            finally:
                release.set()
                await asyncio.gather(loading, return_exceptions=True)
        self.assertEqual(self.manager.root_ai.agent_id, owner)
        self.assertTrue(self.manager._activity.recovery_required)
        self.assertFalse(client.requests)

    async def test_close_waits_for_accepted_recovery_without_closing_the_writer_early(self):
        checkpoint, owner, client = await self.interrupted_checkpoint()
        entered, release, close_entered = asyncio.Event(), asyncio.Event(), asyncio.Event()
        original_commit = self.manager._records.commit
        original_close = self.manager._activity.close
        original_acquire = self.manager._runtime_gate.acquire

        async def commit(records, **kwargs):
            receipt = await original_commit(records, **kwargs)
            if any(
                row.table_name == "activity_admissions"
                and row.values["disposition"] == "interrupted"
                for row in records
            ):
                entered.set()
                await release.wait()
            return receipt

        async def close():
            self.assertIn(owner, self.manager._activity.sessions)
            self.assertFalse(self.manager._restore_in_progress)
            await original_close()

        async def acquire():
            if asyncio.current_task() is self.manager._close_task:
                close_entered.set()
            return await original_acquire()

        with (
            patch.object(self.manager._records, "commit", commit),
            patch.object(self.manager._activity, "close", close),
            patch.object(self.manager._runtime_gate, "acquire", acquire),
        ):
            loading = asyncio.create_task(self.manager.load_state(checkpoint))
            close_task = None
            try:
                await asyncio.wait_for(entered.wait(), 10)
                close_task = asyncio.create_task(self.manager.close())
                await asyncio.wait_for(close_entered.wait(), 5)
                self.assertFalse(close_task.done())
                self.assertFalse(self.manager._persistence._closed)
                release.set()
                await asyncio.wait_for(asyncio.gather(loading, close_task), 10)
            finally:
                release.set()
                await asyncio.gather(
                    loading, *([close_task] if close_task else []), return_exceptions=True
                )
        self.assertTrue(self.manager._closed)
        self.assertFalse(client.requests)
        with closing(sqlite3.connect(checkpoint)) as database:
            self.assertNotIn(
                ("pending",),
                database.execute(
                    "SELECT outcome FROM model_requests WHERE agent_id=?", (owner,)
                ).fetchall(),
            )
