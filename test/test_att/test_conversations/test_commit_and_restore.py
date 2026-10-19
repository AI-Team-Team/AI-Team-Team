"""Real SQLite failure, concurrent ordering, cancellation, and corrupt references."""

import asyncio
import json
import sqlite3
import threading
from contextlib import closing
from unittest.mock import patch

from ai_team_team import Agent, StateRestoreError
from test.test_att.test_autonomous_activity_phase1._support import make_manager
from ._support import ChatTestCase


class CommitAndRestoreTests(ChatTestCase):
    async def test_cancelled_delivery_settles_and_replays_the_exact_durable_receipt(self):
        await self.manager.save_state()
        entered, release = threading.Event(), threading.Event()
        store = self.manager._persistence._store(self.path)
        original = store.write

        def slow(snapshot):
            entered.set()
            if not release.wait(10):
                raise TimeoutError("The test did not release its writer.")
            return original(snapshot)

        with patch.object(store, "write", slow):
            sending = asyncio.create_task(self.manager.send_direct_message(self.other.agent_id, "Committed once", actor=self.root, operation_key="lost-response"))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 5))
                self.assertFalse(self.records("chat_messages"))
                sending.cancel()
                await asyncio.sleep(0)
                sending.cancel()
            finally:
                release.set()
            with self.assertRaises(asyncio.CancelledError):
                await sending
        replay = await self.manager.send_direct_message(self.other.agent_id, "Committed once", actor=self.root, operation_key="lost-response")
        self.assertEqual(len(self.records("chat_messages")), 1)
        await self.manager.save_state()
        await self.manager.load_state(self.path)
        other = self.manager._agents_by_id[self.other.agent_id]
        again = await self.manager.send_direct_message(other.agent_id, "Committed once", actor=self.manager.root_ai, operation_key="lost-response")
        self.assertEqual(replay, again)
        self.assertEqual(self.manager.inspect_direct_relationship(other.agent_id, actor=self.manager.root_ai).remaining_messages, 2)

    async def test_member_removal_and_message_publication_share_the_same_lock(self):
        team = self.team()
        before = await self.manager.send_team_message(team.team_id, "Before", actor=self.root)
        async with team.state_lock:
            removal = asyncio.create_task(self.manager._messaging.replace_members(team,
                [member for member in team.members if member is not self.other], actor=self.root))
            await asyncio.sleep(0)
            sending = asyncio.create_task(self.manager.send_team_message(team.team_id, "After", actor=self.root))
            await asyncio.sleep(0)
        await removal
        after = await sending
        self.assertEqual([item.message_id for item in self.manager.list_team_messages(team.team_id, actor=self.other).items], [before.message_id])
        self.assertNotEqual(before.message_id, after.message_id)

    async def test_later_progress_snapshot_cannot_reopen_a_committed_membership(self):
        team = self.team()
        await self.manager.save_state()
        dirty = self.manager._new_dirty_state()
        dirty["teams"].add(team.team_id)
        old = self.manager._capture_state_snapshot(dirty)
        await self.manager._messaging.replace_members(team, [member for member in team.members if member is not self.other], actor=self.root)
        # Simulate a later queued metadata snapshot captured while the receipt
        # was settling, including its stale open interval prerequisites.
        from ai_team_team.database.persistence.records import thaw
        snapshot = {key: value if key == "records" else thaw(value) for key, value in old.items()}
        snapshot["state_version"] = self.manager._state_version + 10
        snapshot["teams"] = [{**row, "state_version": snapshot["state_version"], "team_progress": "Later metadata"} for row in snapshot["teams"]]
        await asyncio.wrap_future(self.manager._persistence.submit(self.path, snapshot))
        with closing(sqlite3.connect(self.path)) as database:
            self.assertEqual(database.execute("SELECT count(*) FROM team_members WHERE team_id=? AND agent_id=?", (team.team_id, self.other.agent_id)).fetchone(), (0,))
            self.assertEqual(database.execute("PRAGMA foreign_key_check").fetchall(), [])

    async def test_corrupt_chat_reference_matrix_does_not_publish_runtime_or_files(self):
        mutations = (
            "DELETE FROM chat_personal_views WHERE view_id=(SELECT view_id FROM chat_personal_views LIMIT 1)",
            "UPDATE chat_personal_views SET revision_id='missing'",
            "UPDATE chat_message_projections SET revision_id='missing'",
            "UPDATE chat_messages SET author_agent_id='missing'",
            "UPDATE chat_messages SET reply_message_id='missing'",
            "UPDATE chat_operations SET result='{}'",
            "UPDATE chat_operations SET request_digest='invalid'",
            "UPDATE chat_reminder_previews SET visibility='{}'",
            "UPDATE membership_intervals SET join_event_id='missing' WHERE interval_id=(SELECT interval_id FROM membership_intervals LIMIT 1)",
            "UPDATE friendship_requests SET generation=99",
            "UPDATE direct_relationships SET friendship=1, blocked_a=1",
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                manager, path, client = make_manager(self)
                manager._activity.schedule_notice = lambda _identifier: None
                root = manager.root_ai
                peer = manager.register_agent(Agent("Peer", "Researcher", client))
                team = manager.bootstrap_agent_team(root, existing_members=[root, peer],
                    member_configs={"Member": {"model": "fixture"}})
                await manager.send_team_message(team.team_id, "Safe source", actor=root)
                request = await manager.request_friendship(peer.agent_id, actor=root)
                await manager.respond_friendship(request.request_id, "accept", actor=peer)
                library = manager.libraries[root.private_doc_library_id]
                library.write_file("own.txt", "Unchanged artifact")
                await manager.save_state()
                records = manager._records.snapshot()
                with closing(sqlite3.connect(path)) as database:
                    database.execute("PRAGMA ignore_check_constraints=ON")
                    database.execute(mutation)
                    database.commit()
                with self.assertRaises(StateRestoreError):
                    await manager.load_state(path)
                self.assertIs(manager.root_ai, root)
                self.assertEqual(manager._records.snapshot(), records)
                self.assertEqual(library.read_text("own.txt"), "Unchanged artifact")

    async def test_schema_12_is_rejected_without_changing_any_bytes(self):
        await self.manager.save_state()
        with closing(sqlite3.connect(self.path)) as database:
            database.execute("UPDATE manager_config SET config_value='12' WHERE config_key='schema_version'")
            database.commit()
            before = database.execute("SELECT name, sql FROM sqlite_master ORDER BY name").fetchall()
        with self.assertRaises(StateRestoreError):
            await self.manager.load_state(self.path)
        with closing(sqlite3.connect(self.path)) as database:
            self.assertEqual(before, database.execute("SELECT name, sql FROM sqlite_master ORDER BY name").fetchall())

    async def test_chat_only_delta_preserves_unrelated_identity_and_team_rows(self):
        team = self.team()
        await self.manager.save_state()
        with closing(sqlite3.connect(self.path)) as database:
            before = {name: database.execute(f"SELECT * FROM {name} ORDER BY 1").fetchall() for name in ("agents", "teams", "libraries", "team_members")}
        await self.manager.send_team_message(team.team_id, "Delta only", actor=self.root)
        with closing(sqlite3.connect(self.path)) as database:
            after = {name: database.execute(f"SELECT * FROM {name} ORDER BY 1").fetchall() for name in before}
        self.assertEqual(before, after)
        self.assertNotIn("Delta only", json.dumps(self.manager.list_entities().model_dump(mode="json")))
