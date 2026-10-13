"""Scoped audit forensics and the common durable model-alias quota ledger."""

import asyncio
import sqlite3
import unittest
from contextlib import closing

from ai_team_team import StateRestoreError, TokenLimitExceededError

from ._support import invocation_graph, make_manager, model_request, record


def audit_records(owner):
    return (
        record("audit_runs", audit_id="audit", subject_agent_id=owner, temporary_team_id="audit-team",
               template={"name": "Health"}, electorate=["scoped-auditor"], runtime_generation=1,
               status="running", created_at=1.0, deadline=121.0, token_budget=1000),
        record("audit_participants", audit_id="audit", scoped_agent_id="scoped-auditor",
               identity_snapshot={"name": "Auditor"}, model_alias="fixture", position=0),
    )


def audit_request():
    return record("audit_model_requests", request_id="audit-request", audit_id="audit", scoped_agent_id="scoped-auditor",
                  invocation_id="audit-invocation", frame_id="audit-frame", input_version=1, model_alias="fixture",
                  attempt_index=1, dispatch_state="unsent", outcome="pending", created_at=1.0,
                  request_budget=120.0, sequence_budget=600.0)


class AuditQuotaTests(unittest.IsolatedAsyncioTestCase):
    async def test_audit_uses_scoped_evidence_without_ordinary_identities(self):
        manager, path, client = make_manager(self)
        owner = manager.root_ai.agent_id
        await manager._records.commit(audit_records(owner))
        claim = await manager.token_budget.reserve_request(audit_request(), 10, 20)
        await manager.token_budget.settle_claim(claim, settlement="unknown_sent")
        await manager.load_state(path)
        with closing(sqlite3.connect(path)) as database:
            self.assertEqual(database.execute("SELECT agent_id FROM agents").fetchall(), [(owner,)])
            self.assertEqual(database.execute("SELECT count(*) FROM teams").fetchone(), (0,))
            self.assertEqual(database.execute("SELECT count(*) FROM libraries").fetchone(), (1,))
            self.assertEqual(database.execute("SELECT count(*) FROM audit_participants").fetchone(), (1,))
            self.assertEqual(database.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual(client.requests, [])

    async def test_ordinary_and_audit_reservations_share_one_atomic_limit(self):
        manager, _, _ = make_manager(self, volatile=True)
        owner = manager.root_ai.agent_id
        manager.config.model_token_limits["fixture"] = 100
        await manager._records.commit((*invocation_graph(owner), *audit_records(owner)))
        results = await asyncio.gather(manager.token_budget.reserve_request(model_request(owner), 20, 40),
                                       manager.token_budget.reserve_request(audit_request(), 20, 40), return_exceptions=True)
        self.assertEqual(sum(isinstance(result, TokenLimitExceededError) for result in results), 1)
        self.assertEqual(manager.token_budget.available("fixture"), 40)
        # Legacy failover sees exactly the same remaining amount, without
        # double-counting durable reservations as process-local reservations.
        ordinary = manager.token_budget.reserve("fixture", 5, 5)
        self.assertEqual(manager.token_budget.available("fixture"), 30)
        manager.token_budget.release(ordinary)
        self.assertEqual(manager.token_budget.available("fixture"), 40)

    async def test_unknown_sent_usage_survives_restore_and_unsent_refunds(self):
        manager, path, _ = make_manager(self)
        owner = manager.root_ai.agent_id
        manager.config.model_token_limits["fixture"] = 100
        await manager._records.commit((*invocation_graph(owner), *audit_records(owner)))
        sent = await manager.token_budget.reserve_request(model_request(owner), 10, 40)
        unsent = await manager.token_budget.reserve_request(audit_request(), 10, 20)
        await manager.token_budget.settle_claim(sent, settlement="unknown_sent")
        await manager.token_budget.settle_claim(unsent, settlement="confirmed_unsent")
        self.assertEqual(manager.token_budget.available("fixture"), 50)
        await manager.load_state(path)
        self.assertEqual(manager.token_budget.available("fixture"), 50)
        await manager.token_budget.settle_claim(sent, settlement="unknown_sent")
        self.assertEqual(manager.token_budget.available("fixture"), 50)

    async def test_actual_usage_refunds_unused_budget_and_repeated_claim_is_idempotent(self):
        manager, _, _ = make_manager(self, volatile=True)
        owner = manager.root_ai.agent_id
        manager.config.model_token_limits["fixture"] = 100
        await manager._records.commit(invocation_graph(owner))
        request = model_request(owner)
        claim = await manager.token_budget.reserve_request(request, 10, 50)
        self.assertEqual(await manager.token_budget.reserve_request(request, 10, 50), claim)
        self.assertEqual(manager.token_budget.available("fixture"), 40)
        await manager.token_budget.settle_claim(claim, settlement="known_usage", actual_usage=25)
        self.assertEqual(manager.token_budget.available("fixture"), 75)
        await manager.token_budget.settle_claim(claim, settlement="known_usage", actual_usage=25)
        self.assertEqual(manager.token_budget.available("fixture"), 75)

    async def test_missing_audit_participant_is_corruption_not_a_root_fallback(self):
        manager, _, _ = make_manager(self, volatile=True)
        with self.assertRaisesRegex(Exception, "concrete durable prerequisite"):
            await manager._records.commit((audit_request(),))
        self.assertEqual(manager._records.snapshot(), ())

    async def test_unregistered_auditor_cannot_be_substituted_with_an_ordinary_agent(self):
        manager, path, _ = make_manager(self)
        owner = manager.root_ai.agent_id
        await manager._records.commit(audit_records(owner))
        with closing(sqlite3.connect(path)) as database:
            database.execute("UPDATE audit_participants SET scoped_agent_id=?", (owner,))
            database.commit()
        with self.assertRaises(StateRestoreError):
            await manager.load_state(path)
