"""Physical constraints and historical relationships never rewrite a person."""

import sqlite3
import unittest
from contextlib import closing

from ai_team_team import Agent, StateRestoreError
from test.test_att.test_autonomous_activity_phase0._fixtures import AgentIdentitySnapshot

from ._support import invocation_graph, make_manager


class AuthorityAndHistoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_sql_enforces_one_live_admission_and_strict_scope(self):
        manager, path, _ = make_manager(self)
        owner = manager.root_ai.agent_id
        await manager._records.commit(invocation_graph(owner))
        with closing(sqlite3.connect(path)) as database:
            for sql in (
                "INSERT INTO activity_admissions SELECT 'duplicate', agent_id, runtime_generation, scope_kind, scope_team_id, disposition, accepted_at, state_version FROM activity_admissions",
                "UPDATE activity_admissions SET scope_kind='agent_team', scope_team_id=NULL",
                "UPDATE activity_invocations SET interrupted=2",
                "UPDATE activity_admissions SET state_version=0",
            ):
                with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                    database.execute(sql)
                database.rollback()
            self.assertEqual(database.execute("PRAGMA foreign_key_check").fetchall(), [])

    async def test_join_leave_rejoin_records_preserve_owned_identity(self):
        manager, path, _ = make_manager(self)
        team = manager.bootstrap_agent_team(manager.root_ai, member_configs={
            f"Member-{index}": {"model": "fixture"} for index in range(manager.config.min_subagent_team_size)
        })
        await manager.save_state()
        person = team.members[0]
        before = AgentIdentitySnapshot.capture(person, manager)
        with manager._resources.mutation():
            team.members.remove(person)
        manager._auto_save(teams={team.team_id})
        await manager.flush_state()
        with manager._resources.mutation():
            team.members.append(person)
        manager._auto_save(teams={team.team_id})
        await manager.flush_state()
        self.assertEqual(before, AgentIdentitySnapshot.capture(person, manager))
        with closing(sqlite3.connect(path)) as database:
            intervals = database.execute("SELECT interval_id, leave_event_id FROM membership_intervals WHERE team_id=? AND agent_id=?", (team.team_id, person.agent_id)).fetchall()
            self.assertEqual(len(intervals), 2)
            opened = [identifier for identifier, leave in intervals if leave is None]
            self.assertEqual(len(opened), 1)
            self.assertEqual(database.execute("SELECT interval_id FROM team_members WHERE team_id=? AND agent_id=?", (team.team_id, person.agent_id)).fetchone(), (opened[0],))
            database.execute("PRAGMA foreign_keys=OFF")
            database.execute("UPDATE team_members SET interval_id=? WHERE team_id=? AND agent_id=?",
                             (next(identifier for identifier, leave in intervals if leave is not None), team.team_id, person.agent_id))
            database.commit()
        with self.assertRaisesRegex(StateRestoreError, "current membership interval mismatch"):
            await manager.load_state(path)
        self.assertIs(manager._agents_by_id[person.agent_id], person)
        self.assertEqual(before, AgentIdentitySnapshot.capture(person, manager))

    async def test_corrupt_frame_shape_is_rejected_without_publication(self):
        manager, path, _ = make_manager(self)
        root = manager.root_ai
        await manager._records.commit(invocation_graph(root.agent_id))
        with closing(sqlite3.connect(path)) as database:
            database.execute("UPDATE notification_frames SET summary_references='{}'")
            database.commit()
        with self.assertRaisesRegex(StateRestoreError, "reference list"):
            await manager.load_state(path)
        self.assertIs(manager.root_ai, root)
        self.assertFalse(manager._resources.blocked)

    async def test_personal_message_cannot_reference_another_person_invocation(self):
        manager, path, client = make_manager(self)
        root = manager.root_ai
        other = manager.register_agent(Agent("Other", "Researcher", client))
        other.messages.append({"role": "user", "content": "Stored personal context"})
        await manager.save_state()
        await manager._records.commit(invocation_graph(root.agent_id))
        with closing(sqlite3.connect(path)) as database:
            database.execute("UPDATE agent_messages SET invocation_id='invocation' WHERE agent_id=?", (other.agent_id,))
            database.commit()
        with self.assertRaisesRegex(StateRestoreError, "source owner mismatch"):
            await manager.load_state(path)
        self.assertIs(manager.root_ai, root)
        self.assertIs(manager._agents_by_id[other.agent_id], other)
        self.assertFalse(manager._resources.blocked)

    async def test_malformed_checkpoint_json_raises_restore_error_before_file_changes(self):
        manager, path, _ = make_manager(self)
        root = manager.root_ai
        library = manager.libraries[root.private_doc_library_id]
        library.write_file("notes.txt", "unchanged")
        root.messages.append({"role": "user", "content": "Context"})
        await manager.save_state()
        with closing(sqlite3.connect(path)) as database:
            database.execute("UPDATE agent_messages SET source_metadata='not-json'")
            database.commit()
        with self.assertRaises(StateRestoreError):
            await manager.load_state(path)
        self.assertIs(manager.root_ai, root)
        self.assertEqual(library.read_text("notes.txt"), "unchanged")
        self.assertFalse(manager._resources.blocked)
