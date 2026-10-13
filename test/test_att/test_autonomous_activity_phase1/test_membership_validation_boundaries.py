"""Current relationships and ordered membership history agree in both directions."""

import asyncio
import sqlite3
import unittest
from contextlib import closing

from ai_team_team import Agent, StateRestoreError
from ai_team_team.database.persistence.records import DomainRecord, thaw
from ai_team_team.database.persistence.store.detached_validation import validate_detached_records
from test.test_att.test_autonomous_activity_phase0._fixtures import AgentIdentitySnapshot

from ._support import make_manager, record


def create_team(manager):
    return manager.create_agent_team(manager.root_ai, member_configs={
        f"Member-{index}": {"model": "fixture"} for index in range(manager.config.min_subagent_team_size + 1)
    })


class MembershipValidationTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_current_relation_is_rejected_without_publication(self):
        manager, path, client = make_manager(self)
        team = create_team(manager)
        person = team.members[0]
        identity = AgentIdentitySnapshot.capture(person, manager)
        library = manager.libraries[manager.root_ai.private_doc_library_id]
        library.write_file("original.txt", "unchanged")
        await manager.save_state()
        with closing(sqlite3.connect(path)) as database:
            database.execute("DELETE FROM team_members WHERE team_id=? AND agent_id=?", (team.team_id, person.agent_id))
            database.commit()
            self.assertEqual(database.execute("PRAGMA foreign_key_check").fetchall(), [])
        with self.assertRaisesRegex(StateRestoreError, "open intervals and current memberships"):
            await manager.load_state(path)
        self.assertIs(manager.teams[team.team_id], team)
        self.assertIn(person, team.members)
        self.assertEqual(AgentIdentitySnapshot.capture(person, manager), identity)
        self.assertEqual(library.read_text("original.txt"), "unchanged")
        self.assertFalse(manager._resources.blocked)
        self.assertEqual(client.requests, [])

    async def test_leave_event_requires_the_departing_agent(self):
        for actor in ("another_member", None):
            with self.subTest(actor=actor):
                manager, path, client = make_manager(self)
                team = create_team(manager)
                await manager.save_state()
                person, other = team.members[:2]
                identity = AgentIdentitySnapshot.capture(person, manager)
                with manager._resources.mutation():
                    team.members.remove(person)
                manager._auto_save(teams={team.team_id})
                await manager.flush_state()
                with closing(sqlite3.connect(path)) as database:
                    event_id = database.execute("SELECT leave_event_id FROM membership_intervals WHERE team_id=? AND agent_id=?", (team.team_id, person.agent_id)).fetchone()[0]
                    database.execute("UPDATE chat_events SET actor_agent_id=? WHERE event_id=?", (other.agent_id if actor else None, event_id))
                    database.commit()
                with self.assertRaisesRegex(StateRestoreError, "leave owner mismatch"):
                    await manager.load_state(path)
                self.assertIs(manager.teams[team.team_id], team)
                self.assertEqual(AgentIdentitySnapshot.capture(person, manager), identity)
                self.assertFalse(manager._resources.blocked)
                self.assertEqual(client.requests, [])

    async def test_volatile_history_requires_a_current_member(self):
        manager, _, client = make_manager(self, volatile=True)
        team = create_team(manager)
        outsider = manager.register_agent(Agent("Outsider", "Researcher", client))
        previous = next(row for row in manager._records.snapshot() if row.table_name == "chat_streams" and row.values["team_id"] == team.team_id)
        stream_id = previous.values["stream_id"]
        stream = DomainRecord.capture("chat_streams", {**thaw(previous.values), "next_position": previous.values["next_position"] + 1, "state_version": previous.version + 1})
        join = record("chat_events", event_id="join", stream_id=stream_id, sequence=previous.values["next_position"],
                      event_kind="join", actor_agent_id=outsider.agent_id, created_at=1.0)
        interval = record("membership_intervals", interval_id="interval", team_id=team.team_id,
                          agent_id=outsider.agent_id, stream_id=stream_id, join_event_id="join")
        before = manager._records.snapshot()
        with self.assertRaisesRegex(StateRestoreError, "open intervals and current memberships"):
            await manager._records.commit((stream, join, interval))
        self.assertEqual(manager._records.snapshot(), before)
        self.assertEqual(manager._records.receipts, {})
        member = team.members[0]
        identity = AgentIdentitySnapshot.capture(member, manager)
        interval = next(row for row in before if row.table_name == "membership_intervals" and row.values["team_id"] == team.team_id and row.values["agent_id"] == member.agent_id)
        join = next(row for row in before if row.table_name == "chat_events" and row.values["event_id"] == interval.values["join_event_id"])
        receipt = await manager._records.commit((previous, join, interval))
        self.assertEqual(receipt.durability, "volatile")
        self.assertEqual(AgentIdentitySnapshot.capture(member, manager), identity)
        self.assertEqual(client.requests, [])

    async def test_full_detached_checkpoint_requires_every_current_interval(self):
        manager, path, client = make_manager(self)
        create_team(manager)
        await manager.save_state()
        state = await manager._persistence.read(path, reconcile=False)
        state["records"] = ()
        with self.assertRaisesRegex(StateRestoreError, "current membership intervals"):
            await asyncio.to_thread(validate_detached_records, state)
        self.assertEqual(client.requests, [])

    async def test_dissolution_can_close_multiple_intervals_without_a_personal_actor(self):
        manager, path, client = make_manager(self)
        team = create_team(manager)
        await manager.save_state()
        stream = next(row for row in manager._records.snapshot() if row.table_name == "chat_streams" and row.values["team_id"] == team.team_id)
        intervals = [row for row in manager._records.snapshot() if row.table_name == "membership_intervals" and row.values["team_id"] == team.team_id]
        dissolve = record("chat_events", event_id="dissolve", stream_id=stream.values["stream_id"],
                          sequence=stream.values["next_position"], event_kind="dissolve", created_at=2.0)
        closed = []
        for previous in intervals:
            values = thaw(previous.values)
            values.update(leave_event_id="dissolve", state_version=previous.version + 1)
            closed.append(DomainRecord.capture("membership_intervals", values))
        values = thaw(stream.values)
        values.update(next_position=values["next_position"] + 1, state_version=stream.version + 1)
        # Exercise the relational foundation directly; the later institutional
        # adapter owns the complete team-dissolution runtime transition.
        store = manager._persistence._store(path)
        def commit():
            with store.session_factory() as session:
                from sqlalchemy import text
                from ai_team_team.database.persistence.store.records import validate_database, write_records
                session.execute(text("BEGIN IMMEDIATE"))
                session.execute(text("PRAGMA defer_foreign_keys=ON"))
                session.execute(text("DELETE FROM team_members WHERE team_id=:id"), {"id": team.team_id})
                write_records(session, (dissolve, *closed, DomainRecord.capture("chat_streams", values)))
                validate_database(session)
                session.commit()
        await asyncio.to_thread(commit)
        state = await manager._persistence.read(path, reconcile=False)
        self.assertTrue(all(row.values["leave_event_id"] == "dissolve" for row in state["records"] if row.table_name == "membership_intervals"))
        self.assertEqual(client.requests, [])
