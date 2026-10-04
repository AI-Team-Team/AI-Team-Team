"""Real SQLite coverage for indexing while a discussion batch remains open."""

import asyncio
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from ai_team_team import ATTConfig, ATTManager, Agent, LLMResponse
from ai_team_team.core.exceptions import StatePersistenceError
from ai_team_team.core.memory import RetainedMemoryReference


class GatedMemoryClient:
    """Pauses one member and the indexer independently, without mocking storage."""

    def __init__(self):
        self.manager = None
        self.slow_agent_id = None
        self.slow_started = asyncio.Event()
        self.index_started = asyncio.Event()
        self.release_turn = asyncio.Event()
        self.release_index = asyncio.Event()
        self.index_response = json.dumps(
            {
                "title": "Completed work",
                "summary": "The Agent completed a recorded task.",
                "tags": ["work"],
            }
        )

    def supports_native_tool_calling(self):
        return False

    async def generate(
        self, prompt, system_instruction=None, require_json=False, **kwargs
    ):
        if require_json:
            if not system_instruction.startswith(
                "You are an isolated episodic-memory indexer"
            ):
                raise AssertionError("Unexpected structured model invocation.")
            self.index_started.set()
            await self.release_index.wait()
            return LLMResponse(text=self.index_response)
        chain = self.manager._agent_invocation_chain.get()
        if chain[-1][0] == self.slow_agent_id:
            self.slow_started.set()
            await self.release_turn.wait()
        return LLMResponse(text="Final Answer: complete")


class IncrementalMemoryDependencyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="att-memory-delta-")
        self.addCleanup(self.temporary.cleanup)
        self.db_path = str(Path(self.temporary.name) / "state.db")
        self.managers = []
        self.clients = []
        self.discussions = []

    async def asyncTearDown(self):
        for client in self.clients:
            client.release_turn.set()
            client.release_index.set()
        await asyncio.wait_for(
            asyncio.gather(*self.discussions, return_exceptions=True), 10
        )
        for manager in reversed(self.managers):
            await manager.close()

    def make_manager(self, *, incremental=True):
        client = GatedMemoryClient()
        manager = ATTManager(
            Agent("Root", "Architect", client),
            ATTConfig(
                workspace_root=str(Path(self.temporary.name) / "workspace"),
                episodic_memory={
                    "enabled": True,
                    "index_worker_count": 1,
                    "index_retry_backoff_factor": 0.0,
                },
            ),
            db_path=self.db_path if incremental else None,
        )
        self.managers.append(manager)
        self.clients.append(client)
        client.manager = manager
        manager.register_llm_client("memory-model", client)
        return manager, client

    def rows(self, sql, parameters=()):
        with closing(sqlite3.connect(self.db_path)) as connection:
            return connection.execute(sql, parameters).fetchall()

    async def pause_discussion(self, manager, client, team):
        client.slow_agent_id = team.members[-1].agent_id
        discussion = asyncio.create_task(
            manager.execute_team_discussion_detailed(
                team, "Complete a recorded task.", rounds=1, skip_audit=True
            )
        )
        self.discussions.append(discussion)
        await asyncio.wait_for(client.slow_started.wait(), 10)
        await asyncio.wait_for(client.index_started.wait(), 10)
        self.assertFalse(discussion.done())
        return discussion

    async def finish_discussion(self, manager, client, discussion):
        client.release_turn.set()
        result = await asyncio.wait_for(discussion, 10)
        self.assertEqual(result.status.value, "completed")
        client.release_index.set()
        await asyncio.wait_for(manager.flush_memory_indexing(), 10)
        await manager.flush_state()

    async def assert_dependency_complete(self, manager):
        await manager.flush_state()
        state = await manager._persistence.read(self.db_path)
        manager._validate_state_snapshot(state)
        persisted_events = {event["event_id"] for event in state["memory_events"]}
        self.assertTrue(state["memory_segments"])
        for segment in state["memory_segments"]:
            self.assertLessEqual(set(segment["source_event_ids"]), persisted_events)
        self.assertEqual(self.rows("PRAGMA foreign_key_check"), [])
        return state

    async def verify_open_batch(self, manager, client, team):
        await manager.flush_state()
        original_rows = {
            table: self.rows(f"SELECT * FROM {table} ORDER BY 1")
            for table in ("agents", "agent_messages", "teams", "libraries")
        }
        discussion = await self.pause_discussion(manager, client, team)
        state = await self.assert_dependency_complete(manager)
        self.assertTrue(
            any(segment["status"] == "processing" for segment in state["memory_segments"])
        )
        for table, rows in original_rows.items():
            self.assertEqual(self.rows(f"SELECT * FROM {table} ORDER BY 1"), rows, table)

        # The indexer also finishes before the discussion submits its Journal batch.
        client.release_index.set()
        await asyncio.wait_for(manager.flush_memory_indexing(), 10)
        state = await self.assert_dependency_complete(manager)
        self.assertTrue(state["memory_cards"])
        self.assertFalse(discussion.done())
        await self.finish_discussion(manager, client, discussion)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM agent_memory_cards"), [(3,)])
        await manager.save_state()
        await manager.close()

    async def test_constructor_database_indexes_before_discussion_batch_commits(self):
        manager, client = self.make_manager()
        team = manager.create_agent_team(manager.root_ai, member_count=3)
        await manager.save_state()
        await self.verify_open_batch(manager, client, team)

    async def test_restored_database_indexes_before_discussion_batch_commits(self):
        original, _ = self.make_manager(incremental=False)
        team = original.create_agent_team(original.root_ai, member_count=3)
        await original.save_state(self.db_path)
        await original.close()
        manager, client = self.make_manager(incremental=False)
        await manager.load_state(self.db_path)
        self.assertEqual(manager.db_path, self.db_path)
        await self.verify_open_batch(manager, client, manager.teams[team.team_id])

    async def test_processing_checkpoint_restores_and_resumes_its_index_job(self):
        manager, client = self.make_manager()
        team = manager.create_agent_team(manager.root_ai, member_count=3)
        await manager.save_state()
        discussion = await self.pause_discussion(manager, client, team)
        checkpoint_state = await self.assert_dependency_complete(manager)
        checkpoint = str(Path(self.temporary.name) / "processing-checkpoint.db")
        with closing(sqlite3.connect(self.db_path)) as source:
            with closing(sqlite3.connect(checkpoint)) as target:
                source.backup(target)
        expected_segments = {
            segment["segment_id"] for segment in checkpoint_state["memory_segments"]
        }
        await self.finish_discussion(manager, client, discussion)
        await manager.close()

        restored, restored_client = self.make_manager(incremental=False)
        await restored.load_state(checkpoint)
        self.assertEqual(set(restored._memory.segments), expected_segments)
        self.assertTrue(
            all(segment.status.value == "pending" for segment in restored._memory.segments.values())
        )
        restored_client.release_index.set()
        await asyncio.wait_for(restored.flush_memory_indexing(), 10)
        await restored.flush_state()
        state = await restored._persistence.read(checkpoint)
        restored._validate_state_snapshot(state)
        self.assertEqual(len(state["memory_cards"]), len(expected_segments))
        self.assertTrue(all(segment["status"] == "indexed" for segment in state["memory_segments"]))
        with closing(sqlite3.connect(checkpoint)) as connection:
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])

    async def test_new_nested_team_dependencies_are_restorable_before_batch_commits(self):
        manager, client = self.make_manager()
        await manager.save_state()
        async with manager.suppress_auto_save():
            parent = manager.create_agent_team(manager.root_ai, member_count=3)
            team = manager.create_agent_team(parent, member_count=3)
            discussion = await self.pause_discussion(manager, client, team)
            state = await self.assert_dependency_complete(manager)
            self.assertEqual(
                {row["team_id"] for row in state["teams"]},
                {parent.team_id, team.team_id},
            )
            self.assertEqual(len(state["agents"]), 7)
            self.assertEqual(len(state["libraries"]), 9)
            client.release_index.set()
            await asyncio.wait_for(manager.flush_memory_indexing(), 10)
            await self.assert_dependency_complete(manager)
            await self.finish_discussion(manager, client, discussion)
        await self.assert_dependency_complete(manager)

    async def test_index_failure_delta_keeps_sources_while_discussion_remains_open(self):
        manager, client = self.make_manager()
        manager.config.episodic_memory.index_max_retries = 0
        team = manager.create_agent_team(manager.root_ai, member_count=3)
        await manager.save_state()
        discussion = await self.pause_discussion(manager, client, team)
        client.index_response = '{"title": false}'
        client.release_index.set()
        await asyncio.wait_for(manager.flush_memory_indexing(), 10)
        state = await self.assert_dependency_complete(manager)
        self.assertTrue(all(segment["status"] == "failed" for segment in state["memory_segments"]))
        self.assertFalse(state["memory_cards"])
        self.assertFalse(discussion.done())
        await self.finish_discussion(manager, client, discussion)

    async def test_index_cancellation_delta_keeps_sources_and_pending_state(self):
        manager, client = self.make_manager()
        team = manager.create_agent_team(manager.root_ai, member_count=3)
        await manager.save_state()
        discussion = await self.pause_discussion(manager, client, team)
        await manager._memory.close()
        state = await self.assert_dependency_complete(manager)
        self.assertTrue(all(segment["status"] == "pending" for segment in state["memory_segments"]))
        self.assertFalse(state["memory_cards"])
        self.assertFalse(discussion.done())
        client.release_turn.set()
        await asyncio.wait_for(discussion, 10)
        await self.assert_dependency_complete(manager)

    async def prepare_unpersisted_memory(self):
        manager, client = self.make_manager(incremental=False)
        team = manager.create_agent_team(manager.root_ai, member_count=3)
        private_library = manager.libraries[team.members[0].private_doc_library_id]
        private_library.write_file("notes.txt", "Persisted private notes.")
        await manager.save_state(self.db_path)
        client.release_turn.set()
        client.release_index.set()
        await team.execute_reasoning_step_detailed(
            team.members[0], "Create a memory.", "System.", manager=manager
        )
        await manager.flush_memory_indexing()
        return manager, team

    async def test_segment_only_delta_includes_sources_owner_and_indexed_card(self):
        manager, team = await self.prepare_unpersisted_memory()
        private_library = manager.libraries[team.members[0].private_doc_library_id]
        private_library.write_file("notes.txt", "Updated private notes not yet saved.")
        dirty = manager._new_dirty_state()
        dirty["memory_segments"] = set(manager._memory.segments)
        delta = manager._capture_state_snapshot(dirty)
        self.assertFalse(delta["agents"])
        self.assertFalse(delta["teams"])
        self.assertEqual(len(delta["memory_cards"]), 1)
        self.assertEqual(
            {event["event_id"] for event in delta["memory_events"]},
            set(delta["memory_segments"][0]["source_event_ids"]),
        )
        self.assertIn(
            team.members[0].agent_id,
            {agent["agent_id"] for agent in delta["agent_dependencies"]},
        )
        await asyncio.wrap_future(manager._persistence.submit(self.db_path, delta))
        await self.assert_dependency_complete(manager)
        original_events = self.rows("SELECT * FROM system_memory_events ORDER BY sequence")
        original_agents = self.rows("SELECT * FROM agent_messages ORDER BY id")
        await asyncio.wrap_future(manager._persistence.submit(self.db_path, delta))
        self.assertEqual(
            self.rows("SELECT * FROM system_memory_events ORDER BY sequence"),
            original_events,
        )
        self.assertEqual(
            self.rows("SELECT * FROM agent_messages ORDER BY id"), original_agents
        )
        self.assertEqual(
            self.rows(
                "SELECT content FROM doc_lib_files WHERE lib_id=? AND path=?",
                (private_library.lib_id, "notes.txt"),
            ),
            [("Persisted private notes.",)],
        )

    async def test_provenance_dependencies_keep_distinct_parent_and_creator_after_migration(self):
        manager, client = self.make_manager(incremental=False)
        manager.config.migration_policy = "permissive"
        await manager.save_state(self.db_path)
        original_parent = manager.create_agent_team(manager.root_ai, member_count=3)
        current_parent = manager.create_agent_team(manager.root_ai, member_count=3)
        team = manager.create_agent_team(original_parent, member_count=3)
        approved, reason = await manager.negotiate_and_execute_migration(
            team, current_parent, "Move to a different parent."
        )
        self.assertTrue(approved, reason)
        client.release_turn.set()
        client.release_index.set()
        await team.execute_reasoning_step_detailed(
            team.members[0], "Create a memory after migration.", "System.", manager=manager
        )
        await manager.flush_memory_indexing()
        dirty = manager._new_dirty_state()
        dirty["memory_cards"] = set(manager._memory.cards)
        delta = manager._capture_state_snapshot(dirty)
        self.assertEqual(
            {record["team_id"] for record in delta["team_dependencies"]},
            {original_parent.team_id, current_parent.team_id, team.team_id},
        )
        # Supply the child first to ensure insertion does not depend on ID order.
        delta["team_dependencies"].sort(key=lambda record: record["team_id"] != team.team_id)
        await asyncio.wrap_future(manager._persistence.submit(self.db_path, delta))
        state = await self.assert_dependency_complete(manager)
        restored_team = next(record for record in state["teams"] if record["team_id"] == team.team_id)
        self.assertEqual(restored_team["parent_team_id"], current_parent.team_id)
        self.assertEqual(restored_team["creator_type"], "team")
        self.assertEqual(restored_team["creator_id"], original_parent.team_id)

    async def test_card_only_delta_includes_its_segment_and_source_events(self):
        manager, _ = await self.prepare_unpersisted_memory()
        dirty = manager._new_dirty_state()
        dirty["memory_cards"] = set(manager._memory.cards)
        delta = manager._capture_state_snapshot(dirty)
        self.assertEqual(len(delta["memory_segments"]), 1)
        self.assertTrue(delta["memory_events"])
        await asyncio.wrap_future(manager._persistence.submit(self.db_path, delta))
        await self.assert_dependency_complete(manager)

    async def test_reference_only_delta_includes_card_segment_sources_and_owner(self):
        manager, _ = await self.prepare_unpersisted_memory()
        card = next(iter(manager._memory.cards.values()))
        reference = RetainedMemoryReference(
            reference_id="MRF-reference-dependency",
            agent_id=card.agent_id,
            memory_id=card.memory_id,
            note="Retained reference.",
            created_at=card.created_at,
        )
        manager._memory.references[reference.reference_id] = reference
        dirty = manager._new_dirty_state()
        dirty["memory_references"] = {reference.reference_id}
        delta = manager._capture_state_snapshot(dirty)
        self.assertEqual(len(delta["memory_cards"]), 1)
        self.assertEqual(len(delta["memory_segments"]), 1)
        self.assertTrue(delta["memory_events"])
        await asyncio.wrap_future(manager._persistence.submit(self.db_path, delta))
        state = await self.assert_dependency_complete(manager)
        self.assertEqual(state["memory_references"][0]["reference_id"], reference.reference_id)

    async def test_source_dependency_replay_rejects_mutation_and_propagates_error(self):
        manager, _ = await self.prepare_unpersisted_memory()
        dirty = manager._new_dirty_state()
        dirty["memory_segments"] = set(manager._memory.segments)
        delta = manager._capture_state_snapshot(dirty)
        await asyncio.wrap_future(manager._persistence.submit(self.db_path, delta))
        original_events = self.rows("SELECT * FROM system_memory_events ORDER BY sequence")
        altered_event = {
            **delta["memory_events"][0],
            "payload": {"tampered": True},
        }
        corrupted = {
            **delta,
            "memory_events": [altered_event, *delta["memory_events"][1:]],
        }
        with self.assertRaisesRegex(ValueError, "Immutable journal event") as raised:
            await asyncio.wrap_future(manager._persistence.submit(self.db_path, corrupted))
        self.assertEqual(
            self.rows("SELECT * FROM system_memory_events ORDER BY sequence"),
            original_events,
        )
        for boundary in (
            manager.flush_state,
            lambda: manager.save_state(self.db_path),
            manager.close,
        ):
            with self.assertRaises(ValueError) as repeated:
                await boundary()
            self.assertIs(repeated.exception, raised.exception)

    async def test_missing_segment_dependency_fails_snapshot_capture_explicitly(self):
        manager, _ = await self.prepare_unpersisted_memory()
        segment = next(iter(manager._memory.segments.values()))
        dirty = manager._new_dirty_state()
        dirty["memory_segments"] = {segment.segment_id}
        missing_event_id = segment.source_event_ids[0]
        missing_event = manager._memory.events.pop(missing_event_id)
        try:
            with self.assertRaisesRegex(StatePersistenceError, missing_event_id):
                manager._capture_state_snapshot(dirty)
        finally:
            manager._memory.events[missing_event_id] = missing_event
        owner = manager._agents_by_id.pop(segment.agent_id)
        try:
            with self.assertRaisesRegex(StatePersistenceError, segment.agent_id):
                manager._capture_state_snapshot(dirty)
        finally:
            manager._agents_by_id[segment.agent_id] = owner
