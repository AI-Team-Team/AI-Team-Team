import asyncio
import os
import shutil
import sqlite3
import tempfile
import unittest

from ai_team_team import Agent, ATTConfig, ATTManager
from ai_team_team.core import StateRestoreError


class DummyClient:
    async def generate(self, prompt, **kwargs):
        return "ok"


class SequenceClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.prompt_snapshots = []

    async def generate(self, prompt, **kwargs):
        self.prompt_snapshots.append(repr(prompt))
        return self.responses.pop(0)


class TestPrivateAgentDocLib(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="att-private-")
        self.client = DummyClient()
        self.root = Agent("Root", "Architect", self.client)
        self.manager = ATTManager(
            self.root,
            ATTConfig(workspace_root=self.temp_dir),
        )
        self.manager.register_llm_client("default", self.client)

    async def asyncTearDown(self):
        await self.manager.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _activate(self, agent, team=None):
        agent_token = self.manager._active_tool_agent.set(agent)
        team_token = self.manager._active_team.set(team)
        return agent_token, team_token

    def _deactivate(self, tokens):
        agent_token, team_token = tokens
        self.manager._active_team.reset(team_token)
        self.manager._active_tool_agent.reset(agent_token)

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
                "shared": shared,
                "one": Agent("One", "One", self.client),
                "two": Agent("Two", "Two", self.client),
            },
        )
        second = self.manager.create_agent_team(
            self.root,
            member_configs={
                "shared": shared,
                "three": Agent("Three", "Three", self.client),
                "four": Agent("Four", "Four", self.client),
            },
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
        team = self.manager.create_agent_team(
            self.root,
            member_configs={
                "publisher": agent,
                "peer-a": Agent("PeerA", "Peer", self.client),
                "peer-b": Agent("PeerB", "Peer", self.client),
            },
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
        team = self.manager.create_agent_team(
            self.root,
            member_configs={
                "writer": writer,
                "peer-c": Agent("PeerC", "Peer", self.client),
                "peer-d": Agent("PeerD", "Peer", self.client),
            },
        )
        callbacks = []
        self.manager.on_activity_added = lambda *args: callbacks.append(args)
        self.manager.on_log_append = lambda *args: callbacks.append(args)
        result = await team.execute_reasoning_step(
            writer,
            "Save the note.",
            "Use the private workspace.",
            max_steps=2,
            manager=self.manager,
        )
        await self.manager.flush_callbacks()
        self.assertEqual(result, "note saved")
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
        team = self.manager.create_agent_team(
            self.root,
            member_configs={
                "reader": reader,
                "peer-r1": Agent("PeerR1", "Peer", self.client),
                "peer-r2": Agent("PeerR2", "Peer", self.client),
            },
        )
        self.manager.libraries[reader.private_doc_library_id].write_file(
            "note.txt", secret
        )
        callbacks = []
        self.manager.on_activity_added = lambda *args: callbacks.append(args)
        self.manager.on_log_append = lambda *args: callbacks.append(args)

        result = await team.execute_reasoning_step(
            reader,
            "Consult your private note.",
            "Use the private workspace only when needed.",
            max_steps=2,
            manager=self.manager,
        )
        await self.manager.flush_callbacks()

        self.assertEqual(result, secret)
        self.assertIn(secret, client.prompt_snapshots[1])
        self.assertNotIn(secret, repr(callbacks))
        self.assertNotIn(secret, repr(reader.message_history))
        self.assertNotIn(secret, repr(reader.messages))

    async def test_archive_retain_reactivate_and_delete(self):
        with self.assertRaises(ValueError):
            await self.manager.retire_agent(self.root.agent_id)

        member = Agent("StillMember", "Member", self.client)
        self.manager.create_agent_team(
            self.root,
            member_configs={
                "member": member,
                "peer-e": Agent("PeerE", "Peer", self.client),
                "peer-f": Agent("PeerF", "Peer", self.client),
            },
        )
        with self.assertRaises(ValueError):
            await self.manager.retire_agent(member.agent_id)

        creator = Agent("Creator", "Lead", self.client)
        self.manager.create_agent_team(creator)
        with self.assertRaises(ValueError):
            await self.manager.retire_agent(creator.agent_id)

        busy = Agent("Busy", "Worker", self.client)
        self.manager.register_agent(busy)
        async with busy.lock:
            with self.assertRaises(ValueError):
                await self.manager.retire_agent(busy.agent_id)

        archived = Agent("Archived", "Researcher", self.client)
        self.manager.register_agent(archived)
        archived_lib = self.manager.libraries[
            archived.private_doc_library_id
        ]
        tokens = self._activate(archived)
        try:
            await self.manager.write_private_file("memory.txt", "remember me")
        finally:
            self._deactivate(tokens)

        await self.manager.retire_agent(archived.agent_id, "archive")
        self.assertNotIn(archived.name, self.manager.agents)
        self.assertEqual(archived.lifecycle_state, "archived")
        with self.assertRaises(PermissionError):
            archived_lib.write_file("blocked.txt", "blocked")
        with self.assertRaises(PermissionError):
            archived_lib.write_file_atomic("blocked.txt", "blocked")
        with self.assertRaises(PermissionError):
            archived_lib.move_file("memory.txt", "moved.txt")
        with self.assertRaises(PermissionError):
            archived_lib.replace_all_files({"replacement.txt": "blocked"})
        await self.manager.reactivate_agent(archived.agent_id, "default")
        self.assertIs(self.manager.agents[archived.name], archived)
        self.assertIn("remember me", archived_lib.read_file("memory.txt"))

        retained = Agent("Retained", "Researcher", self.client)
        self.manager.register_agent(retained)
        await self.manager.retire_agent(retained.agent_id, "retain")
        self.assertEqual(retained.lifecycle_state, "retained")
        self.manager.libraries[retained.private_doc_library_id].write_file(
            "host-note.txt", "trusted host"
        )
        await self.manager.reactivate_agent(retained.agent_id, "default")

        doomed = Agent("Doomed", "Temporary", self.client)
        self.manager.register_agent(doomed)
        doomed_id = doomed.agent_id
        doomed_lib_id = doomed.private_doc_library_id
        doomed_root = self.manager.libraries[doomed_lib_id].root_dir
        with self.assertRaises(ValueError):
            await self.manager.retire_agent(doomed_id, "delete")
        await self.manager.retire_agent(
            doomed_id, "delete", confirm_delete=True
        )
        self.assertNotIn(doomed_id, self.manager._agents_by_id)
        self.assertNotIn(doomed_lib_id, self.manager.libraries)
        self.assertFalse(os.path.exists(doomed_root))

        unbound = Agent("Unbound", "Temporary", DummyClient())
        self.manager.register_agent(unbound)
        await self.manager.retire_agent(
            unbound.agent_id, "delete", confirm_delete=True
        )
        self.assertEqual(unbound.lifecycle_state, "deleted")

    async def test_lifecycle_operations_are_serialized_per_agent(self):
        agent = Agent("Lifecycle", "Researcher", self.client)
        self.manager.register_agent(agent)
        retire_results = await asyncio.gather(
            self.manager.retire_agent(agent.agent_id, "archive"),
            self.manager.retire_agent(agent.agent_id, "archive"),
            return_exceptions=True,
        )
        self.assertEqual(sum(result is None for result in retire_results), 1)
        self.assertEqual(
            sum(isinstance(result, ValueError) for result in retire_results),
            1,
        )

        reactivate_results = await asyncio.gather(
            self.manager.reactivate_agent(agent.agent_id, "default"),
            self.manager.reactivate_agent(agent.agent_id, "default"),
            return_exceptions=True,
        )
        self.assertEqual(sum(result is agent for result in reactivate_results), 1)
        self.assertEqual(
            sum(
                isinstance(result, ValueError)
                for result in reactivate_results
            ),
            1,
        )

    async def test_active_invocation_cannot_race_retirement(self):
        started = asyncio.Event()
        release = asyncio.Event()

        class BlockingClient:
            async def generate(self, prompt, **kwargs):
                started.set()
                await release.wait()
                return "Final Answer: complete"

        blocking_client = BlockingClient()
        self.manager.register_llm_client("blocking", blocking_client)
        worker = Agent("Blocking", "Worker", blocking_client)
        self.manager.register_agent(worker)
        team = self.manager.create_agent_team(self.root)
        state_path = os.path.join(self.temp_dir, "active-invocation.db")
        self.manager.db_path = state_path
        await self.manager.save_state()
        task = asyncio.create_task(
            team.execute_reasoning_step(
                worker,
                "Work.",
                "Complete the task.",
                manager=self.manager,
            )
        )
        await started.wait()
        with self.assertRaisesRegex(ValueError, "active model invocation"):
            await self.manager.retire_agent(worker.agent_id, "archive")
        with self.assertRaisesRegex(StateRestoreError, "invocation"):
            await self.manager.load_state(state_path)
        release.set()
        self.assertEqual(await task, "complete")
        await self.manager.retire_agent(worker.agent_id, "archive")

    async def test_delete_revalidates_membership_after_preflush(self):
        agent = Agent("DeleteRace", "Temporary", self.client)
        self.manager.register_agent(agent)
        started = asyncio.Event()
        release = asyncio.Event()
        original_flush = self.manager.flush_state

        async def delayed_flush():
            started.set()
            await release.wait()
            await original_flush()

        self.manager.flush_state = delayed_flush
        deletion = asyncio.create_task(
            self.manager.retire_agent(
                agent.agent_id, "delete", confirm_delete=True
            )
        )
        await started.wait()
        team = self.manager.create_agent_team(
            self.root,
            member_configs={
                "worker": agent,
                "peer-d1": Agent("PeerD1", "Peer", self.client),
                "peer-d2": Agent("PeerD2", "Peer", self.client),
            },
        )
        release.set()
        with self.assertRaisesRegex(ValueError, "still belongs"):
            await deletion
        self.assertIs(self.manager._agents_by_id[agent.agent_id], agent)
        self.assertIn(agent, team.members)
        self.assertIn(agent.private_doc_library_id, self.manager.libraries)

    async def test_schema_five_round_trip_and_corruption_is_atomic(self):
        db_path = os.path.join(self.temp_dir, "state.db")
        self.manager.db_path = db_path
        active = Agent("Active", "Researcher", self.client)
        inactive = Agent("Inactive", "Researcher", self.client)
        self.manager.register_agent(active)
        self.manager.register_agent(inactive)
        tokens = self._activate(active)
        try:
            await self.manager.write_private_file("active.txt", "active-data")
        finally:
            self._deactivate(tokens)
        await self.manager.retire_agent(inactive.agent_id, "archive")
        await self.manager.save_state()
        await self.manager.close()

        restored_root = Agent("Replacement", "Architect", self.client)
        restored = ATTManager(
            restored_root,
            ATTConfig(workspace_root=self.temp_dir),
        )
        restored.register_llm_client("default", self.client)
        await restored.load_state(db_path)
        try:
            self.assertEqual(restored.root_ai.agent_id, self.root.agent_id)
            self.assertEqual(
                restored._agents_by_id[inactive.agent_id].lifecycle_state,
                "archived",
            )
            private = restored.libraries[f"PDL-{active.agent_id}"]
            self.assertIn("active-data", private.read_file("active.txt"))
            self.assertEqual(
                sum(lib.library_kind == "agent_private" for lib in restored.libraries.values()),
                len(restored._agents_by_id),
            )
            corrupt_path = os.path.join(self.temp_dir, "corrupt.db")
            shutil.copy2(db_path, corrupt_path)
            connection = sqlite3.connect(corrupt_path)
            try:
                connection.execute(
                    "UPDATE libraries SET is_public_visible = 1 WHERE lib_id = ?",
                    (f"PDL-{active.agent_id}",),
                )
                connection.commit()
            finally:
                connection.close()
            original_root_id = restored.root_ai.agent_id
            original_private_content = restored.libraries[
                f"PDL-{active.agent_id}"
            ].read_file("active.txt")
            with self.assertRaises(StateRestoreError):
                await restored.load_state(corrupt_path)
            self.assertEqual(restored.root_ai.agent_id, original_root_id)
            self.assertEqual(
                restored.libraries[f"PDL-{active.agent_id}"].read_file(
                    "active.txt"
                ),
                original_private_content,
            )
        finally:
            await restored.close()


if __name__ == "__main__":
    unittest.main()
