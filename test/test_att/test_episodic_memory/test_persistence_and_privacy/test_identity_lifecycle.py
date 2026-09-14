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
        self.team.members.append(doomed)
        await self.team.execute_reasoning_step_detailed(
            doomed,
            "Create history before retirement.",
            "System.",
            manager=self.manager,
        )
        await self.manager.flush_memory_indexing()
        self.team.members.remove(doomed)
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

