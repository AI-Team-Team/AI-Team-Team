"""Invocation-scoped indexing through the continuing personal runtime."""

import asyncio
import json
import time
from unittest.mock import patch

from ai_team_team import Agent, AgentMemorySegment, InteractionStatus, MemoryIndexStatus
from ai_team_team.core.memory.sanitization import content_digest
from test.personal_activity import interact_and_idle

from .._support import EpisodicMemoryTestCase, ScriptedMemoryClient


class TestCatalogAndRecall(EpisodicMemoryTestCase):
    async def test_stale_indexer_cannot_publish_into_replaced_state(self):
        content = "Historical activity reference"
        now = time.time()
        segment = AgentMemorySegment(
            segment_id="SEG-stale", agent_id=self.agent.agent_id,
            invocation_id="INVOCATION-stale", origin_team_id=self.team.team_id,
            source_event_ids=["EVT-stale"], recall_content=content,
            content_sha256=content_digest(content), created_at=now, updated_at=now,
        )
        self.manager._memory.segments[segment.segment_id] = segment
        started, release = asyncio.Event(), asyncio.Event()

        async def labels(*args):
            started.set()
            await release.wait()
            return json.dumps(self.client.labels)

        with patch.object(self.manager._activity.models, "index", labels):
            task = asyncio.create_task(self.manager._memory._index_segment(segment.segment_id))
            await started.wait()
            self.assertEqual(segment.status, MemoryIndexStatus.PROCESSING)
            self.manager._memory.segments.pop(segment.segment_id)
            release.set()
            await task
        self.assertFalse(self.manager._memory.cards)
        self.assertFalse(any(event.payload.get("segment_id") == segment.segment_id
                             for event in self.manager._memory.events.values()))

    async def test_one_finished_invocation_creates_one_isolated_card(self):
        result = await interact_and_idle(self.manager, self.agent, "Complete the analysis.", team=self.team)
        await self.manager.flush_memory_indexing()
        self.assertEqual(result.status, InteractionStatus.COMPLETED)
        self.assertIsNotNone(result.invocation_id)
        self.assertEqual(len(self.manager._memory.segments), 1)
        self.assertEqual(len(self.manager._memory.cards), 1)
        card = next(iter(self.manager._memory.cards.values()))
        segment = next(iter(self.manager._memory.segments.values()))
        self.assertEqual(card.invocation_id, result.invocation_id)
        self.assertEqual(card.agent_id, self.agent.agent_id)
        self.assertEqual(card.origin_team_id, self.team.team_id)
        self.assertEqual(segment.status, MemoryIndexStatus.INDEXED)
        self.assertNotIn("isolated episodic-memory indexer", str(self.agent.messages).lower())

    async def test_background_indexer_does_not_inherit_business_invocation_context(self):
        observed = []
        manager = self.manager

        class ContextProbeClient(ScriptedMemoryClient):
            async def generate(self, *args, require_json=False, **kwargs):
                if require_json:
                    observed.append((manager._active_tool_agent.get(), manager._active_team.get(),
                                     manager._activity.current.get()))
                return await super().generate(*args, require_json=require_json, **kwargs)

        client = ContextProbeClient()
        self.manager.register_llm_client("context-probe", client)
        agent = self.manager.register_agent(Agent("ContextProbe", "Researcher", client))
        await interact_and_idle(self.manager, agent, "Create personal memory.")
        await self.manager.flush_memory_indexing()
        self.assertEqual(observed, [(None, None, None)])

    async def test_another_agent_registered_during_activity_cannot_enter_its_segment(self):
        manager = self.manager

        class RegistrationClient(ScriptedMemoryClient):
            async def generate(self, *args, require_json=False, **kwargs):
                if not require_json and not hasattr(self, "registered_agent"):
                    self.registered_agent = manager.register_agent(Agent("RegisteredDuringActivity", "Researcher", self))
                return await super().generate(*args, require_json=require_json, **kwargs)

        client = RegistrationClient()
        self.manager.register_llm_client("registration-client", client)
        actor = self.manager.register_agent(Agent("RegistrationActor", "Coordinator", client))
        result = await interact_and_idle(self.manager, actor, "Register another independent identity.")
        await self.manager.flush_memory_indexing()
        segment = next(item for item in self.manager._memory.segments.values()
                       if item.invocation_id == result.invocation_id)
        self.assertTrue(all(self.manager._memory.events[key].agent_id == actor.agent_id for key in segment.source_event_ids))
        event = next(event for event in self.manager._memory.events.values()
                     if event.event_type == "agent_registered" and event.agent_id == client.registered_agent.agent_id)
        self.assertIsNone(event.invocation_id)

    async def test_tool_error_can_be_remembered_but_interrupted_invocation_has_no_card(self):
        self.client.responses = ["Action: missing_tool(value=1)", "Final Answer: Corrected the attempt."]
        result = await interact_and_idle(self.manager, self.agent, "Use the tools carefully.", team=self.team)
        await self.manager.flush_memory_indexing()
        self.assertEqual(result.status, InteractionStatus.COMPLETED)
        self.assertEqual(len(self.manager._memory.cards), 1)
        self.assertTrue(any(message.get("tool_status") == "unknown_tool" for message in self.agent.messages))
        self.assertNotIn("missing_tool", next(iter(self.manager._memory.segments.values())).recall_content)
        started = asyncio.Event()

        class HangingClient(ScriptedMemoryClient):
            async def generate(self, *args, **kwargs):
                started.set()
                await asyncio.Event().wait()

        hanging = HangingClient()
        self.manager.register_llm_client("hanging", hanging)
        other = self.manager.register_agent(Agent("Interrupted", "Researcher", hanging))
        await self.manager.activate_agent(other.agent_id)
        await started.wait()
        worker = self.manager._activity.sessions[other.agent_id].worker
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
        self.assertFalse(any(item.agent_id == other.agent_id for item in self.manager._memory.segments.values()))
        self.assertTrue(any(row.table_name == "activity_invocations" and row.values["agent_id"] == other.agent_id
                            and row.values["interrupted"] == 1 for row in self.manager._records.snapshot()))

    async def test_label_failure_does_not_change_observed_business_answer(self):
        class FailingLabelClient(ScriptedMemoryClient):
            async def generate(self, *args, require_json=False, **kwargs):
                if require_json:
                    raise ValueError("invalid labels")
                return await super().generate(*args, **kwargs)

        client = FailingLabelClient(["Final Answer: business result"])
        self.manager.register_llm_client("failing-label", client)
        agent = self.manager.register_agent(Agent("LabelFailure", "Researcher", client))
        self.manager.config.episodic_memory.index_max_retries = 0
        result = await interact_and_idle(self.manager, agent, "Perform ordinary work.")
        await self.manager.flush_memory_indexing()
        segment = next(item for item in self.manager._memory.segments.values() if item.agent_id == agent.agent_id)
        self.assertEqual(result.answer, "business result")
        self.assertEqual(segment.status, MemoryIndexStatus.FAILED)
