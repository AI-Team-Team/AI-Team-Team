"""Known admission closure is deferred metadata, not a governance failure log."""

import asyncio
from unittest.mock import AsyncMock, patch

from ai_team_team import StatePersistenceError
from ai_team_team.core.exceptions import RuntimeAdmissionClosedError
from test.test_att.test_agent_activity._support import ActivityTestCase
from ._lock_support import ObservedLock


class InstitutionalAdmissionClosureTests(ActivityTestCase):
    def endpoints(self):
        self.manager.config.communication = {"policy": "parent_approval"}
        sender = self.manager.create_agent_team(self.root, parent=self.root)
        recipient = self.manager.create_agent_team(self.root, parent=self.root)
        return sender, recipient

    async def assert_closed_approval_is_deferred(self, field):
        sender, recipient = self.endpoints()
        emitted = []
        self.manager.on_system_event = lambda event, payload: emitted.append((event, payload))
        gate = ObservedLock(self.manager._governance.lock)
        with self.assertNoLogs(self.manager.broker.logger, level="ERROR"), patch.object(
                self.manager, "_emit_callback", wraps=self.manager._emit_callback) as dispatch, patch.object(
                self.manager._governance, "lock", gate):
            async with gate:
                result = await self.manager.broker.request_peer_communication(sender, recipient, sender.members[0].agent_id, "Retain a pending channel request.")
                task = next(iter(self.manager.broker._approval_tasks.values()))
                await gate.wait_for_attempt(task)
                setattr(self.manager, field, True)
            try:
                with self.assertRaises(RuntimeAdmissionClosedError):
                    await task
                await asyncio.sleep(0)
            finally:
                setattr(self.manager, field, False)
        await self.manager.flush_callbacks()
        self.assertEqual(self.manager.broker.communication_requests[result.request_id].status.value, "PENDING")
        self.assertFalse(self.manager.broker.agreements)
        self.assertFalse(self.manager._governance.cases)
        self.assertTrue(any(call.args[1] == "communication_approval_admission_deferred" for call in dispatch.call_args_list))
        if field != "_closing":
            self.assertTrue(any(event == "communication_approval_admission_deferred" for event, _payload in emitted))

    async def test_shutdown_closure_retains_pending_request_without_an_error_log(self):
        await self.assert_closed_approval_is_deferred("_closing")

    async def test_restore_closure_retains_pending_request_without_an_error_log(self):
        await self.assert_closed_approval_is_deferred("_restore_in_progress")

    async def test_a_real_writer_error_remains_an_approval_failure(self):
        sender, recipient = self.endpoints()
        with patch.object(self.manager._governance, "create_case", new=AsyncMock(side_effect=StatePersistenceError("Writer failed"))):
            with self.assertLogs(self.manager.broker.logger, level="ERROR") as logged:
                await self.manager.broker.request_peer_communication(sender, recipient, sender.members[0].agent_id, "A real failure must remain visible.")
                task = next(iter(self.manager.broker._approval_tasks.values()))
                with self.assertRaises(StatePersistenceError):
                    await task
                await asyncio.sleep(0)
        self.assertTrue(any("Communication approval task failed" in entry for entry in logged.output))
