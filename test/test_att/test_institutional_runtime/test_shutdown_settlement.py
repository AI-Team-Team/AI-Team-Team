"""Shutdown fencing rejects new effects, not factual outcomes already returned."""

import asyncio
from unittest.mock import patch

from ai_team_team.core.exceptions import RuntimeAdmissionClosedError, StatePersistenceError
from test.async_waits import wait_for_runtime
from test.test_att.test_agent_activity._support import ActivityTestCase, call, personal_control_contract


class InstitutionalShutdownSettlementTests(ActivityTestCase):
    async def test_returned_foreground_outcome_settles_while_close_waits_for_runtime_gate(self):
        events = []
        self.manager.on_system_event = lambda name, payload: events.append((name, payload))

        async def rejected_notice(error):
            raise error

        for error in (RuntimeAdmissionClosedError("Admission closed"), StatePersistenceError("Writer failed")):
            with patch.object(self.manager.logger, "exception") as errors:
                self.manager._governance.track("retained-position-outbox", rejected_notice(error))
                await asyncio.gather(*tuple(self.manager._governance.tasks.values()), return_exceptions=True)
                if isinstance(error, RuntimeAdmissionClosedError):
                    errors.assert_not_called()
                else:
                    errors.assert_called_once()
        await self.manager.flush_callbacks()
        self.assertTrue(any(name == "governance_admission_deferred" for name, _ in events))
        started, release, settling = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def accepted_operation():
            started.set()
            await release.wait()
            return "The already accepted operation returned."

        self.manager.register_tool("accepted_operation", func=accepted_operation,
            execution_contract=personal_control_contract())
        self.steps(call("accepted_operation"))
        finish = self.manager._executions.finish_result

        async def observe_settlement(job, result):
            settling.set()
            return await finish(job, result)

        with patch.object(self.manager._executions, "finish_result", observe_settlement), patch.object(self.manager.logger, "error") as errors:
            await self.manager.activate_agent(self.root.agent_id)
            await wait_for_runtime(self.manager, started.wait(), label="Accepted tool begins")
            await self.manager._runtime_gate.acquire()
            try:
                closing = asyncio.create_task(self.manager.close())
                async def fenced():
                    while not self.manager._closing:
                        await asyncio.sleep(0)
                await wait_for_runtime(self.manager, fenced(), label="Shutdown fences the current generation")
                release.set()
                await wait_for_runtime(self.manager, settling.wait(), label="Returned outcome reaches local settlement")
            finally:
                self.manager._runtime_gate.release()
                release.set()
            await wait_for_runtime(self.manager, closing, label="Shutdown drains the returned outcome")
            errors.assert_not_called()
        execution = self.records("executions")[0]
        self.assertEqual(execution.values["status"], "completed")
        self.assertFalse(execution.values["outcome_unconfirmed"])
        self.assertEqual(len(self.records("execution_payloads")), 2)
