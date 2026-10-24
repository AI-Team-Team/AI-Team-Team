"""Creation acceptance and rollback preserve independently accepted work."""

import asyncio
import sqlite3
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from test.test_att.test_agent_activity._support import ActivityTestCase
from ._lock_support import ObservedLock


class CreationTransactionTests(ActivityTestCase):
    def parent_and_proposal(self, *, agent_creator=False, task=None):
        parent = self.manager.bootstrap_agent_team(self.root, existing_members=[self.root],
            member_configs={"Parent1": {}, "Parent2": {}, "Parent3": {}})
        request = self.manager.propose_team_formation(creator=self.root if agent_creator else parent,
            parent=parent, initiating_agent=self.root, initiator_joins=True,
            member_configs={"Child1": {}, "Child2": {}}, task=task)
        return parent, request

    async def assert_membership_revalidated(self, *, durable, agent_creator=False):
        if durable:
            self.manager = self.make_manager(self.root, durable=True)
        with patch.object(self.manager._activity, "schedule_notice"):
            parent, request = self.parent_and_proposal(agent_creator=agent_creator)
            before = set(self.manager._agents_by_id), set(self.manager.libraries)
            activity = ObservedLock(self.manager._activity.lock)
            with patch.object(self.manager._activity, "lock", activity):
                async with activity:
                    removal = asyncio.create_task(self.manager._messaging.replace_members(parent,
                        [member for member in parent.members if member is not self.root], actor=self.root))
                    await activity.wait_for_attempt(removal)
                    creation = asyncio.create_task(self.manager.create_team_from_formation(
                        request.request_id, actor=self.root, proposal_revision=1))
                    await activity.wait_for_attempt(creation)
                await removal
                with self.assertRaisesRegex(ValueError, "initiator left"):
                    await creation
        self.assertNotIn(self.root, parent.members)
        self.assertEqual(len(self.manager.teams), 1)
        self.assertEqual((set(self.manager._agents_by_id), set(self.manager.libraries)), before)
        self.assertIsNone(self.manager.get_team_formation(request.request_id).created_team_id)
        self.assertNotIn(f"FORMATION-CREATE-{request.request_id}", self.manager._records.receipts)
        if durable:
            await self.manager.save_state()
            self.manager._validate_state_snapshot(await self.manager._persistence.read(self.manager.db_path))

    async def test_volatile_creation_rechecks_creator_team_membership(self):
        await self.assert_membership_revalidated(durable=False)

    async def test_durable_creation_rechecks_creator_team_membership(self):
        await self.assert_membership_revalidated(durable=True)

    async def test_agent_creator_rechecks_membership_in_the_requested_parent(self):
        await self.assert_membership_revalidated(durable=False, agent_creator=True)

    async def assert_unrelated_creation_survives(self, *, durable):
        if durable:
            self.manager = self.make_manager(self.root, durable=True)
        with patch.object(self.manager._activity, "schedule_notice"):
            _parent, request = self.parent_and_proposal()
            other_parent = self.manager.create_agent_team(self.root)
            activity = ObservedLock(self.manager._activity.lock)
            with patch.object(self.manager._activity, "lock", activity):
                async with activity:
                    creation = asyncio.create_task(self.manager.create_team_from_formation(
                        request.request_id, actor=self.root, proposal_revision=1))
                    await activity.wait_for_attempt(creation)
                    unrelated = self.manager.create_agent_team(self.root, parent=other_parent)
                    unrelated.doc_library.write_file("keep.txt", "Accepted independent artifact.")
                    if durable:
                        await self.manager.flush_state()
                    self.manager.config.max_delegation_depth = 1
                with self.assertRaisesRegex(ValueError, "depth"):
                    await creation
        self.assertIs(self.manager.teams[unrelated.team_id], unrelated)
        self.assertIn(unrelated, other_parent.child_teams)
        self.assertEqual(self.manager._team_parent_map[unrelated.team_id], other_parent.team_id)
        self.assertEqual(Path(unrelated.doc_library.root_dir, "keep.txt").read_text(), "Accepted independent artifact.")
        for person in unrelated.members:
            self.assertIs(self.manager._agents_by_id[person.agent_id], person)
            self.assertIs(person._manager, self.manager)
            self.assertTrue(Path(self.manager.libraries[person.private_doc_library_id].root_dir).is_dir())
        if durable:
            with closing(sqlite3.connect(self.manager.db_path)) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM teams WHERE team_id = ?",
                    (unrelated.team_id,)).fetchone()[0], 1)
            await self.manager.save_state()
            state = await self.manager._persistence.read(self.manager.db_path)
            self.manager._validate_state_snapshot(state)
            self.assertIn(unrelated.team_id, {row["team_id"] for row in state["teams"]})

    async def test_volatile_rollback_preserves_another_created_team_and_its_files(self):
        await self.assert_unrelated_creation_survives(durable=False)

    async def test_durable_rollback_preserves_another_committed_team_and_its_files(self):
        await self.assert_unrelated_creation_survives(durable=True)

    async def assert_unrelated_mail_survives(self, *, durable):
        if durable:
            self.manager = self.make_manager(self.root, durable=True)
        with patch.object(self.manager._activity, "schedule_notice"):
            _parent, request = self.parent_and_proposal(task="Only admitted creation may publish this initial task.")
            activity = ObservedLock(self.manager._activity.lock)
            with patch.object(self.manager._activity, "lock", activity):
                async with activity:
                    delivery = asyncio.create_task(self.manager._activity.deliver_mail(self.root.agent_id,
                        message_type="personal_instruction", payload={"text": "Preserve independently accepted mail."}, schedule=False))
                    await activity.wait_for_attempt(delivery)
                    creation = asyncio.create_task(self.manager.create_team_from_formation(
                        request.request_id, actor=self.root, proposal_revision=1))
                    await activity.wait_for_attempt(creation)
                    self.manager.config.max_delegation_depth = 1
                receipt = await delivery
                with self.assertRaisesRegex(ValueError, "depth"):
                    await creation
        mail_ids = {item["message_id"] for item in self.root.agent_inbox}
        self.assertIn(receipt.message_id, mail_ids)
        self.assertIn(("agent_notifications", (f"NOTICE-{receipt.message_id}",)), self.manager._records.index)
        self.assertFalse(any(item["message_type"] in {"team_initial_instruction", "team_formation_created"}
            for item in self.root.agent_inbox))
        for notice in self.records("agent_notifications"):
            owner = self.manager._agents_by_id[notice.values["agent_id"]]
            if notice.values["mail_id"]:
                self.assertIn(notice.values["mail_id"], {item["message_id"] for item in owner.agent_inbox})
        self.assertFalse(self.manager._inbox._staged_mail_ids)
        if durable:
            await self.manager.save_state()
            self.manager._validate_state_snapshot(await self.manager._persistence.read(self.manager.db_path))

    async def test_volatile_rollback_preserves_accepted_mail_and_has_no_ghost_notice(self):
        await self.assert_unrelated_mail_survives(durable=False)

    async def test_durable_rollback_preserves_accepted_mail_and_has_no_ghost_notice(self):
        await self.assert_unrelated_mail_survives(durable=True)

    async def test_cancelled_revoked_tool_can_still_withdraw_its_unaccepted_creation(self):
        with patch.object(self.manager._activity, "schedule_notice"):
            _parent, request = self.parent_and_proposal()
            before = set(self.manager.teams), set(self.manager._agents_by_id), set(self.manager.libraries)
            activity = ObservedLock(self.manager._activity.lock)
            with self.manager._resources.execution() as authority, patch.object(self.manager._activity, "lock", activity):
                async with activity:
                    creation = asyncio.create_task(self.manager.create_team_from_formation(
                        request.request_id, actor=self.root, proposal_revision=1))
                    await activity.wait_for_attempt(creation)
                    self.manager._resources.revoke(authority)
                    creation.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await creation
        self.assertEqual((set(self.manager.teams), set(self.manager._agents_by_id), set(self.manager.libraries)), before)
        self.assertFalse(self.manager._inbox._staged_mail_ids)
        self.assertFalse(any(row["message_type"] == "team_formation_created" for row in self.root.agent_inbox))
