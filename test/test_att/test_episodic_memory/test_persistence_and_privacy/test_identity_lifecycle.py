import os
import sqlite3
from copy import deepcopy
from contextlib import closing
from unittest.mock import patch

from ai_team_team import (
    ATTConfig,
    ATTManager,
    Agent,
    AgentTurnResult,
    AgentTurnStatus,
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
        await self.team.execute_reasoning_step_detailed(
            self.agent,
            "Create stable personal memory.",
            "System.",
            manager=self.manager,
        )
        await self.manager.flush_memory_indexing()
        before = self._agent_memory_snapshot(self.agent.agent_id)
        another = self.manager.bootstrap_agent_team(
            self.manager.root_ai,
            member_configs={
                "HelperOne": {"model": "memory-model"},
                "HelperTwo": {"model": "memory-model"},
            },
            existing_members=[self.agent],
        )
        self.assertIn(self.agent, another.members)
        another.members.remove(self.agent)
        self.assertEqual(self._agent_memory_snapshot(self.agent.agent_id), before)

    async def test_permanent_agent_delete_removes_derived_memory_but_retains_journal(self):
        doomed = Agent("Doomed", "Researcher", self.client)
        self.manager.register_agent(doomed)
        # This pure catalog fixture has no actual provider request. A separate
        # test verifies that retained request/quota evidence prevents deletion.
        turn_id = "standalone-delete-fixture"
        token = self.manager._active_agent_turn_id.set(turn_id)
        try:
            self.manager._memory.start_turn(doomed, None, turn_id)
            doomed.append_message({"role": "user", "content": "Create personal history before retirement."})
            doomed.append_message({"role": "assistant", "content": "Completed personal fixture work."})
            await self.manager._memory.finalize_turn(doomed, None, AgentTurnResult(
                agent_id=doomed.agent_id, turn_id=turn_id, status=AgentTurnStatus.COMPLETED,
                answer="Completed personal fixture work.",
            ))
        finally:
            self.manager._active_agent_turn_id.reset(token)
        async def derived_labels(agent, segment, prompt, system_instruction):
            import json
            return json.dumps(self.client.labels)
        with patch.object(self.manager._activity.models, "index", derived_labels):
            await self.manager.flush_memory_indexing()
        self.assertTrue(any(card.agent_id == doomed.agent_id for card in self.manager._memory.cards.values()))
        db_path = os.path.join(self.tmpdir, "delete.db")
        self.manager.db_path = db_path
        await self.manager.save_state()
        self.manager.config.episodic_memory.enabled = False

        await self.manager.retire_agent(
            doomed.agent_id,
            policy="delete",
            confirm_delete=True,
        )
        with closing(sqlite3.connect(db_path)) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM agents WHERE agent_id=?",
                    (doomed.agent_id,),
                ).fetchone()[0],
                0,
            )
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM agent_memory_cards WHERE agent_id=?",
                    (doomed.agent_id,),
                ).fetchone()[0],
                0,
            )
            self.assertIsNone(
                connection.execute(
                    "SELECT name FROM sqlite_master WHERE name='agent_memory_cards_fts'"
                ).fetchone()
            )
            self.assertGreater(
                connection.execute(
                    "SELECT COUNT(*) FROM system_memory_events WHERE agent_id=?",
                    (doomed.agent_id,),
                ).fetchone()[0],
                0,
            )
        self.assertTrue(self.manager.list_agent_history(doomed.agent_id))

    async def test_actual_index_request_evidence_prevents_physical_agent_deletion(self):
        owner = self.manager.register_agent(Agent("RetainedIndexerOwner", "Researcher", self.client))
        turn_id = "retained-index-request-fixture"
        self.manager._memory.start_turn(owner, None, turn_id)
        await self.manager._memory.finalize_turn(owner, None, AgentTurnResult(
            agent_id=owner.agent_id, turn_id=turn_id, status=AgentTurnStatus.COMPLETED, answer="Done."))
        await self.manager.flush_memory_indexing()
        requests = [row for row in self.manager._records.snapshot() if row.table_name == "memory_index_requests"
                    and row.values["beneficiary_agent_id"] == owner.agent_id]
        self.assertEqual(len(requests), 1)
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

