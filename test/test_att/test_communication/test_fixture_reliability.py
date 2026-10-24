"""Regression coverage for communication waits and exceptional fixture teardown."""

import asyncio
import os
import sqlite3
import unittest
from contextlib import closing
from unittest.mock import patch

from ai_team_team import Agent, ParentApprovalCommunicationConfig
from test.test_att.test_communication._support import CommunicationTestCase


class TestCommunicationWaits(CommunicationTestCase):
    async def _create_request(self, *, rationale="wait regression", db_path=None, manager=None):
        if manager is None:
            manager = self.manager(ParentApprovalCommunicationConfig(), db_path=db_path)
        sender = manager.create_agent_team(self.root, parent=self.root, member_count=3)
        recipient = manager.create_agent_team(self.root, parent=self.root, member_count=3)
        result = await manager.broker.request_peer_communication(
            sender, recipient, sender.members[0].agent_id, rationale
        )
        return manager, manager.broker.communication_requests[result.request_id]

    async def _await_task_cleanup(self, task):
        """Wait for the production completion callbacks registered before this marker."""
        completed = asyncio.Event()
        task.add_done_callback(lambda _: completed.set())
        await asyncio.wait_for(completed.wait(), timeout=10)

    async def test_removed_notification_failure_is_not_mistaken_for_idle(self):
        manager = self.manager(ParentApprovalCommunicationConfig())
        failure = RuntimeError("sensitive-worker-error-marker")

        async def failed_notification(session, agent):
            raise failure

        with patch.object(manager._activity, "run_invocation", failed_notification):
            with self.assertLogs(manager.logger, level="ERROR"):
                _, request = await self._create_request(manager=manager)
                approval_task = manager.broker._approval_tasks.history[0][1]
                await self._await_task_cleanup(approval_task)
                async with asyncio.timeout(10):
                    while not manager._activity.workers.history:
                        await asyncio.sleep(0)
                notification = manager._activity.workers.history[0]
                await self._await_task_cleanup(notification)

        self.assertNotIn(notification, manager._activity.workers)
        self.assertEqual(self.client.calls, [])
        with self.assertRaises(RuntimeError) as caught:
            await self.wait_for_governance_idle(request)
        self.assertIs(caught.exception, failure)
        with self.assertRaises(RuntimeError) as caught:
            await self.wait_for_status(request, "PENDING")
        self.assertIs(caught.exception, failure)
        diagnostic = self._request_diagnostics(manager, request.request_id, "IDLE")
        self.assertIn('"state": "failed"', diagnostic)
        self.assertIn('"error_type": "RuntimeError"', diagnostic)
        self.assertNotIn(str(failure), diagnostic)

    async def test_replaced_task_key_does_not_hide_a_prior_failure(self):
        self.client.respond = False
        manager, request = await self._create_request()
        await self.wait_for_governance_idle(request)
        case_id = manager._governance.latest(
            "communication", request.request_id, request.approval_principals[0]
        ).case_id
        key = f"resolve:{case_id}"
        failure = RuntimeError("earlier resolution failed")

        async def fail():
            raise failure

        async def succeed():
            return None

        with self.assertLogs(manager.logger, level="ERROR"):
            manager._governance.track(key, fail())
            previous = manager._governance.tasks[key]
            await self._await_task_cleanup(previous)
        manager._governance.track(key, succeed())
        replacement = manager._governance.tasks[key]
        await self._await_task_cleanup(replacement)

        retained = [
            task for recorded_key, task in manager._governance.tasks.history if recorded_key == key
        ]
        self.assertEqual(retained, [previous, replacement])
        with self.assertRaises(RuntimeError) as caught:
            await self.wait_for_governance_idle(request)
        self.assertIs(caught.exception, failure)

    async def test_worker_timeout_is_preserved_without_relabeling_it(self):
        self.client.respond = False
        manager, request = await self._create_request()
        await self.wait_for_governance_idle(request)
        case_id = manager._governance.latest(
            "communication", request.request_id, request.approval_principals[0]
        ).case_id
        failure = TimeoutError("independent worker timeout")

        async def fail():
            raise failure

        with self.assertLogs(manager.logger, level="ERROR"):
            manager._governance.track(f"resolve:{case_id}", fail())
            task = manager._governance.tasks[f"resolve:{case_id}"]
            await self._await_task_cleanup(task)

        with self.assertRaises(TimeoutError) as caught:
            await self.wait_for_governance_idle(request)
        self.assertIs(caught.exception, failure)
        with self.assertRaises(TimeoutError) as caught:
            await self.wait_for_status(request, "PENDING")
        self.assertIs(caught.exception, failure)

    async def test_idle_deadline_does_not_cancel_the_accepted_worker(self):
        self.client.respond = False
        manager, request = await self._create_request()
        await self.wait_for_governance_idle(request)
        case_id = manager._governance.latest(
            "communication", request.request_id, request.approval_principals[0]
        ).case_id
        entered = asyncio.Event()
        release = asyncio.Event()

        async def blocked():
            entered.set()
            await release.wait()

        manager._governance.track(f"resolve:{case_id}", blocked())
        task = manager._governance.tasks[f"resolve:{case_id}"]
        try:
            await asyncio.wait_for(entered.wait(), timeout=10)
            with self.assertRaisesRegex(AssertionError, "workers did not settle"):
                await self.wait_for_governance_idle(request, timeout=0.02)
            self.assertFalse(task.done())
            self.assertFalse(task.cancelled())
            release.set()
            await self.wait_for_governance_idle(request)
            self.assertIsNone(task.result())
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)

    async def test_failed_worker_is_reported_while_a_sibling_remains_blocked(self):
        self.client.respond = False
        manager, request = await self._create_request()
        await self.wait_for_governance_idle(request)
        case_id = manager._governance.latest(
            "communication", request.request_id, request.approval_principals[0]
        ).case_id
        entered = asyncio.Event()
        release = asyncio.Event()
        failure = RuntimeError("worker failed while its sibling was blocked")

        async def blocked():
            entered.set()
            await release.wait()

        async def fail():
            await entered.wait()
            raise failure

        with self.assertLogs(manager.logger, level="ERROR"):
            manager._governance.track(f"resolve:{case_id}", blocked())
            sibling = manager._governance.tasks[f"resolve:{case_id}"]
            key = f"mail:{case_id}:{self.root.agent_id}"
            manager._governance.track(key, fail())
            failed = manager._governance.tasks[key]
            try:
                with self.assertRaises(RuntimeError) as caught:
                    await self.wait_for_governance_idle(request)
                self.assertIs(caught.exception, failure)
                self.assertFalse(sibling.done())
                self.assertFalse(sibling.cancelled())
            finally:
                release.set()
                await asyncio.gather(sibling, failed, return_exceptions=True)

    async def test_timeout_reports_vote_progress_without_private_payload(self):
        self.client.respond = False
        manager, request = await self._create_request(rationale="sensitive-rationale-marker")
        await self.wait_for_governance_idle(request)

        with self.assertRaisesRegex(AssertionError, "did not settle") as caught:
            await self.wait_for_status(request, "APPROVED", timeout=0.02)

        diagnostic = str(caught.exception)
        self.assertIn(request.request_id, diagnostic)
        self.assertIn('"votes": 0', diagnostic)
        self.assertIn('"voters": 1', diagnostic)
        self.assertIn('"status": "PENDING"', diagnostic)
        self.assertNotIn(request.rationale, diagnostic)
        self.assertEqual(manager.broker.agreements, {})

    async def test_wait_reads_the_current_request_after_registry_replacement(self):
        self.client.respond = False
        manager, request = await self._create_request()
        await self.wait_for_governance_idle(request)
        replacement = request.model_copy(deep=True)
        manager.broker.communication_requests[request.request_id] = replacement

        observed = await self.wait_for_status(request, "PENDING")

        self.assertIs(observed, replacement)

    async def test_unexpected_terminal_status_fails_without_waiting_for_timeout(self):
        self.client.approved = False
        _, request = await self._create_request()
        await self.wait_for_status(request, "DENIED")

        with self.assertRaisesRegex(AssertionError, "Unexpected terminal communication status"):
            await self.wait_for_status(request, "APPROVED")

    async def test_staged_approval_is_not_ready_until_authoritative_commit_finishes(self):
        db_path = os.path.join(self.workspace, "commit-barrier.db")
        manager = self.manager(ParentApprovalCommunicationConfig(), db_path=db_path)
        sender = manager.create_agent_team(self.root, parent=self.root, member_count=3)
        recipient = manager.create_agent_team(self.root, parent=self.root, member_count=3)
        entered = asyncio.Event()
        release = asyncio.Event()
        original_commit = manager._records.commit

        async def gated_commit(records, **kwargs):
            if kwargs.get("dirty", {}).get("communication_agreements"):
                entered.set()
                await release.wait()
            return await original_commit(records, **kwargs)

        with patch.object(manager._records, "commit", gated_commit):
            try:
                result = await manager.broker.request_peer_communication(
                    sender, recipient, sender.members[0].agent_id, "commit barrier"
                )
                request = manager.broker.communication_requests[result.request_id]
                async with asyncio.timeout(10.0):
                    await entered.wait()
                self.assertEqual(request.status.value, "PENDING")

                with self.assertRaisesRegex(AssertionError, '"transaction_busy": true'):
                    await self.wait_for_status(request, "APPROVED", timeout=0.02)

                self.assertFalse(
                    any(
                        task.cancelled()
                        for task in self._request_tasks(manager, request.request_id).values()
                    )
                )
                release.set()
                await self.wait_for_status(request, "APPROVED")
                await self.wait_for_governance_idle(request)
            finally:
                release.set()

        # No save/flush shortcut: the domain commit itself must be durable.
        with closing(sqlite3.connect(db_path)) as database:
            self.assertEqual(
                database.execute(
                    "SELECT status FROM communication_requests WHERE request_id = ?",
                    (request.request_id,),
                ).fetchone(),
                ("APPROVED",),
            )
            self.assertEqual(
                database.execute(
                    "SELECT COUNT(*) FROM communication_agreements WHERE created_from_request_id = ?",
                    (request.request_id,),
                ).fetchone(),
                (1,),
            )


class TestCommunicationCleanup(unittest.IsolatedAsyncioTestCase):
    async def _assert_interrupted_fixture_closes_managers(self, *, cancelled):
        old_cwd = os.getcwd()
        managers = []
        closed = []
        workspaces = []

        class InterruptedFixture(CommunicationTestCase):
            async def runTest(self):
                workspaces.append(self.workspace)
                for index in range(2):
                    manager = self.manager(
                        db_path=os.path.join(self.workspace, f"state-{index}.db"),
                        root_ai=Agent(f"Root-{index}", "Root governor", self.client),
                    )
                    managers.append(manager)
                    manager.create_agent_team(manager.root_ai, parent=manager.root_ai, member_count=3)
                    await manager.save_state()
                    original_close = manager.close

                    async def close_before_removal(owner=manager, close=original_close):
                        workspace_exists = os.path.isdir(self.workspace)
                        cwd_is_workspace = os.path.samefile(os.getcwd(), self.workspace)
                        await close()
                        closed.append(owner)
                        self.assertTrue(workspace_exists)
                        self.assertTrue(cwd_is_workspace)

                    manager.close = close_before_removal
                if cancelled:
                    raise asyncio.CancelledError()
                self.fail("Intentional fixture failure.")

        result = unittest.TestResult()
        # IsolatedAsyncioTestCase owns its own loop, outside this test's loop.
        await asyncio.to_thread(InterruptedFixture().run, result)

        self.assertEqual(result.testsRun, 1)
        self.assertEqual(len(result.failures), 0 if cancelled else 1)
        self.assertEqual(len(result.errors), 1 if cancelled else 0, result.errors)
        self.assertEqual(len(managers), 2)
        self.assertEqual(closed, list(reversed(managers)))
        self.assertTrue(all(manager._closed for manager in managers))
        self.assertEqual(os.getcwd(), old_cwd)
        self.assertFalse(os.path.exists(workspaces[0]))

    async def test_failed_test_body_still_closes_writers_before_removing_workspace(self):
        await self._assert_interrupted_fixture_closes_managers(cancelled=False)

    async def test_cancelled_test_body_still_closes_writers_before_removing_workspace(self):
        await self._assert_interrupted_fixture_closes_managers(cancelled=True)
