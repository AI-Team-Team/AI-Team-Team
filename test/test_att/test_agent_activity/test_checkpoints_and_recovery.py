"""Real SQLite receipts, complete provider windows, and post-publication replay limits."""

import asyncio
import sqlite3
from contextlib import closing

from ai_team_team import ATTConfig, ATTManager, Agent, LLMResponse
from ai_team_team.core.activity.contracts import AgentTeamScope
from test.test_att.test_autonomous_activity_phase0._fixtures import (
    AsyncBarrier,
    ModelStep,
    ScriptedModelClient,
)

from ._support import ActivityTestCase, call, idle


class CheckpointAndRecoveryTests(ActivityTestCase):
    async def durable(self):
        await self.manager.close()
        self.manager = self.make_manager(self.root, durable=True)

    async def test_host_scope_replaces_an_earlier_control_scope_in_the_restored_checkpoint(self):
        await self.durable()
        first, second = [
            self.manager.bootstrap_agent_team(
                self.root,
                existing_members=[self.root],
                member_configs={
                    f"{prefix}Peer1": {"model": "fixture"},
                    f"{prefix}Peer2": {"model": "fixture"},
                },
            )
            for prefix in ("First", "Second")
        ]
        self.steps(
            call(
                "set_operation_scope", {"scope": {"kind": "agent_team", "team_id": first.team_id}}
            ),
            idle(),
            idle(),
        )
        original = await self.manager.activate_agent(self.root.agent_id)
        await self.wait(original)
        explicit = await self.manager.activate_agent(
            self.root.agent_id, scope=AgentTeamScope(team_id=second.team_id)
        )
        await self.wait(explicit)
        await self.manager.save_state()
        path, owner = self.manager.db_path, self.root.agent_id
        await self.manager.close()
        restored = ATTManager(
            Agent("HostRoot", "Architect", self.client),
            ATTConfig(workspace_root=self.workspace.name),
            persistence_mode="volatile",
        )
        restored.register_llm_client("fixture", self.client)
        self.addAsyncCleanup(restored.close)
        await restored.load_state(path)
        self.assertEqual(
            restored.inspect_agent_activity(owner).scope,
            AgentTeamScope(team_id=second.team_id),
        )
        self.assertEqual(
            restored.root_ai.last_context["activity_scope"],
            {"kind": "agent_team", "team_id": second.team_id},
        )

    async def test_every_dispatched_frame_has_its_exact_personal_window_and_journal(self):
        await self.durable()
        barrier = AsyncBarrier()
        self.client.steps.extend(
            (
                ModelStep(LLMResponse(text="COMMITTED_FIRST_PERSONAL_ANSWER")),
                ModelStep(idle(), barrier),
            )
        )
        admitted = await self.manager.activate_agent(self.root.agent_id)
        await asyncio.wait_for(barrier.wait_entered(), 10)
        with closing(sqlite3.connect(self.manager.db_path)) as database:
            messages = database.execute(
                "SELECT content FROM agent_messages WHERE agent_id=?", (self.root.agent_id,)
            ).fetchall()
            self.assertIn("COMMITTED_FIRST_PERSONAL_ANSWER", str(messages))
            self.assertEqual(
                database.execute("SELECT COUNT(*) FROM notification_frames").fetchone()[0], 2
            )
            self.assertEqual(
                database.execute("SELECT COUNT(*) FROM model_token_claims").fetchone()[0], 2
            )
            self.assertEqual(database.execute("PRAGMA foreign_key_check").fetchall(), [])
        barrier.release()
        await self.wait(admitted)
        await self.manager.save_state()
        state = await self.manager._persistence.read(self.manager.db_path)
        self.manager._validate_state_snapshot(state)
        self.assertIn("COMMITTED_FIRST_PERSONAL_ANSWER", str(state["agents"][0]["messages"]))

    async def test_an_open_native_batch_is_evidence_not_an_invalid_saved_window(self):
        await self.durable()
        wait = AsyncBarrier()

        async def wait_tool() -> str:
            await wait.pause()
            return "tool outcome"

        self.manager.register_tool("wait_tool", func=wait_tool)
        self.steps(call("wait_tool"), idle())
        admitted = await self.manager.activate_agent(self.root.agent_id)
        await asyncio.wait_for(wait.wait_entered(), 10)
        await self.manager.save_state()
        state = await self.manager._persistence.read(self.manager.db_path)
        self.manager._validate_state_snapshot(state)
        window = state["agents"][0]["messages"]
        self.assertFalse(any(message.get("tool_calls") for message in window))
        self.assertEqual(len(self.records("executions")), 1)
        self.assertEqual(self.records("executions")[0].values["status"], "running")
        self.assertTrue(any(event.invocation_id for event in self.manager._memory.events.values()))
        wait.release()
        await self.wait(admitted)
        await self.manager.save_state()
        state = await self.manager._persistence.read(self.manager.db_path)
        window = state["agents"][0]["messages"]
        self.assertEqual(sum(message.get("tool_call_id") == "call" for message in window), 1)

    async def test_sleep_export_samples_remainder_and_restore_does_not_spend_offline_time(self):
        await self.durable()
        self.manager.register_runtime_clock(self.clock)
        self.steps(
            call("set_activity_intent", {"intent": {"kind": "sleep", "countdown": {"minutes": 5}}})
        )
        admitted = await self.manager.activate_agent(self.root.agent_id)
        await self.wait(admitted, "sleep")
        self.clock.advance(60)
        await self.manager.save_state()
        path = self.manager.db_path
        owner = self.root.agent_id
        await self.manager.close()
        new_clock = self.clock.restarted(offline_seconds=3600)
        self.addCleanup(new_clock.close)
        client = ScriptedModelClient(ModelStep(idle()))
        restored = ATTManager(
            Agent("HostRoot", "Architect", client),
            ATTConfig(workspace_root=self.workspace.name, tool_calling_mode="native"),
            persistence_mode="volatile",
        )
        restored.register_llm_client("fixture", client)
        restored.register_runtime_clock(new_clock)
        self.addAsyncCleanup(restored.close)
        await restored.load_state(path)
        self.assertFalse(client.requests)
        self.assertEqual(restored.inspect_agent_activity(owner).intent, "sleep")
        new_clock.advance(239)
        self.assertFalse(client.requests)
        new_clock.advance(1)
        async with asyncio.timeout(10):
            while not client.requests:
                await asyncio.sleep(0)
        activity = restored.inspect_agent_activity(owner)
        await asyncio.wait_for(
            restored.wait_for_activity_checkpoint(activity.admission_id, intent="idle"), 10
        )
        self.assertEqual(len(client.requests), 1)

    async def test_restore_rejects_live_personal_admission_without_changing_files(self):
        await self.durable()
        await self.manager.save_state()
        gate = AsyncBarrier()
        self.client.steps.append(ModelStep(idle(), gate))
        admitted = await self.manager.activate_agent(self.root.agent_id)
        await asyncio.wait_for(gate.wait_entered(), 10)
        from ai_team_team import StateRestoreError

        with self.assertRaises(StateRestoreError):
            await self.manager.load_state(self.manager.db_path)
        self.assertIs(self.manager.root_ai, self.root)
        gate.release()
        await self.wait(admitted)

    async def test_cancelled_source_observer_does_not_discard_a_committed_mail(self):
        await self.durable()
        gate = AsyncBarrier()
        self.client.steps.append(ModelStep(idle(), gate))
        source = asyncio.create_task(
            self.manager.deliver_agent_mail(self.root.agent_id, message_type="note", payload={})
        )
        # Observe the concrete commit before cancelling only the caller.
        async with asyncio.timeout(10):
            while not self.records("agent_notifications"):
                await asyncio.sleep(0)
        source.cancel()
        try:
            await source
        except asyncio.CancelledError:
            pass
        await asyncio.wait_for(gate.wait_entered(), 10)
        gate.release()
        current = self.manager.inspect_agent_activity(self.root.agent_id)
        await asyncio.wait_for(
            self.manager.wait_for_activity_checkpoint(current.admission_id, intent="idle"), 10
        )
        self.assertEqual(len(self.root.agent_inbox), 1)
        self.assertEqual(len(self.records("agent_notifications")), 1)
