from test.test_att.test_private_doclib._support import (
    ATTConfig,
    ATTManager,
    Agent,
    DummyClient,
    PrivateAgentDocLibTestCase,
    SequenceClient,
    StateRestoreError,
    asyncio,
    os,
    sqlite3,
)
from test.personal_activity import interact_and_idle


class TestPrivateAgentDocLib(PrivateAgentDocLibTestCase):
    async def test_react_private_payload_is_not_durable_or_callback_visible(self):
        secret = "PRIVATE-CALLBACK-SENTINEL"
        client = SequenceClient(
            [
                "Thought: save a deliberate note\n"
                f"Action: write_private_file(path='note.txt', content='{secret}')",
                "Final Answer: note saved",
            ]
        )
        writer = Agent("ReActWriter", "Writer", client)
        self.manager.register_agent(writer)
        team = self.manager.bootstrap_agent_team(
            self.root, parent=self.root,
            member_configs={
                "PeerC": {"model": "default"},
                "PeerD": {"model": "default"},
            },
            existing_members=[writer],
        )
        callbacks = []
        self.manager.on_system_event = lambda *args: callbacks.append(args)
        self.manager.register_llm_client("writer", client)
        result = await interact_and_idle(self.manager, writer, "Save the note.", team=team)
        await self.manager.flush_callbacks()
        self.assertEqual(result.answer, "note saved")
        self.assertNotIn(secret, repr(callbacks))
        self.assertNotIn(secret, repr(writer.message_history))
        private = self.manager.libraries[writer.private_doc_library_id]
        self.assertEqual(private.read_text("note.txt"), secret)

    async def test_private_read_can_inform_result_without_persisting_body(self):
        secret = "PRIVATE-READ-SENTINEL"
        client = SequenceClient(
            [
                "Thought: consult my note\n"
                "Action: read_private_file(path='note.txt')",
                f"Final Answer: {secret}",
            ]
        )
        reader = Agent("ReActReader", "Reader", client)
        self.manager.register_agent(reader)
        team = self.manager.bootstrap_agent_team(
            self.root, parent=self.root,
            member_configs={
                "PeerR1": {"model": "default"},
                "PeerR2": {"model": "default"},
            },
            existing_member_ids=[reader.agent_id],
        )
        self.manager.libraries[reader.private_doc_library_id].write_file(
            "note.txt", secret
        )
        callbacks = []
        self.manager.on_system_event = lambda *args: callbacks.append(args)
        self.manager.register_llm_client("reader", client)

        result = await interact_and_idle(self.manager, reader, "Consult your private note.", team=team)
        await self.manager.flush_callbacks()

        self.assertEqual(result.answer, secret)
        self.assertIn(secret, client.prompt_snapshots[1])
        self.assertNotIn(secret, repr(callbacks))
        self.assertNotIn(secret, repr(reader.message_history))
        self.assertNotIn(secret, repr(reader.messages))
