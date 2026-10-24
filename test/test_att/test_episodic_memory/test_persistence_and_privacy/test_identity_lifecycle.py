from test.personal_activity import interact_and_idle
import os
import sqlite3
from copy import deepcopy
from contextlib import closing
from unittest.mock import patch

from ai_team_team import (
    ATTConfig,
    ATTManager,
    Agent,
    InteractionResult,
    InteractionStatus,
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
    async def test_membership_changes_do_not_touch_agent_memory(self):
        await interact_and_idle(self.manager, self.agent, "Create stable personal memory.", team=self.team)
        await self.manager.flush_memory_indexing()
        before = self._agent_memory_snapshot(self.agent.agent_id)
        another = self.manager.bootstrap_agent_team(
            self.manager.root_ai, parent=self.manager.root_ai,
            member_configs={
                "HelperOne": {"model": "memory-model"},
                "HelperTwo": {"model": "memory-model"},
            },
            existing_members=[self.agent],
        )
        self.assertIn(self.agent, another.members)
        another.members.remove(self.agent)
        self.assertEqual(self._agent_memory_snapshot(self.agent.agent_id), before)

    async def test_person_without_runtime_references_can_be_deleted_and_journal_is_retained(self):
        doomed = self.manager.register_agent(Agent("Doomed", "Researcher", self.client))
        db_path = os.path.join(self.tmpdir, "delete.db")
        self.manager.db_path = db_path
        await self.manager.save_state(db_path)
        await self.manager.retire_agent(doomed.agent_id, policy="delete", confirm_delete=True)
        with closing(sqlite3.connect(db_path)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM agents WHERE agent_id=?", (doomed.agent_id,)).fetchone()[0], 0)
            self.assertGreater(connection.execute("SELECT COUNT(*) FROM system_memory_events WHERE agent_id=?", (doomed.agent_id,)).fetchone()[0], 0)
        self.assertTrue(self.manager.list_agent_history(doomed.agent_id))

    async def test_actual_memory_and_request_evidence_prevents_physical_agent_deletion(self):
        owner = self.manager.register_agent(Agent("RetainedIndexerOwner", "Researcher", self.client))
        await interact_and_idle(self.manager, owner, "Preserve independent personal history.")
        await self.manager.flush_memory_indexing()
        requests = [row for row in self.manager._records.snapshot() if row.table_name == "memory_index_requests"
                    and row.values["beneficiary_agent_id"] == owner.agent_id]
        self.assertEqual(len(requests), 1)
        self.assertTrue(any(card.agent_id == owner.agent_id for card in self.manager._memory.cards.values()))
        with self.assertRaisesRegex(ValueError, "durable history references"):
            await self.manager.retire_agent(owner.agent_id, "delete", confirm_delete=True)
        await self.manager.retire_agent(owner.agent_id, "archive")
        self.assertEqual(owner.lifecycle_state, "archived")
        self.assertEqual([row for row in self.manager._records.snapshot() if row.table_name == "memory_index_requests"
                          and row.values["beneficiary_agent_id"] == owner.agent_id], requests)

    def _agent_memory_snapshot(self, agent_id):
        snapshot = self.manager._memory.snapshot()
        return {
            "memory_events": [
                item for item in snapshot["memory_events"] if item["agent_id"] == agent_id
            ],
            "memory_segments": [
                item for item in snapshot["memory_segments"] if item["agent_id"] == agent_id
            ],
            "memory_cards": [
                item for item in snapshot["memory_cards"] if item["agent_id"] == agent_id
            ],
            "memory_references": [
                item for item in snapshot["memory_references"] if item["agent_id"] == agent_id
            ],
        }

