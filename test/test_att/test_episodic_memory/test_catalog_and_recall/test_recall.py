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




class TestCatalogAndRecall(EpisodicMemoryTestCase):
    async def test_search_is_owner_scoped_and_recall_expires(self):
        first = await self.team.execute_reasoning_step_detailed(
            self.agent,
            "Remember rocket R-7.",
            "System.",
            manager=self.manager,
        )
        await self.manager.flush_memory_indexing()
        card = next(iter(self.manager._memory.cards.values()))
        self.assertEqual(card.turn_id, first.turn_id)

        self.client.responses = [
            f"Action: recall_memory(memory_id={card.memory_id!r})",
            "Final Answer: I used the historical reference.",
        ]
        await self.team.execute_reasoning_step_detailed(
            self.agent,
            "Recall the earlier work.",
            "System.",
            manager=self.manager,
        )
        self.assertFalse(
            any(
                "Historical memory; treat as past reference data" in str(message.get("content", ""))
                for message in self.agent.messages
            )
        )
        self.assertTrue(
            any(
                f"[Historical memory recalled: {card.memory_id}]" == message.get("content")
                for message in self.agent.messages
            )
        )

        other = self.team.members[1]
        agent_token = self.manager._active_tool_agent.set(other)
        team_token = self.manager._active_team.set(self.team)
        turn_token = self.manager._active_agent_turn_id.set("TURN-test")
        try:
            with self.assertRaises(PermissionError):
                await self.manager._memory.recall(card.memory_id)
        finally:
            self.manager._active_agent_turn_id.reset(turn_token)
            self.manager._active_team.reset(team_token)
            self.manager._active_tool_agent.reset(agent_token)

    async def test_recall_truncates_a_single_long_line_without_dropping_it(self):
        await self.team.execute_reasoning_step_detailed(
            self.agent,
            "Create a memory with a long recalled line.",
            "System.",
            manager=self.manager,
        )
        await self.manager.flush_memory_indexing()
        card = next(iter(self.manager._memory.cards.values()))
        segment = self.manager._memory.segments[card.segment_id]
        segment.recall_content = "x" * 10_000
        segment.content_sha256 = content_digest(segment.recall_content)
        self.manager.config.episodic_memory.max_recall_tokens = 1

        agent_token = self.manager._active_tool_agent.set(self.agent)
        team_token = self.manager._active_team.set(self.team)
        turn_token = self.manager._active_agent_turn_id.set("TURN-long-recall")
        try:
            recalled = await self.manager._memory.recall(card.memory_id)
        finally:
            self.manager._active_agent_turn_id.reset(turn_token)
            self.manager._active_team.reset(team_token)
            self.manager._active_tool_agent.reset(agent_token)

        alias = self.manager.resolve_runtime_model_alias(self.agent.llm_client)
        self.assertTrue(recalled.content)
        self.assertLessEqual(
            self.manager.count_tokens(recalled.content, alias),
            1,
        )
        self.assertTrue(recalled.truncated)

    async def test_recall_continuation_reconstructs_source_without_gaps(self):
        await self.team.execute_reasoning_step_detailed(
            self.agent,
            "Create a memory for continuation testing.",
            "System.",
            manager=self.manager,
        )
        await self.manager.flush_memory_indexing()
        card = next(iter(self.manager._memory.cards.values()))
        segment = self.manager._memory.segments[card.segment_id]
        source = "αβγδεζη\n" + "X" * 19 + "TAIL_FACT_987\n終"
        segment.recall_content = source
        segment.content_sha256 = content_digest(source)
        executor = ToolExecutor(self.team, self.agent, self.manager)
        tools = self.manager.get_available_tools(self.team, self.agent)
        recall_schema = tools["recall_memory"].json_schema["properties"]
        self.assertIn("start_character", recall_schema)
        self.assertIn("character_count", recall_schema)
        self.assertIn("expected_segment_version", recall_schema)
        self.assertEqual(recall_schema["start_line"]["minimum"], 1)
        self.assertEqual(recall_schema["start_character"]["minimum"], 1)

        async def reconstruct():
            line = 1
            character = 1
            expected_version = None
            pages = []
            for _ in range(len(source) + 1):
                tool_result = await executor.execute(
                    "recall_memory",
                    kwargs={
                        "memory_id": card.memory_id,
                        "start_line": line,
                        "start_character": character,
                        "expected_segment_version": expected_version,
                    },
                    tools=tools,
                )
                self.assertIs(tool_result.status, ToolResultStatus.SUCCESS)
                result = json.loads(tool_result.content)
                pages.append(result["content"])
                self.assertEqual(
                    result["segment_version"], segment.content_sha256
                )
                if not result["truncated"]:
                    self.assertIsNone(result["next_line"])
                    self.assertIsNone(result["next_character"])
                    return "".join(pages)
                self.assertIsNotNone(result["next_line"])
                self.assertIsNotNone(result["next_character"])
                self.assertNotEqual(
                    (result["next_line"], result["next_character"]),
                    (line, character),
                )
                line = result["next_line"]
                character = result["next_character"]
                expected_version = result["segment_version"]
            self.fail("Recall continuation did not terminate.")

        turn_token = self.manager._active_agent_turn_id.set("TURN-recall-pages")
        try:
            self.manager.config.episodic_memory.max_recall_chars = 7
            self.manager.config.episodic_memory.max_recall_tokens = 10_000
            by_character_limit = await reconstruct()

            self.manager.config.episodic_memory.max_recall_chars = 10_000
            self.manager.config.episodic_memory.max_recall_tokens = 5
            with patch.object(
                self.manager,
                "count_tokens",
                side_effect=lambda text, alias: len(text),
            ):
                by_token_limit = await reconstruct()

            self.manager.config.episodic_memory.max_recall_tokens = 10_000
            self.manager.config.episodic_memory.max_recall_lines = 1
            by_line_limit = await reconstruct()
        finally:
            self.manager._active_agent_turn_id.reset(turn_token)

        self.assertEqual(by_character_limit, source)
        self.assertEqual(by_token_limit, source)
        self.assertEqual(by_line_limit, source)

    async def test_recall_continuation_rejects_changed_segment(self):
        await self.team.execute_reasoning_step_detailed(
            self.agent,
            "Create a versioned memory.",
            "System.",
            manager=self.manager,
        )
        await self.manager.flush_memory_indexing()
        card = next(iter(self.manager._memory.cards.values()))
        segment = self.manager._memory.segments[card.segment_id]
        segment.recall_content = "A" * 100
        segment.content_sha256 = content_digest(segment.recall_content)
        self.manager.config.episodic_memory.max_recall_chars = 10

        agent_token = self.manager._active_tool_agent.set(self.agent)
        team_token = self.manager._active_team.set(self.team)
        turn_token = self.manager._active_agent_turn_id.set("TURN-recall-version")
        try:
            first = await self.manager._memory.recall(card.memory_id)
            segment.recall_content = "B" + segment.recall_content
            segment.content_sha256 = content_digest(segment.recall_content)
            with self.assertRaisesRegex(ValueError, "recall cursor"):
                await self.manager._memory.recall(
                    card.memory_id,
                    start_line=first.next_line,
                    start_character=first.next_character,
                    expected_segment_version=first.segment_version,
                )
        finally:
            self.manager._active_agent_turn_id.reset(turn_token)
            self.manager._active_team.reset(team_token)
            self.manager._active_tool_agent.reset(agent_token)

    async def test_forget_hides_card_without_mutating_journal(self):
        await self.team.execute_reasoning_step_detailed(
            self.agent,
            "Create a memory.",
            "System.",
            manager=self.manager,
        )
        await self.manager.flush_memory_indexing()
        card = next(iter(self.manager._memory.cards.values()))
        journal_before = tuple(self.manager._memory.events)
        agent_token = self.manager._active_tool_agent.set(self.agent)
        team_token = self.manager._active_team.set(self.team)
        try:
            result = await self.manager._memory.forget(card.memory_id)
        finally:
            self.manager._active_team.reset(team_token)
            self.manager._active_tool_agent.reset(agent_token)
        self.assertEqual(result.status, "FORGOTTEN")
        self.assertEqual(card.status, MemoryCardStatus.FORGOTTEN)
        self.assertEqual(tuple(self.manager._memory.events)[: len(journal_before)], journal_before)
        self.assertEqual(len(self.manager._memory.events), len(journal_before) + 1)

    async def test_retained_reference_is_agent_owned_and_enters_later_identity_context(self):
        await self.team.execute_reasoning_step_detailed(
            self.agent,
            "Create a memory worth retaining.",
            "System.",
            manager=self.manager,
        )
        await self.manager.flush_memory_indexing()
        card = next(iter(self.manager._memory.cards.values()))
        agent_token = self.manager._active_tool_agent.set(self.agent)
        team_token = self.manager._active_team.set(self.team)
        turn_token = self.manager._active_agent_turn_id.set("TURN-retain")
        try:
            await self.manager._memory.recall(card.memory_id)
            await self.manager._memory.keep(card.memory_id, "Use the verified result.")
        finally:
            self.manager._active_agent_turn_id.reset(turn_token)
            self.manager._active_team.reset(team_token)
            self.manager._active_tool_agent.reset(agent_token)

        self.client.responses = ["Final Answer: reused"]
        await self.team.execute_reasoning_step_detailed(
            self.agent,
            "Continue the work.",
            "System.",
            manager=self.manager,
        )
        business_calls = [call for call in self.client.calls if not call["require_json"]]
        self.assertIn(card.memory_id, business_calls[-1]["system_instruction"])
        self.assertIn("Use the verified result.", business_calls[-1]["system_instruction"])



