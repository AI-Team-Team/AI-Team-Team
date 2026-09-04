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


class TestPrivateAgentDocLib(PrivateAgentDocLibTestCase):
    async def test_registration_private_boundary_and_shared_identity(self):
        shared = Agent("Shared", "Researcher", self.client)
        self.manager.register_agent(shared)
        private_id = self.manager.get_private_library_id(shared.agent_id)
        self.assertEqual(private_id, f"PDL-{shared.agent_id}")
        self.assertEqual(shared.private_doc_library_id, private_id)
        private = self.manager.libraries[private_id]
        self.assertEqual(private.library_kind, "agent_private")
        self.assertFalse(private.is_public_visible)

        first = self.manager.create_agent_team(
            self.root,
            member_configs={
                "One": {"model": "default"},
                "Two": {"model": "default"},
            },
            existing_members=[shared],
        )
        second = self.manager.create_agent_team(
            self.root,
            member_configs={
                "Three": {"model": "default"},
                "Four": {"model": "default"},
            },
            existing_member_ids=[shared.agent_id],
        )
        self.assertIn(shared, first.members)
        self.assertIn(shared, second.members)
        self.assertEqual(
            sum(
                library.owner_agent_id == shared.agent_id
                for library in self.manager.libraries.values()
            ),
            1,
        )

        with self.assertRaises(PermissionError):
            await self.manager.read_private_file("notes.txt")
        self.assertFalse(
            self.manager.check_library_access(
                first.team_id, private_id, "/", "READ"
            )
        )

        tokens = self._activate(shared, first)
        try:
            await self.manager.write_private_file("notes.txt", "private secret")
            self.assertIn(
                "private secret",
                await self.manager.read_private_file("notes.txt"),
            )
            await self.manager.publish_private_file(
                "notes.txt", "published.txt"
            )
            self.assertIn(
                "Permission denied",
                await first.tools["read_library_file"](
                    private_id, "notes.txt"
                ),
            )
            self.assertIn(
                "Permission denied",
                await first.tools["update_library_metadata"](
                    private_id, is_public=True
                ),
            )
            self.assertIn(
                "Permission denied",
                await first.tools["grant_library_permission"](
                    private_id, "/", second.team_id, "READ"
                ),
            )
            self.assertIn(
                "Private DocLibs cannot participate",
                await first.tools["create_library_link"](
                    first.doc_library.lib_id,
                    "private-link.txt",
                    private_id,
                    "notes.txt",
                ),
            )
            self.assertNotIn(
                private_id,
                await first.tools["list_public_libraries"](),
            )
        finally:
            self._deactivate(tokens)
        self.assertTrue(first.doc_library.is_file("published.txt"))
        self.assertFalse(second.doc_library.path_exists("published.txt"))

        tokens = self._activate(shared, second)
        try:
            self.assertIn(
                "private secret",
                await self.manager.read_private_file("notes.txt"),
            )
        finally:
            self._deactivate(tokens)

    async def test_publish_collision_move_and_private_events_hide_content(self):
        agent = Agent("Publisher", "Writer", self.client)
        self.manager.register_agent(agent)
        team = self.manager.create_agent_team(
            self.root,
            member_configs={
                "PeerA": {"model": "default"},
                "PeerB": {"model": "default"},
            },
            existing_members=[agent],
        )
        events = []
        self.manager.on_system_event = lambda kind, payload: events.append(
            (kind, payload)
        )
        tokens = self._activate(agent, team)
        try:
            await self.manager.write_private_file("draft.txt", "TOP SECRET BODY")
            await self.manager.move_private_file("draft.txt", "final.txt")
            team.doc_library.write_file("result.txt", "existing")
            with self.assertRaises(FileExistsError):
                await self.manager.publish_private_file(
                    "final.txt", "result.txt"
                )
            await self.manager.publish_private_file(
                "final.txt", "result.txt", overwrite=True
            )
            await self.manager.move_library_file(
                team.team_id,
                team.doc_library.lib_id,
                "result.txt",
                "renamed.txt",
            )
        finally:
            self._deactivate(tokens)
        await self.manager.flush_callbacks()
        self.assertFalse(team.doc_library.path_exists("result.txt"))
        self.assertIn("TOP SECRET BODY", team.doc_library.read_file("renamed.txt"))
        self.assertTrue(events)
        self.assertNotIn("TOP SECRET BODY", repr(events))
        self.assertNotIn("TOP SECRET BODY", repr(agent.message_history))
