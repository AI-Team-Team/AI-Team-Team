"""Every accepted chat command retains type-specific historical authority."""

import json
import sqlite3
from contextlib import closing
from unittest.mock import patch

from ai_team_team import Agent, StateRestoreError
from ai_team_team.database.persistence.records import DomainRecord, thaw
from ai_team_team.database.persistence.store.detached_validation import validate_detached_records
from test.test_att.test_autonomous_activity_phase1._support import make_manager, record
from ._support import ChatTestCase


class OperationReceiptTests(ChatTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.manager.register_token_counter("fixture", len)

    async def operation_history(self):
        first = await self.manager.send_direct_message(self.other.agent_id, "V1", actor=self.root, operation_key="send")
        await self.manager.edit_chat_message(first.message_id, "V2", actor=self.root, operation_key="edit")
        await self.manager.withdraw_chat_message(first.message_id, actor=self.root, operation_key="withdraw")
        second = await self.manager.send_direct_message(self.root.agent_id, "Reverse source", actor=self.other, operation_key="reverse")
        await self.manager.control_chat_message("mark_message_read", second.message_id, actor=self.root, operation_key="read")
        await self.manager.control_chat_message("mark_message_unread", second.message_id, actor=self.root, operation_key="unread")
        await self.manager.control_chat_message("delete_message", second.message_id, actor=self.root, operation_key="delete")
        await self.manager.control_chat_message("restore_message", second.message_id, actor=self.root, operation_key="restore")
        await self.manager.set_chat_details(actor=self.root, direct_details=False, operation_key="details")
        request = await self.manager.request_friendship(self.other.agent_id, actor=self.root, operation_key="request")
        await self.manager.respond_friendship(request.request_id, "accept", actor=self.other, operation_key="accept")
        await self.manager.respond_friendship(request.request_id, "reject", actor=self.other, operation_key="already-resolved")
        await self.manager.request_friendship(self.other.agent_id, actor=self.root, operation_key="already-friends")
        await self.manager.control_direct_relationship(self.other.agent_id, "remove_friendship", actor=self.root, operation_key="remove")
        await self.manager.respond_friendship(request.request_id, "accept", actor=self.other, operation_key="stale")
        for decision, actor in (("ignore", self.other), ("cancel", self.root), ("reject", self.other)):
            renewed = await self.manager.request_friendship(self.other.agent_id, actor=self.root)
            await self.manager.respond_friendship(renewed.request_id, decision, actor=actor)
        await self.manager.control_direct_relationship(self.root.agent_id, "lift_direct_refusal", actor=self.other)
        await self.manager.control_direct_relationship(self.other.agent_id, "block_agent", actor=self.root)
        await self.manager.control_direct_relationship(self.other.agent_id, "unblock_agent", actor=self.root)
        await self.manager.set_chat_details(actor=self.root, direct_details=True, operation_key="later-details")
        await self.manager.save_state()
        return first, second, request

    async def test_corrupt_command_receipts_reject_restore_without_changing_runtime_or_files(self):
        first, second, request = await self.operation_history()
        outsider = self.manager.register_agent(Agent("Outsider", "Observer", self.client))
        other_source = await self.manager.send_direct_message(outsider.agent_id, "Another original", actor=self.root)
        await self.manager.edit_chat_message(other_source.message_id, "Another edited source", actor=self.root)
        private = self.manager.libraries[self.root.private_doc_library_id]
        private.write_file("own.txt", "Retained private artifact")
        await self.manager.save_state()
        operations = {row.values["operation_key"]: thaw(row.values) for row in self.records("chat_operations")}
        cases = (
            ("edit", {"message_id": "missing"}),
            ("edit", {"message_id": second.message_id}),
            ("edit", {"message_id": other_source.message_id}),
            ("edit", {"version": 999}),
            ("edit", {"version": 1}),
            ("edit", {"status": "WITHDRAWN"}),
            ("edit", {"version": None}),
            ("withdraw", {"message_id": second.message_id}),
            ("withdraw", {"version": 1}),
            ("read", {"message_id": "missing"}),
            ("read", {"status": "DELETE_MESSAGE"}),
            ("delete", {"version": 1}),
            ("details", {"status": "UNCHANGED"}),
            ("details", {"message_id": first.message_id}),
            ("request", {"request_id": "missing"}),
            ("request", {"generation": 999}),
            ("request", {"generation": None}),
            ("request", {"relationship_id": "missing"}),
            ("accept", {"status": "REJECTED"}),
            ("stale", {"generation": 1}),
            ("send", {"notification_ids": ["missing"]}),
        )
        runtime = self.manager.root_ai, self.manager._records.snapshot()
        for key, patch_result in cases:
            with self.subTest(operation=key, fields=tuple(patch_result)):
                original = operations[key]
                candidate = {**original["result"], **patch_result}
                with closing(sqlite3.connect(self.path)) as database:
                    database.execute("UPDATE chat_operations SET result=? WHERE operation_key=?",
                                     (json.dumps(candidate), key))
                    database.commit()
                try:
                    with self.assertRaises(StateRestoreError):
                        await self.manager.load_state(self.path)
                    self.assertIs(self.manager.root_ai, runtime[0])
                    self.assertEqual(self.manager._records.snapshot(), runtime[1])
                    self.assertEqual(private.read_text("own.txt"), "Retained private artifact")
                finally:
                    with closing(sqlite3.connect(self.path)) as database:
                        database.execute("UPDATE chat_operations SET result=? WHERE operation_key=?",
                                         (json.dumps(original["result"]), key))
                        database.commit()
        # Independently test valid-shaped commands attributed to wrong principals.
        with closing(sqlite3.connect(self.path)) as database:
            database.execute("UPDATE chat_operations SET agent_id=? WHERE operation_key='read'", (outsider.agent_id,))
            database.commit()
        with self.assertRaises(StateRestoreError):
            await self.manager.load_state(self.path)
        with closing(sqlite3.connect(self.path)) as database:
            database.execute("UPDATE chat_operations SET agent_id=? WHERE operation_key='read'", (self.root.agent_id,))
            database.execute("UPDATE chat_operations SET agent_id=? WHERE operation_key='accept'", (self.root.agent_id,))
            database.commit()
        with self.assertRaises(StateRestoreError):
            await self.manager.load_state(self.path)
        with closing(sqlite3.connect(self.path)) as database:
            database.execute("UPDATE chat_operations SET agent_id=? WHERE operation_key='accept'", (self.other.agent_id,))
            database.execute("UPDATE chat_operations SET command='send_team' WHERE operation_key='send'")
            database.commit()
        with self.assertRaises(StateRestoreError):
            await self.manager.load_state(self.path)

    async def test_detached_validation_rejects_nonpublication_receipt_reference_corruption(self):
        await self.operation_history()
        dirty = self.manager._new_dirty_state(full=True)
        state = self.manager._capture_state_snapshot(dirty)
        # Full detached validation uses the very same command-specific checks.
        rows = list(state["records"])
        for position, value in enumerate(rows):
            if value.table_name == "chat_operations" and value.values["command"] == "edit":
                fields = thaw(value.values)
                fields["result"]["message_id"] = "missing"
                rows[position] = DomainRecord.capture(value.table_name, fields)
                break
        with self.assertRaises(StateRestoreError):
            validate_detached_records({**state, "records": tuple(rows)})

    async def test_sql_and_volatile_commits_reject_invalid_receipts_before_publication(self):
        for volatile in (False, True):
            with self.subTest(volatile=volatile):
                manager, path, client = make_manager(self, volatile=volatile)
                manager._activity.schedule_notice = lambda _identifier: None
                peer = manager.register_agent(Agent("Peer", "Researcher", client))
                sent = await manager.send_direct_message(peer.agent_id, "Original", actor=manager.root_ai)
                before = manager._records.snapshot()
                invalid = record("chat_operations", agent_id=manager.root_ai.agent_id,
                    operation_key="invalid-edit", command="edit", request_digest="0" * 64,
                    result={"status": "EDITED", "message_id": sent.message_id, "version": 999}, created_at=1.0)
                with self.assertRaises(StateRestoreError):
                    await manager._records.commit((invalid,))
                self.assertEqual(manager._records.snapshot(), before)
                if not volatile:
                    with closing(sqlite3.connect(path)) as database:
                        self.assertEqual(database.execute("SELECT count(*) FROM chat_operations WHERE operation_key='invalid-edit'").fetchone(), (0,))
                    # The intentionally rejected writer error remains observable.
                    with self.assertRaises(StateRestoreError):
                        await manager.flush_state()
                    with self.assertRaises(StateRestoreError):
                        await manager.close()

    async def test_historical_receipts_survive_later_relationship_and_view_changes(self):
        first, second, request = await self.operation_history()
        await self.manager.load_state(self.path)
        root, other = self.manager.root_ai, self.manager._agents_by_id[self.other.agent_id]
        retries = (
            self.manager.edit_chat_message(first.message_id, "V2", actor=root, operation_key="edit"),
            self.manager.withdraw_chat_message(first.message_id, actor=root, operation_key="withdraw"),
            self.manager.control_chat_message("delete_message", second.message_id, actor=root, operation_key="delete"),
            self.manager.set_chat_details(actor=root, direct_details=False, operation_key="details"),
            self.manager.respond_friendship(request.request_id, "accept", actor=other, operation_key="accept"),
        )
        with patch.object(self.manager._records, "commit", side_effect=AssertionError("An accepted retry must not commit again")):
            for operation in retries:
                await operation
        self.assertEqual(self.manager.list_direct_messages(root.agent_id, actor=other).items[0].version, 2)
        self.assertEqual(self.manager.inspect_direct_relationship(other.agent_id, actor=root).generation, 3)
