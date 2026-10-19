"""The same authority and read semantics in volatile and durable operation."""

import unittest

from ai_team_team import Agent, ToolBusinessError
from test.test_att.test_autonomous_activity_phase1._support import make_manager


class DurabilityParityTests(unittest.IsolatedAsyncioTestCase):
    async def test_sources_views_changes_and_export_keep_the_same_person_in_both_modes(self):
        for volatile in (False, True):
            with self.subTest(volatile=volatile):
                manager, path, client = make_manager(self, volatile=volatile)
                manager._activity.schedule_notice = lambda _identifier: None
                manager.register_token_counter("fixture", len)
                person = manager.register_agent(Agent("Person", "Researcher", client))
                root = manager.root_ai
                team = manager.bootstrap_agent_team(root, existing_members=[root, person], member_configs={"Another": {"model": "fixture"}})
                private_id, personal_window = person.private_doc_library_id, person.messages
                sent = await manager.send_team_message(team.team_id, "Original", actor=root)
                self.assertEqual(sent.durability, "volatile" if volatile else "durable")
                await manager._messaging.replace_members(team, [member for member in team.members if member is not person], actor=root)
                await manager.edit_chat_message(sent.message_id, "Later", actor=root)
                self.assertEqual((await manager.read_chat_message(sent.message_id, actor=person)).content, "Original")
                direct = await manager.send_direct_message(person.agent_id, "Direct", actor=root)
                await manager.edit_chat_message(direct.message_id, "Direct V2", actor=root)
                request = await manager.request_friendship(person.agent_id, actor=root)
                await manager.respond_friendship(request.request_id, "accept", actor=person)
                await manager.control_direct_relationship(person.agent_id, "remove_friendship", actor=root)
                self.assertIs(person.messages, personal_window)
                self.assertEqual(person.private_doc_library_id, private_id)
                await manager.save_state(path)
                await manager.load_state(path)
                restored = manager._agents_by_id[person.agent_id]
                self.assertTrue(manager.list_team_messages(team.team_id, actor=restored).items[0].frozen)
                self.assertEqual(manager.list_friendship_requests(actor=restored)[0].status, "accepted")
                self.assertEqual(manager.inspect_direct_relationship(restored.agent_id, actor=manager.root_ai).generation, 2)

    async def test_inactive_and_audit_endpoints_cannot_receive_new_contact(self):
        manager, _, client = make_manager(self, volatile=True)
        manager._activity.schedule_notice = lambda _identifier: None
        person = manager.register_agent(Agent("Person", "Researcher", client))
        await manager.send_direct_message(person.agent_id, "Retained", actor=manager.root_ai)
        await manager.retire_agent(person.agent_id, "archive")
        for operation in (manager.send_direct_message(person.agent_id, "Denied", actor=manager.root_ai),
                          manager.request_friendship(person.agent_id, actor=manager.root_ai)):
            with self.assertRaises(PermissionError):
                await operation
        team = manager._team_creation.create_supervisory_team()
        with self.assertRaises(PermissionError):
            await manager.send_direct_message(team.members[0].agent_id, "Denied", actor=manager.root_ai)
        await manager._team_creation.dissolve_supervisory_team(team, persist=False)
        self.assertEqual(len([row for row in manager._records.snapshot() if row.table_name == "chat_messages"]), 1)
        with self.assertRaises(ToolBusinessError):
            await manager.send_direct_message(manager.root_ai.agent_id, "Self", actor=manager.root_ai)
