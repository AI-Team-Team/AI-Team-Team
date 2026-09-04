import asyncio
import multiprocessing
import os
import shutil
import sqlite3
import tempfile
import threading
import time
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import AsyncMock, patch

from ai_team_team import (
    AmbiguousTeamContextError,
    ATTConfig,
    ATTException,
    ATTManager,
    Agent,
    AuditResult,
    AuditStatus,
    DatabaseOwnershipError,
    LLMGenerationError,
    StateRestoreError,
)
from ai_team_team.core.utils import generate_with_retry
from ai_team_team.database.persistence import (
    DatabaseStore,
    PersistenceCoordinator,
)
from ai_team_team.tool import get_default_tools


class EchoClient:
    async def generate(self, prompt, system_instruction=None, **kwargs):
        return "Final Answer: complete"


def _write_and_hold(db_path, workspace, ready, release):
    import warnings

    warnings.filterwarnings("ignore", category=ResourceWarning)

    async def run():
        client = EchoClient()
        manager = ATTManager(
            Agent("ProcessRoot", "Architect", client),
            ATTConfig(workspace_root=workspace),
            db_path=db_path,
        )
        manager.register_llm_client("process-model", client)
        team = manager.create_agent_team(manager.root_ai)
        await manager.save_state()
        ready.put(team.team_id)
        release.wait(10)

    asyncio.run(run())

class TestHighHardening(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="att_high_")
        self.client = EchoClient()

    async def asyncTearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    async def test_shared_agent_context_memory_and_serial_calls(self):
        class SerialClient:
            def __init__(self):
                self.active = 0
                self.maximum = 0
                self.system_prompts = []

            async def generate(self, prompt, system_instruction=None, **kwargs):
                self.active += 1
                self.maximum = max(self.maximum, self.active)
                self.system_prompts.append(system_instruction or "")
                await asyncio.sleep(0.03)
                self.active -= 1
                return "Final Answer: shared"

        client = SerialClient()
        root = Agent("Root", "Architect", client)
        shared = Agent("Shared", "Analyst", client)
        manager = ATTManager(root, ATTConfig(workspace_root=self.tmpdir))
        manager.register_llm_client("shared-model", client)
        manager.register_agent(shared)
        configs_a = {
            "HelperA": {"model": "shared-model"},
            "HelperB": {"model": "shared-model"},
        }
        configs_b = {
            "HelperC": {"model": "shared-model"},
            "HelperD": {"model": "shared-model"},
        }
        team_a = manager.create_agent_team(
            root,
            member_configs=configs_a,
            existing_members=[shared],
        )
        team_b = manager.create_agent_team(
            root,
            member_configs=configs_b,
            existing_member_ids=[shared.agent_id],
        )
        self.assertIs(next(member for member in team_a.members if member is shared), shared)
        self.assertIs(next(member for member in team_b.members if member is shared), shared)
        self.assertEqual(shared.role, "Analyst")

        with self.assertRaises(AmbiguousTeamContextError):
            manager.get_agent_team(shared)

        team_token = manager._active_team.set(team_a)
        try:
            child = shared.launch_att(manager)
        finally:
            manager._active_team.reset(team_token)
        self.assertIs(child.parent_team, team_a)

        await asyncio.gather(
            team_a.execute_reasoning_step(shared, "A", "system", manager=manager),
            team_b.execute_reasoning_step(shared, "B", "system", manager=manager),
        )
        self.assertEqual(client.maximum, 1)
        self.assertTrue(any(team_a.team_id in text for text in client.system_prompts))
        self.assertTrue(any(team_b.team_id in text for text in client.system_prompts))
        generated = [
            message
            for message in shared.message_history
            if message.get("team_id") in {team_a.team_id, team_b.team_id}
        ]
        self.assertEqual(
            {message["team_id"] for message in generated},
            {team_a.team_id, team_b.team_id},
        )
        self.assertTrue(all(message.get("discussion_id") for message in generated))

        tools = get_default_tools({"att_manager": manager}, shared)
        token = manager._active_team.set(team_b)
        try:
            await tools["update_team_purpose"]("Scoped to B")
        finally:
            manager._active_team.reset(token)
        self.assertEqual(team_b.team_purpose, "Scoped to B")
        self.assertNotEqual(team_a.team_purpose, "Scoped to B")
        with self.assertRaises(AmbiguousTeamContextError):
            await tools["update_team_purpose"]("Ambiguous")
        db_path = os.path.join(self.tmpdir, "shared-history.db")
        await manager.save_state(db_path)
        await manager.close()
        restored = ATTManager(
            Agent("Root", "Architect", client),
            ATTConfig(workspace_root=self.tmpdir),
        )
        restored.register_llm_client("shared-model", client)
        await restored.load_state(db_path)
        restored_history = restored.agents[shared.name].message_history
        self.assertEqual(len(restored_history), len(shared.message_history))
        self.assertTrue(
            all(message.get("team_id") for message in restored_history)
        )
        await restored.close()
    async def test_callbacks_are_ordered_nonblocking_and_isolated(self):
        manager = ATTManager(
            Agent("Root", "Architect", self.client),
            ATTConfig(workspace_root=self.tmpdir),
        )
        gate = threading.Event()
        started = threading.Event()
        observed = []

        def callback(event, details):
            observed.append(event)
            if event == "slow":
                started.set()
                gate.wait(5)
            if event == "broken":
                raise RuntimeError("observer failure")

        manager.on_system_event = callback
        before = time.monotonic()
        manager._emit_callback("on_system_event", "slow", {})
        self.assertLess(time.monotonic() - before, 0.05)
        await asyncio.to_thread(started.wait, 5)
        manager._emit_callback("on_system_event", "broken", {})
        manager._emit_callback("on_system_event", "last", {})
        gate.set()
        await manager.flush_callbacks()
        self.assertEqual(observed, ["slow", "broken", "last"])

        async_seen = []

        async def async_callback(event, details):
            async_seen.append(event)

        manager.on_system_event = async_callback
        manager._emit_callback("on_system_event", "async", {})
        await manager.flush_callbacks()
        self.assertEqual(async_seen, ["async"])
        await manager.close()
    async def test_retry_types_and_zero_retry_semantics(self):
        class Flaky:
            def __init__(self, error):
                self.calls = 0
                self.error = error

            async def generate(self, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    raise self.error
                return "ok"

        transient = Flaky(ConnectionError("offline"))
        self.assertEqual(
            await generate_with_retry(transient, "prompt", retries=1, backoff_factor=0),
            "ok",
        )
        permanent = Flaky(ValueError("invalid request"))
        with self.assertRaises(LLMGenerationError):
            await generate_with_retry(permanent, "prompt", retries=5)
        self.assertEqual(permanent.calls, 1)
        no_retry = Flaky(ConnectionError("offline"))
        with self.assertRaises(LLMGenerationError):
            await generate_with_retry(no_retry, "prompt", retries=0)
        self.assertEqual(no_retry.calls, 1)
    async def test_hard_token_budget_rejects_client_without_cap_api(self):
        class NoCapClient:
            async def generate(
                self,
                prompt,
                system_instruction=None,
                temperature=0.3,
                require_json=False,
            ):
                return {"text": "ok", "usage": {"total_tokens": 3}}

        client = NoCapClient()
        manager = ATTManager(
            Agent("Root", "Architect", client),
            ATTConfig(
                workspace_root=self.tmpdir,
                model_token_limits={"default": 10},
                model_max_output_tokens={"default": 6},
            ),
        )
        with self.assertRaisesRegex(
            LLMGenerationError, "max_output_tokens or max_tokens"
        ):
            await generate_with_retry(client, "12345678", manager=manager)
        self.assertEqual(manager.token_budget.available("default"), 10)
        self.assertNotIn("default", manager.model_token_usage)
        await manager.close()
    async def test_hanging_llm_does_not_block_close(self):
        started = asyncio.Event()

        class HangingClient:
            async def generate(self, **kwargs):
                started.set()
                await asyncio.Event().wait()

        client = HangingClient()
        manager = ATTManager(
            Agent("Root", "Architect", client),
            ATTConfig(workspace_root=self.tmpdir),
        )
        team = manager.create_agent_team(manager.root_ai)
        task = asyncio.create_task(
            manager.execute_team_discussion(
                team, "hang", rounds=1, skip_audit=True
            )
        )
        await started.wait()
        await asyncio.wait_for(manager.close(), timeout=0.5)
        with self.assertRaises(asyncio.CancelledError):
            await task


if __name__ == "__main__":
    unittest.main()
