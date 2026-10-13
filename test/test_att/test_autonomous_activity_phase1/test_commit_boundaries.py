"""Accepted-operation identity, cancellation, and immutable scope boundaries."""

import asyncio
import unittest
from concurrent.futures import Future

from ai_team_team import StatePersistenceError
from ai_team_team.database.persistence.records import DomainRecord, FrozenObject, merge_records, thaw
from ai_team_team.database.persistence.receipts import settle_commit

from ._support import execution, invocation_graph, make_manager, model_request


class CommitBoundaryTests(unittest.IsolatedAsyncioTestCase):
    def test_direct_frozen_object_construction_cannot_smuggle_mutable_values(self):
        with self.assertRaisesRegex(ValueError, "mutable"):
            FrozenObject((("nested", []),))
        with self.assertRaisesRegex(ValueError, "unique"):
            FrozenObject((("key", 1), ("key", 2)))

    async def test_lost_response_retry_after_restore_returns_the_original_receipt(self):
        manager, path, _ = make_manager(self)
        owner = manager.root_ai.agent_id
        first = await manager._records.commit(invocation_graph(owner), operation_id="accepted-once")
        await manager.load_state(path)
        events = []
        manager.on_system_event = lambda *args: events.append(args)
        second = await manager._records.commit(invocation_graph(owner), operation_id="accepted-once")
        self.assertEqual(first, second)
        self.assertEqual(await manager._persistence.receipt(path, "accepted-once"), first)
        self.assertEqual(events, [])
        changed = list(invocation_graph(owner))
        values = thaw(changed[0].values)
        values["accepted_at"] = 0.5
        changed[0] = DomainRecord.capture("activity_admissions", values)
        with self.assertRaisesRegex(ValueError, "different records"):
            await manager._records.commit(changed, operation_id="accepted-once")

    async def test_write_failure_takes_precedence_over_cancelled_observer(self):
        completion = Future()
        observer = asyncio.create_task(settle_commit(asyncio.wrap_future(completion)))
        await asyncio.sleep(0)
        observer.cancel()
        await asyncio.sleep(0)
        completion.set_exception(StatePersistenceError("Injected writer failure"))
        with self.assertRaises(StatePersistenceError):
            await observer

    async def test_higher_version_cannot_change_captured_scope_or_reopen_admission(self):
        manager, _, _ = make_manager(self, volatile=True)
        original = execution(manager.root_ai.agent_id)
        values = thaw(original.values)
        values.update(tool_name="different_tool", state_version=2)
        with self.assertRaisesRegex(StatePersistenceError, "cannot be rewritten"):
            merge_records((original,), (DomainRecord.capture("executions", values),))
        admission = invocation_graph(manager.root_ai.agent_id)[0]
        closed = thaw(admission.values)
        closed.update(disposition="completed", state_version=2)
        reopened = {**closed, "disposition": "admitted", "state_version": 3}
        with self.assertRaisesRegex(StatePersistenceError, "cannot be reopened"):
            merge_records((DomainRecord.capture("activity_admissions", closed),),
                          (DomainRecord.capture("activity_admissions", reopened),))

    async def test_settlement_cannot_rewrite_outcome_on_an_idempotent_retry(self):
        manager, _, _ = make_manager(self)
        owner = manager.root_ai.agent_id
        await manager._records.commit(invocation_graph(owner))
        claim_id = await manager.token_budget.reserve_request(model_request(owner), 20, 30)
        await manager.token_budget.settle_claim(claim_id, settlement="known_usage", actual_usage=25, outcome="failed")
        with self.assertRaisesRegex(RuntimeError, "different outcome"):
            await manager.token_budget.settle_claim(claim_id, settlement="known_usage", actual_usage=25, outcome="completed")

    async def test_existing_claim_cannot_be_rebound_to_another_request_frame(self):
        manager, _, _ = make_manager(self, volatile=True)
        owner = manager.root_ai.agent_id
        await manager._records.commit(invocation_graph(owner))
        request = model_request(owner)
        claim_id = await manager.token_budget.reserve_request(request, 20, 30)
        changed = thaw(request.values)
        changed.update(frame_id="different-frame", state_version=2)
        with self.assertRaisesRegex(ValueError, "concrete request"):
            await manager.token_budget.reserve_request(DomainRecord.capture("model_requests", changed), 20, 30)
        self.assertEqual(manager._records.index[("model_token_claims", (claim_id,))].values["settlement"], "reserved")
