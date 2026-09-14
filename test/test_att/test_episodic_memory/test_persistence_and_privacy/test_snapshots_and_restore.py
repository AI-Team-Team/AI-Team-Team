import os
import sqlite3
from copy import deepcopy
from contextlib import closing

from ai_team_team import (
    ATTConfig,
    ATTManager,
    Agent,
    LLMResponse,
    StateRestoreError,
    ToolCall,
)

from test.test_att.test_episodic_memory._support import (
    EpisodicMemoryTestCase,
    ScriptedMemoryClient,
)
from ai_team_team.core.memory import SystemMemoryEvent
from ai_team_team.core.memory.sanitization import content_digest, render_recall_content




class TestPersistenceAndPrivacy(EpisodicMemoryTestCase):
    async def test_full_snapshot_redacts_invocation_only_bodies_before_cleanup(self):
        private_secret = "PRIVATE-SNAPSHOT-SECRET"
        recalled_secret = "RECALLED-SNAPSHOT-SECRET"
        self.agent.messages.extend(
            [
                {
                    "role": "tool",
                    "content": f"[ATT_PRIVATE_OBSERVATION]\n{private_secret}",
                },
                {
                    "role": "tool",
                    "content": (
                        "[ATT_MEMORY_RECALL]\n"
                        f'{{"memory_id":"MEM-test","content":"{recalled_secret}"}}'
                    ),
                },
            ]
        )
        snapshot = self.manager._capture_state_snapshot(
            self.manager._new_dirty_state(full=True)
        )
        persisted = next(
            item
            for item in snapshot["agents"]
            if item["agent_id"] == self.agent.agent_id
        )["messages"]
        self.assertNotIn(private_secret, repr(persisted))
        self.assertNotIn(recalled_secret, repr(persisted))
        self.assertIn("[private tool result redacted]", repr(persisted))
        self.assertIn("[Historical memory recalled: MEM-test]", repr(persisted))
        self.agent.messages = self.agent.messages[:-2]

    async def test_schema_six_is_rejected_without_modification(self):
        db_path = os.path.join(self.tmpdir, "schema-six.db")
        with closing(sqlite3.connect(db_path)) as connection:
            connection.execute(
                "CREATE TABLE manager_config (config_key TEXT PRIMARY KEY, config_value TEXT)"
            )
            connection.execute(
                "INSERT INTO manager_config VALUES ('schema_version', '6')"
            )
            connection.execute("CREATE TABLE schema_six_marker (value TEXT)")
            connection.execute("INSERT INTO schema_six_marker VALUES ('unchanged')")
            connection.commit()

        replacement = ATTManager(
            Agent("Replacement", "Architect", self.client),
            ATTConfig(workspace_root=self.tmpdir),
        )
        with self.assertRaises(StateRestoreError):
            await replacement.load_state(db_path)
        await replacement.close()

        with closing(sqlite3.connect(db_path)) as connection:
            self.assertEqual(
                connection.execute("SELECT value FROM schema_six_marker").fetchone()[0],
                "unchanged",
            )
            self.assertIsNone(
                connection.execute(
                    "SELECT name FROM sqlite_master WHERE name='agent_memory_cards'"
                ).fetchone()
            )

    async def test_current_schema_restores_working_context_and_journal_separately(self):
        await self.team.execute_reasoning_step_detailed(
            self.agent,
            "Remember the complete historical record.",
            "System.",
            manager=self.manager,
        )
        await self.manager.flush_memory_indexing()
        journal_count = len(
            [
                event
                for event in self.manager._memory.events.values()
                if event.agent_id == self.agent.agent_id and event.event_type == "message"
            ]
        )
        self.agent.messages = self.agent.messages[-1:]
        expected_working_context = [dict(message) for message in self.agent.messages]
        db_path = os.path.join(self.tmpdir, "memory.db")
        await self.manager.save_state(db_path)
        await self.manager.close()

        temporary_root = Agent("Temporary", "Architect", self.client)
        restored = ATTManager(
            temporary_root,
            ATTConfig(workspace_root=self.tmpdir),
        )
        restored.register_llm_client("memory-model", self.client)
        await restored.load_state(db_path)
        restored_agent = restored._agents_by_id[self.agent.agent_id]
        self.assertEqual(restored_agent.messages, expected_working_context)
        self.assertEqual(len(restored_agent.message_history), journal_count)
        self.assertGreater(len(restored_agent.message_history), len(restored_agent.messages))
        self.assertEqual(len(restored._memory.cards), 1)
        self.assertTrue(restored.config.episodic_memory.enabled)
        self.assertIsNone(temporary_root._manager)
        self.assertIs(restored.root_ai._manager, restored)
        added_after_restore = Agent("AddedAfterRestore", "Researcher", self.client)
        restored.register_agent(added_after_restore)
        self.assertIs(restored.agents[added_after_restore.name], added_after_restore)
        self.assertIs(
            restored._agent_registry.by_id[added_after_restore.agent_id],
            added_after_restore,
        )
        await restored.close()

    async def test_enabled_database_has_fts_and_corrupt_segment_is_rejected_atomically(self):
        await self.team.execute_reasoning_step_detailed(
            self.agent,
            "Index the blue rocket.",
            "System.",
            manager=self.manager,
        )
        await self.manager.flush_memory_indexing()
        db_path = os.path.join(self.tmpdir, "fts.db")
        await self.manager.save_state(db_path)
        await self.manager.close()
        with closing(sqlite3.connect(db_path)) as connection:
            fts = connection.execute(
                "SELECT name FROM sqlite_master WHERE name='agent_memory_cards_fts'"
            ).fetchone()
            self.assertIsNotNone(fts)
            connection.execute(
                "UPDATE agent_memory_segments SET recall_content='tampered'"
            )
            connection.commit()

        replacement = ATTManager(
            Agent("Replacement", "Architect", self.client),
            ATTConfig(workspace_root=self.tmpdir),
        )
        replacement.register_llm_client("memory-model", self.client)
        original_root = replacement.root_ai
        with self.assertRaises(StateRestoreError):
            await replacement.load_state(db_path)
        self.assertIs(replacement.root_ai, original_root)
        self.assertFalse(replacement._memory.cards)
        await replacement.close()

    async def test_restore_validation_rejects_invalid_memory_lifecycle_edges(self):
        await self.team.execute_reasoning_step_detailed(
            self.agent,
            "Build a strictly validated memory.",
            "System.",
            manager=self.manager,
        )
        await self.manager.flush_memory_indexing()
        db_path = os.path.join(self.tmpdir, "memory-validation.db")
        await self.manager.save_state(db_path)
        state = await self.manager._persistence.read(db_path)

        missing_terminal = deepcopy(state)
        event_map = {
            event["event_id"]: SystemMemoryEvent.model_validate(event)
            for event in missing_terminal["memory_events"]
        }
        segment = missing_terminal["memory_segments"][0]
        segment["source_event_ids"] = [
            event_id
            for event_id in segment["source_event_ids"]
            if event_map[event_id].event_type != "agent_turn_finished"
        ]
        remaining = [event_map[event_id] for event_id in segment["source_event_ids"]]
        segment["recall_content"] = render_recall_content(remaining)
        segment["content_sha256"] = content_digest(segment["recall_content"])
        with self.assertRaisesRegex(StateRestoreError, "terminal event"):
            self.manager._validate_state_snapshot(missing_terminal)

        omitted_message = deepcopy(state)
        event_map = {
            event["event_id"]: SystemMemoryEvent.model_validate(event)
            for event in omitted_message["memory_events"]
        }
        segment = omitted_message["memory_segments"][0]
        omitted_id = next(
            event_id
            for event_id in segment["source_event_ids"]
            if event_map[event_id].event_type == "message"
        )
        segment["source_event_ids"].remove(omitted_id)
        remaining = [event_map[event_id] for event_id in segment["source_event_ids"]]
        segment["recall_content"] = render_recall_content(remaining)
        segment["content_sha256"] = content_digest(segment["recall_content"])
        with self.assertRaisesRegex(StateRestoreError, "omits or adds"):
            self.manager._validate_state_snapshot(omitted_message)

        forgotten_reference = deepcopy(state)
        card = forgotten_reference["memory_cards"][0]
        card["status"] = "forgotten"
        forgotten_reference["memory_references"] = [
            {
                "reference_id": "MRF-corrupt",
                "agent_id": card["agent_id"],
                "memory_id": card["memory_id"],
                "note": "This hidden card must not remain in working context.",
                "created_at": card["created_at"],
            }
        ]
        with self.assertRaisesRegex(StateRestoreError, "forgotten card"):
            self.manager._validate_state_snapshot(forgotten_reference)

        card_before_index = deepcopy(state)
        card_before_index["memory_segments"][0]["status"] = "pending"
        with self.assertRaisesRegex(StateRestoreError, "not indexed"):
            self.manager._validate_state_snapshot(card_before_index)

        indexed_without_card = deepcopy(state)
        indexed_without_card["memory_cards"] = []
        with self.assertRaisesRegex(StateRestoreError, "no Memory Card"):
            self.manager._validate_state_snapshot(indexed_without_card)

    async def test_restore_quiesces_existing_memory_index_workers(self):
        await self.team.execute_reasoning_step_detailed(
            self.agent,
            "Create restorable memory state.",
            "System.",
            manager=self.manager,
        )
        await self.manager.flush_memory_indexing()
        db_path = os.path.join(self.tmpdir, "restore-workers.db")
        await self.manager.save_state(db_path)

        self.manager._memory._ensure_workers()
        old_workers = tuple(self.manager._memory._workers)
        self.assertTrue(old_workers)
        self.assertTrue(any(not worker.done() for worker in old_workers))

        await self.manager.load_state(db_path)

        self.assertTrue(all(worker.done() for worker in old_workers))

    async def test_disabled_snapshot_with_cards_needs_no_fts_and_rebuilds_on_reenable(self):
        await self.team.execute_reasoning_step_detailed(
            self.agent,
            "Create a card before disabling the optional catalog.",
            "System.",
            manager=self.manager,
        )
        await self.manager.flush_memory_indexing()
        db_path = os.path.join(self.tmpdir, "disabled-with-cards.db")
        await self.manager.save_state(db_path)
        with closing(sqlite3.connect(db_path)) as connection:
            self.assertIsNotNone(
                connection.execute(
                    "SELECT name FROM sqlite_master WHERE name='agent_memory_cards_fts'"
                ).fetchone()
            )

        self.manager.config.episodic_memory.enabled = False
        await self.manager.save_state(db_path)
        with closing(sqlite3.connect(db_path)) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM agent_memory_cards"
                ).fetchone()[0],
                1,
            )
            self.assertIsNone(
                connection.execute(
                    "SELECT name FROM sqlite_master WHERE name='agent_memory_cards_fts'"
                ).fetchone()
            )
        await self.manager.close()

        restored = ATTManager(
            Agent("Temporary", "Architect", self.client),
            ATTConfig(
                workspace_root=self.tmpdir,
                episodic_memory={"enabled": True},
            ),
        )
        restored._memory.ensure_enabled()
        self.assertTrue(restored._memory._fts_sync_active)
        restored.register_llm_client("memory-model", self.client)
        await restored.load_state(db_path)
        self.assertFalse(restored.config.episodic_memory.enabled)
        self.assertFalse(restored._memory._fts_sync_active)
        self.assertEqual(len(restored._memory.cards), 1)

        restored.config.episodic_memory.enabled = True
        restored_team = next(iter(restored.teams.values()))
        restored_agent = restored._agents_by_id[self.agent.agent_id]
        self.assertIn(
            "search_memories",
            restored.get_available_tools(restored_team, restored_agent),
        )
        await restored.flush_state()
        agent_token = restored._active_tool_agent.set(restored_agent)
        team_token = restored._active_team.set(restored_team)
        try:
            search_result = await restored._memory.search(query="completed")
        finally:
            restored._active_team.reset(team_token)
            restored._active_tool_agent.reset(agent_token)
        self.assertEqual(len(search_result.items), 1)
        with closing(sqlite3.connect(db_path)) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM agent_memory_cards_fts"
                ).fetchone()[0],
                1,
            )
        await restored.close()


