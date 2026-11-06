"""Confirmed invocation endings cannot turn into recovery candidates again."""

import asyncio
import sqlite3
import unittest
from contextlib import closing

from ai_team_team import StatePersistenceError
from ai_team_team.database.persistence.records import DomainRecord, thaw

from ._support import invocation_graph, make_manager


class InvocationTerminalTests(unittest.IsolatedAsyncioTestCase):
    async def test_confirmed_end_rejects_reopening_and_rewritten_outcomes(self):
        for volatile in (False, True):
            with self.subTest(volatile=volatile):
                manager, _, client = make_manager(self, volatile=volatile)
                await manager._records.commit(invocation_graph(manager.root_ai.agent_id))
                values = thaw(manager._records.index[("activity_invocations", ("invocation",))].values)
                values.update(boundary_at=2.0, state_version=2)
                ended = DomainRecord.capture("activity_invocations", values)
                await manager._records.commit((ended,))
                for change in ({"boundary_at": None}, {"boundary_at": 3.0}, {"interrupted": 1}):
                    with self.subTest(change=change), self.assertRaisesRegex(StatePersistenceError, "invocation boundary"):
                        await manager._records.commit((DomainRecord.capture("activity_invocations", {**values, **change, "state_version": 3}),))
                    self.assertEqual(manager._records.index[ended.identity], ended)
                await manager._records.commit((DomainRecord.capture("activity_invocations", {**values, "state_version": 3}),))
                self.assertEqual(client.requests, [])

    async def test_sql_writer_independently_protects_the_confirmed_boundary(self):
        manager, path, _ = make_manager(self)
        await manager._records.commit(invocation_graph(manager.root_ai.agent_id))
        values = thaw(manager._records.index[("activity_invocations", ("invocation",))].values)
        values.update(boundary_at=2.0, state_version=2)
        await manager._records.commit((DomainRecord.capture("activity_invocations", values),))
        store = manager._persistence._store(path)
        reopened = DomainRecord.capture("activity_invocations", {**values, "boundary_at": None, "state_version": 3})
        with self.assertRaisesRegex(StatePersistenceError, "invocation boundary"):
            await asyncio.to_thread(store.write, {"full": False, "records": (reopened,), "_operations": ()})
        with closing(sqlite3.connect(path)) as database:
            self.assertEqual(database.execute("SELECT boundary_at, state_version FROM activity_invocations").fetchone(), (2.0, 2))
            self.assertEqual(database.execute("PRAGMA foreign_key_check").fetchall(), [])

    async def test_ended_invocation_stays_ended_after_restore(self):
        manager, path, client = make_manager(self)
        await manager._records.commit(invocation_graph(manager.root_ai.agent_id))
        values = thaw(manager._records.index[("activity_invocations", ("invocation",))].values)
        values.update(boundary_at=2.0, state_version=2)
        await manager._records.commit((DomainRecord.capture("activity_invocations", values),))
        await manager.load_state(path)
        self.assertEqual(manager._records.index[("activity_invocations", ("invocation",))].values["boundary_at"], 2.0)
        self.assertEqual(manager._recovery_plan.affected_agents, ())
        self.assertEqual(manager._recovery_plan.notification_ids, ())
        self.assertEqual(client.requests, [])
