"""Ended executor contexts cannot regain managed authority through a new admission."""

import asyncio
import threading
from pathlib import Path
from unittest.mock import patch

from ai_team_team import Agent, LLMResponse, Tool, ToolCall
from ai_team_team.core.tool_runtime import ToolExecutor

from ._support import ActivityTestCase, idle


class ExecutionAuthorityTests(ActivityTestCase):
    async def test_cancelled_sibling_cannot_start_a_write_after_a_new_admission(self):
        started, cancelled, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        library = self.manager.libraries[self.root.private_doc_library_id]
        refused = []
        unwanted = Agent("LateRegistration", "Researcher", self.client)

        async def cancel_batch() -> str:
            await started.wait()
            raise asyncio.CancelledError("Cancel this foreground batch")

        async def late_write() -> str:
            started.set()
            while not release.is_set():
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    cancelled.set()
            try:
                self.manager.register_agent(unwanted)
            except PermissionError:
                pass
            else:
                self.fail("An ended execution must not register a new identity.")
            try:
                await self.manager.deliver_agent_mail(
                    self.root.agent_id, message_type="late", payload={}
                )
            except PermissionError:
                pass
            else:
                self.fail("An ended execution must not accept new addressed sources.")
            try:
                library.write_file("late.txt", "NEW_WRITE_FROM_ENDED_EXECUTION")
            except PermissionError as error:
                refused.append(str(error))
                raise
            return "Must not succeed"

        self.manager.register_tool("cancel_batch", func=cancel_batch)
        self.manager.register_tool("late_write", func=late_write)
        self.steps(
            LLMResponse(
                tool_calls=[
                    ToolCall("cancel", "cancel_batch", {}),
                    ToolCall("late", "late_write", {}),
                ]
            ),
            idle(),
        )
        generation = self.manager._resources.generation
        try:
            old = await self.manager.activate_agent(self.root.agent_id)
            with self.assertRaises(asyncio.CancelledError):
                await self.wait(old)
            await asyncio.wait_for(cancelled.wait(), 5)
            workers = tuple(self.manager._activity.workers)
            await asyncio.gather(*workers, return_exceptions=True)
            new = await self.manager.activate_agent(self.root.agent_id)
            await self.wait(new)
            self.assertNotEqual(old.admission_id, new.admission_id)
            self.assertEqual(self.manager._resources.generation, generation)
        finally:
            release.set()
            tasks = tuple(self.manager._activity.tool_tasks)
            await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 10)
        self.assertEqual(len(refused), 1)
        self.assertNotIn(unwanted.agent_id, self.manager._agents_by_id)
        self.assertNotIn(f"PDL-{unwanted.agent_id}", self.manager.libraries)
        self.assertFalse(self.root.agent_inbox)
        self.assertFalse(Path(library.root_dir, "late.txt").exists())
        execution = next(
            row for row in self.records("executions") if row.values["tool_name"] == "late_write"
        )
        self.assertEqual(execution.values["status"], "running")
        self.assertEqual(execution.values["outcome_unconfirmed"], 1)
        self.assertNotIn("NEW_WRITE_FROM_ENDED_EXECUTION", str(self.root.message_history))

    async def test_cancelled_synchronous_tool_cannot_start_a_late_write(self):
        started, release, finished = threading.Event(), threading.Event(), threading.Event()
        library = self.manager.libraries[self.root.private_doc_library_id]
        refused = []

        def late_sync_write() -> str:
            started.set()
            try:
                if not release.wait(10):
                    raise TimeoutError("The synchronous test tool was not released.")
                try:
                    library.write_file("sync-late.txt", "MUST_NOT_BE_WRITTEN")
                except PermissionError as error:
                    refused.append(str(error))
                    raise
                return "Must not succeed"
            finally:
                finished.set()

        tool = Tool("late_sync_write", func=late_sync_write)
        task = asyncio.create_task(
            ToolExecutor(None, self.root, self.manager).execute(tool.name, tools={tool.name: tool})
        )
        try:
            self.assertTrue(await asyncio.to_thread(started.wait, 5))
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        finally:
            release.set()
            self.assertTrue(await asyncio.to_thread(finished.wait, 5))
            await asyncio.gather(task, return_exceptions=True)
        self.assertEqual(len(refused), 1)
        self.assertFalse(Path(library.root_dir, "sync-late.txt").exists())

    async def test_already_entered_atomic_file_operation_settles_after_cancellation(self):
        started, release, finished = threading.Event(), threading.Event(), threading.Event()
        library = self.manager.libraries[self.root.private_doc_library_id]
        failures = []

        def fsync(_descriptor):
            started.set()
            if not release.wait(10):
                raise TimeoutError("The accepted file operation was not released.")

        def accepted_write() -> str:
            try:
                library.write_file_atomic("accepted.txt", "ACCEPTED_ATOMIC_CONTENT")
                return "written"
            except Exception as error:
                failures.append(error)
                raise
            finally:
                finished.set()

        tool = Tool("accepted_write", func=accepted_write)
        with patch("ai_team_team.doc_library.os.fsync", fsync):
            task = asyncio.create_task(
                ToolExecutor(None, self.root, self.manager).execute(
                    tool.name, tools={tool.name: tool}
                )
            )
            try:
                self.assertTrue(await asyncio.to_thread(started.wait, 5))
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            finally:
                release.set()
                self.assertTrue(await asyncio.to_thread(finished.wait, 5))
                await asyncio.gather(task, return_exceptions=True)
        self.assertFalse(failures)
        self.assertEqual(library.read_text("accepted.txt"), "ACCEPTED_ATOMIC_CONTENT")

    async def test_returned_tool_cannot_implicitly_delegate_its_authority(self):
        release = asyncio.Event()
        children, refused = [], []
        library = self.manager.libraries[self.root.private_doc_library_id]

        async def spawn() -> str:
            async def unsupported_background_write():
                await release.wait()
                try:
                    library.write_file("implicit-background.txt", "MUST_NOT_BE_WRITTEN")
                except PermissionError as error:
                    refused.append(str(error))

            children.append(asyncio.create_task(unsupported_background_write()))
            return "Foreground callable returned"

        tool = Tool("spawn", func=spawn)
        try:
            result = await ToolExecutor(None, self.root, self.manager).execute(
                tool.name, tools={tool.name: tool}
            )
            self.assertFalse(result.failed)
        finally:
            release.set()
            await asyncio.wait_for(asyncio.gather(*children), 5)
        self.assertEqual(len(refused), 1)
        self.assertFalse(Path(library.root_dir, "implicit-background.txt").exists())
