import asyncio
import sqlite3
import threading
import unittest
from concurrent.futures import Future
from contextlib import closing
from unittest.mock import patch

from ai_team_team import ATTManager, Agent, StatePersistenceError
from ai_team_team.database.persistence import PersistenceCoordinator
from ai_team_team.database.persistence.records import DomainRecord, merge_records, thaw
from ai_team_team.database.persistence.receipts import settle_commit

from ._support import execution, invocation_graph, make_manager, model_request, record


class RecordTests(unittest.IsolatedAsyncioTestCase):
    async def test_durable_is_default_and_volatile_is_explicit(self):
        with self.assertRaisesRegex(ValueError, "explicit db_path"):
            ATTManager(Agent("Root", "Architect"))
        manager, _, client = make_manager(self, volatile=True)
        receipt = await manager._records.commit(invocation_graph(manager.root_ai.agent_id))
        self.assertEqual(receipt.durability, "volatile")
        self.assertEqual(client.requests, [])

    async def test_roundtrip_dependencies_are_insert_only_and_receipt_is_queryable(self):
        manager, path, client = make_manager(self)
        owner = manager.root_ai.agent_id
        await manager._records.commit(invocation_graph(owner), operation_id="foundation")
        with closing(sqlite3.connect(path)) as connection:
            before = connection.execute("SELECT * FROM agents").fetchall()
        receipt = await manager._records.commit((model_request(owner),), operation_id="request")
        self.assertIn("notification_frames", str(receipt.dependencies))
        self.assertEqual(await manager._persistence.receipt(path, "request"), receipt)
        with closing(sqlite3.connect(path)) as connection:
            self.assertEqual(before, connection.execute("SELECT * FROM agents").fetchall())
        state = await manager._persistence.read(path)
        self.assertEqual(len(state["records"]), 4)
        await manager.load_state(path)
        self.assertIn(("model_requests", ("model-request",)), manager._records.index)
        self.assertEqual(client.requests, [])

    async def test_version_merge_and_immutable_fact_conflict(self):
        manager, _, _ = make_manager(self)
        owner = manager.root_ai.agent_id
        newer, older = execution(owner, status="running", version=2), execution(owner)
        self.assertEqual(merge_records((newer,), (older,)), (newer,))
        fact = record("execution_attempts", attempt_id="attempt", execution_id="execution", attempt_index=1,
                      retry_contract={}, dispatched=0)
        changed = thaw(fact.values)
        changed["retry_contract"] = {"different": True}
        with self.assertRaises(StatePersistenceError):
            merge_records((fact,), (DomainRecord.capture("execution_attempts", changed),))
        values = {"nested": {"key": [1, 2]}}
        frozen = record("execution_payloads", payload_id="payload", agent_id=owner,
                        execution_id="execution", content_kind="input", content=values, digest="digest")
        values["nested"]["key"].append(3)
        self.assertEqual(thaw(frozen.values)["content"]["nested"]["key"], [1, 2])

    async def test_repeated_cancellation_does_not_release_domain_lock(self):
        completion = Future()
        entered = asyncio.Event()
        lock = asyncio.Lock()
        async def transaction():
            async with lock:
                entered.set()
                await settle_commit(asyncio.wrap_future(completion))
        task = asyncio.create_task(transaction())
        await entered.wait()
        for _ in range(4):
            task.cancel()
            await asyncio.sleep(0)
            self.assertTrue(lock.locked())
            self.assertFalse(completion.cancelled())
        completion.set_result("committed")
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(lock.locked())

    async def test_notification_observer_only_runs_after_exact_receipt(self):
        manager, _, _ = make_manager(self)
        owner = manager.root_ai.agent_id
        await manager._records.commit(invocation_graph(owner))
        await manager._records.commit((execution(owner),))
        notice = record("agent_notifications", notification_id="notice", agent_id=owner, source_kind="execution",
                        execution_id="execution", classification="ordinary", deduplication_key="execution", arrival_generation=1, created_at=1.0)
        entered, release = threading.Event(), threading.Event()
        events = []
        manager.on_system_event = lambda *args: events.append(args)
        original = manager._persistence._write
        def slow(path, snapshot):
            entered.set()
            release.wait(5)
            return original(path, snapshot)
        with patch.object(manager._persistence, "_write", slow):
            task = asyncio.create_task(manager._records.commit((notice,), notifications=("notice",)))
            await asyncio.to_thread(entered.wait, 5)
            self.assertEqual(events, [])
            release.set()
            receipt = await task
        await manager.flush_callbacks()
        self.assertEqual(events[0][1]["operation_id"], receipt.operation_id)

    async def test_pending_queue_merges_records_without_more_completion_futures(self):
        manager, _, _ = make_manager(self)
        owner = manager.root_ai.agent_id
        older, newer = execution(owner), execution(owner, status="running", version=2)
        merged = PersistenceCoordinator._merge_snapshots({"records": (newer,)}, {"records": (older,)})
        self.assertEqual(merged["records"], (newer,))

    async def test_first_private_file_delta_captures_owner_without_full_save(self):
        manager, path, _ = make_manager(self)
        manager.libraries[manager.root_ai.private_doc_library_id].write_file("first.txt", "fixture")
        await manager.flush_state()
        with closing(sqlite3.connect(path)) as connection:
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertEqual(connection.execute("SELECT content FROM doc_lib_files WHERE path='first.txt'").fetchone(), ("fixture",))

    async def test_copy_on_write_worker_updates_do_not_lose_independent_evidence(self):
        manager, path, _ = make_manager(self)
        owner = manager.root_ai.agent_id
        await manager._records.commit((*invocation_graph(owner), execution(owner)))
        observations = tuple(record("execution_observations", observation_id=f"observation-{index}",
                                    execution_id="execution", health="unknown", evidence_kind="executor_sample",
                                    evidence={"sample": index}, observed_at=float(index + 1), uncertain=1)
                             for index in range(64))
        await asyncio.gather(*(asyncio.to_thread(manager._records._merge, (observation,)) for observation in observations))
        self.assertEqual(sum(row.table_name == "execution_observations" for row in manager._records.snapshot()), 64)
        await manager.save_state()
        with closing(sqlite3.connect(path)) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM execution_observations").fetchone(), (64,))
