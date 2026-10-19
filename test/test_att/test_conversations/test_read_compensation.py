"""Cancellation cleanup is an exact receipt-scoped exception, not a cursor bypass."""

import asyncio

from ai_team_team import StatePersistenceError
from ai_team_team.core.manager.activity.values import capture
from ai_team_team.database.persistence.coordinator import PersistenceCoordinator
from ai_team_team.database.persistence.records import DomainRecord, merge_records, thaw
from ._support import ChatTestCase


class ReadCompensationTests(ChatTestCase):
    async def preparation(self):
        sent = await self.manager.send_direct_message(self.other.agent_id, "A body read", actor=self.root)
        original = self.manager._messaging.view(self.other, sent.message_id)
        await self.manager.read_chat_message(sent.message_id, actor=self.other)
        prepared = self.manager._messaging.view(self.other, sent.message_id)
        operation = next(identifier for identifier, (_receipt, rows) in self.manager._records.receipts.items()
                         if identifier.startswith("CHAT-READ-") and rows == (prepared,))
        rollback = capture(self.manager, "chat_personal_views", view_id=original.values["view_id"],
            **{key: original.values[key] for key in ("read_at", "read_revision_number", "unread_override")})
        proof = {"operation_id": operation, "prepared": thaw(prepared.values), "previous": thaw(original.values)}
        return sent, prepared, rollback, proof

    async def test_default_monotonic_validation_and_exact_projection_fields_remain_strict(self):
        _sent, prepared, rollback, proof = await self.preparation()
        with self.assertRaisesRegex(StatePersistenceError, "watermark"):
            merge_records((prepared,), (rollback,))
        changed = DomainRecord.capture("chat_personal_views", {**thaw(rollback.values), "deleted": 1})
        with self.assertRaisesRegex(StatePersistenceError, "watermark"):
            merge_records((prepared,), (changed,), read_compensations=(proof,))
        self.assertEqual(merge_records((prepared,), (rollback,), read_compensations=(proof,)), (rollback,))

    async def test_runtime_rejects_missing_receipts_and_intervening_personal_updates(self):
        sent, _prepared, rollback, proof = await self.preparation()
        with self.assertRaisesRegex(ValueError, "receipt"):
            await self.manager._records.commit((rollback,), read_compensations=({**proof, "operation_id": "missing"},))
        await self.manager.control_chat_message("mark_message_unread", sent.message_id, actor=self.other)
        with self.assertRaisesRegex(ValueError, "receipt"):
            await self.manager._records.commit((rollback,), read_compensations=(proof,))

    async def test_sql_rejects_a_compensation_without_its_exact_preparation_receipt(self):
        _sent, prepared, rollback, proof = await self.preparation()
        snapshot = dict(self.manager._capture_state_snapshot(self.manager._new_dirty_state()))
        snapshot.update(records=(rollback,), _operations=(), _read_compensations=({**proof, "operation_id": "missing"},))
        store = self.manager._persistence._store(self.path)
        with self.assertRaisesRegex(StatePersistenceError, "preparation receipt"):
            await asyncio.to_thread(store.write, snapshot)
        await self.manager.load_state(self.path)
        self.assertEqual(self.manager._records.index[prepared.identity], prepared)

    async def test_coalescing_preserves_scoped_compensation_proof_without_weakening_other_updates(self):
        _sent, prepared, rollback, proof = await self.preparation()
        earlier = {"records": (prepared,), "state_version": 10}
        later = {"records": (rollback,), "state_version": 11, "_read_compensations": (proof,)}
        merged = PersistenceCoordinator._merge_snapshots(earlier, later)
        self.assertEqual(merged["records"], (rollback,))
        self.assertEqual(merged["_read_compensations"], (proof,))
        with self.assertRaisesRegex(StatePersistenceError, "watermark"):
            PersistenceCoordinator._merge_snapshots(earlier, {"records": (rollback,), "state_version": 11})
