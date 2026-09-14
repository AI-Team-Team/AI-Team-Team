import asyncio
import json
import os
import shutil
import sqlite3
import tempfile
import time
import unittest
from contextlib import closing
from unittest.mock import patch

from ai_team_team import (
    ATTConfig,
    ATTManager,
    Agent,
    AgentMemorySegment,
    AgentTurnStatus,
    MemoryCardStatus,
    MemoryIndexStatus,
    ToolResultStatus,
)
from ai_team_team.core.tool_runtime import ToolExecutor
from ai_team_team.core.memory.sanitization import content_digest

from test.test_att.test_episodic_memory._support import (
    EpisodicMemoryTestCase,
    ScriptedMemoryClient,
)




class TestOptionalMode(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.workspace = tempfile.mkdtemp(prefix="att-memory-optional-")
        self.addCleanup(shutil.rmtree, self.workspace, ignore_errors=True)

    async def test_disabled_by_default_and_runtime_tool_view_tracks_configuration(self):
        client = ScriptedMemoryClient()
        manager = ATTManager(
            Agent("Root", "Architect", client),
            ATTConfig(workspace_root=self.workspace),
        )
        manager.register_llm_client("model", client)
        team = manager.create_agent_team(manager.root_ai, member_count=3)
        agent = team.members[0]
        names = manager.get_available_tools(team, agent)
        self.assertNotIn("search_memories", names)
        await team.execute_reasoning_step_detailed(agent, "Work.", "System.", manager=manager)
        self.assertFalse(manager._memory.segments)

        manager.config.episodic_memory.enabled = True
        names = manager.get_available_tools(team, agent)
        self.assertIn("search_memories", names)
        manager.config.episodic_memory.enabled = False
        self.assertNotIn("search_memories", manager.get_available_tools(team, agent))
        agent_token = manager._active_tool_agent.set(agent)
        team_token = manager._active_team.set(team)
        try:
            with self.assertRaisesRegex(RuntimeError, "disabled"):
                await manager._memory.search()
        finally:
            manager._active_team.reset(team_token)
            manager._active_tool_agent.reset(agent_token)
        await manager.close()

    async def test_persisted_search_waits_for_the_latest_fts_delta(self):
        client = ScriptedMemoryClient()
        with tempfile.TemporaryDirectory(prefix="att-memory-search-durability-") as workspace:
            db_path = os.path.join(workspace, "search.db")
            manager = ATTManager(
                Agent("Root", "Architect", client),
                ATTConfig(
                    workspace_root=workspace,
                    episodic_memory={
                        "enabled": True,
                        "index_retry_backoff_factor": 0.0,
                    },
                ),
                db_path=db_path,
            )
            manager.register_llm_client("model", client)
            team = manager.create_agent_team(manager.root_ai, member_count=3)
            agent = team.members[0]
            await team.execute_reasoning_step_detailed(
                agent,
                "Remember the durable blue rocket.",
                "System.",
                manager=manager,
            )
            await manager.flush_memory_indexing()

            agent_token = manager._active_tool_agent.set(agent)
            team_token = manager._active_team.set(team)
            try:
                result = await manager._memory.search(query="completed")
            finally:
                manager._active_team.reset(team_token)
                manager._active_tool_agent.reset(agent_token)

            self.assertEqual(len(result.items), 1)
            await manager.close()

    async def test_disabled_mode_persists_journal_without_cards_or_fts(self):
        client = ScriptedMemoryClient()
        with tempfile.TemporaryDirectory(prefix="att-memory-disabled-") as workspace:
            db_path = os.path.join(workspace, "disabled.db")
            manager = ATTManager(
                Agent("Root", "Architect", client),
                ATTConfig(workspace_root=workspace),
            )
            manager.register_llm_client("model", client)
            team = manager.create_agent_team(manager.root_ai, member_count=3)
            await team.execute_reasoning_step_detailed(
                team.members[0],
                "Work without the optional catalog.",
                "System.",
                manager=manager,
            )
            await manager.save_state(db_path)
            await manager.close()

            with closing(sqlite3.connect(db_path)) as connection:
                self.assertGreater(
                    connection.execute(
                        "SELECT COUNT(*) FROM system_memory_events"
                    ).fetchone()[0],
                    0,
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM agent_memory_cards"
                    ).fetchone()[0],
                    0,
                )
                self.assertIsNone(
                    connection.execute(
                        "SELECT name FROM sqlite_master WHERE name='agent_memory_cards_fts'"
                    ).fetchone()
                )

    async def test_disabling_mode_during_indexing_does_not_publish_a_card(self):
        indexing_started = asyncio.Event()
        release_indexing = asyncio.Event()

        class BlockingIndexClient(ScriptedMemoryClient):
            async def generate(self, *args, require_json=False, **kwargs):
                if require_json:
                    indexing_started.set()
                    await release_indexing.wait()
                return await super().generate(
                    *args,
                    require_json=require_json,
                    **kwargs,
                )

        client = BlockingIndexClient()
        manager = ATTManager(
            Agent("Root", "Architect", client),
            ATTConfig(
                workspace_root=self.workspace,
                episodic_memory={"enabled": True},
            ),
        )
        manager.register_llm_client("model", client)
        team = manager.create_agent_team(manager.root_ai, member_count=3)
        await team.execute_reasoning_step_detailed(
            team.members[0],
            "Create a pending memory.",
            "System.",
            manager=manager,
        )
        await indexing_started.wait()
        manager.config.episodic_memory.enabled = False
        release_indexing.set()
        await asyncio.wait_for(manager._memory._queue.join(), timeout=1.0)
        self.assertFalse(manager._memory.cards)
        self.assertTrue(
            all(
                segment.status is MemoryIndexStatus.PENDING
                for segment in manager._memory.segments.values()
            )
        )
        manager.config.episodic_memory.enabled = True
        manager.get_available_tools(team, team.members[0])
        self.assertIsNotNone(manager._memory._queue)
        await asyncio.wait_for(manager._memory._queue.join(), timeout=1.0)
        self.assertEqual(len(manager._memory.cards), 1)
        await manager.close()

