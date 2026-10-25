"""Invalid suppression, retained ownership, and recovery evidence fail closed."""

import sqlite3
from contextlib import closing

from ai_team_team import Agent, StateRestoreError
from ai_team_team.core.activity.contracts import SuppressionPreference, WakeDuration
from test.test_att.test_agent_activity._support import ActivityTestCase


class LifecycleCorruptionTests(ActivityTestCase):
    async def test_timed_suppression_corruption_matrix_preserves_the_live_manager(self):
        await self.manager.close()
        self.manager = self.make_manager(self.root, durable=True)
        preference = await self.manager.set_notification_suppression(
            SuppressionPreference(scope="all", countdown=WakeDuration(minutes=5)), actor=self.root)
        await self.manager.save_state()
        path = self.manager.db_path
        await self.manager.close()
        self.manager = self.make_manager(Agent("Unchanged", "Architect", self.client))
        original_root = self.manager.root_ai
        for column, value in (("remaining_seconds", -1), ("duration_seconds", None), ("minimum_seconds", None),
                              ("maximum_seconds", None), ("remaining_seconds", 301), ("status", "unknown"),
                              ("scope", "agent"), ("source_agent_id", "missing")):
            with self.subTest(column=column, value=value):
                with closing(sqlite3.connect(path)) as database:
                    database.execute("PRAGMA ignore_check_constraints=ON")
                    original = database.execute(f'SELECT "{column}" FROM notification_suppression WHERE preference_id=?', (preference["preference_id"],)).fetchone()[0]
                    database.execute(f'UPDATE notification_suppression SET "{column}"=? WHERE preference_id=?', (value, preference["preference_id"]))
                    database.commit()
                try:
                    with self.assertRaises(StateRestoreError):
                        await self.manager.load_state(path)
                    self.assertIs(self.manager.root_ai, original_root)
                    self.assertFalse(self.manager._activity.sessions)
                finally:
                    with closing(sqlite3.connect(path)) as database:
                        database.execute("PRAGMA ignore_check_constraints=ON")
                        database.execute(f'UPDATE notification_suppression SET "{column}"=? WHERE preference_id=?', (original, preference["preference_id"]))
                        database.commit()

    async def test_dead_member_or_active_private_library_cannot_restore_as_valid_state(self):
        await self.manager.close()
        self.manager = self.make_manager(self.root, durable=True)
        team = self.manager.create_agent_team(self.root, parent=self.root)
        member = team.members[0]
        await self.manager.save_state()
        path = self.manager.db_path
        await self.manager.close()
        with closing(sqlite3.connect(path)) as database:
            database.execute("UPDATE agents SET lifecycle_state='dead' WHERE agent_id=?", (member.agent_id,))
            database.commit()
        target = self.make_manager(Agent("Target", "Architect", self.client))
        original = target.root_ai
        with self.assertRaises(StateRestoreError):
            await target.load_state(path)
        self.assertIs(target.root_ai, original)
