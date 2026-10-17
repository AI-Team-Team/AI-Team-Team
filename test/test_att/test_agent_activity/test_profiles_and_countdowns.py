"""Trusted scoped maintenance/audit requests and downtime-excluded timers."""

import asyncio

from ai_team_team import ATTConfig, ATTManager, Agent, LLMResponse
from test.test_att.test_autonomous_activity_phase0._fixtures import ModelStep, ScriptedModelClient

from ._support import ActivityTestCase, call, idle


class ProfileAndCountdownTests(ActivityTestCase):
    async def test_audits_retain_scoped_requests_without_an_ordinary_personal_admission(self):
        class Healthy:
            async def generate(inner, prompt, require_json=False, tools=None, **kwargs):
                if require_json:
                    return LLMResponse(
                        text='{"is_healthy": true, "reason": "Healthy fixture."}',
                        usage={"total_tokens": 9},
                    )
                response = (
                    idle()
                    if tools and any(tool.name == "set_activity_intent" for tool in tools)
                    else LLMResponse(text="Final Answer: Coherent audit evidence.")
                )
                response.usage = {"total_tokens": 9}
                return response

        await self.manager.close()
        client = Healthy()
        self.root = Agent("ProfileRoot", "Architect", client)
        self.manager = ATTManager(
            self.root,
            ATTConfig(
                workspace_root=self.workspace.name,
                tool_calling_mode="native",
                model_token_limits={"default": 1_000_000},
            ),
            persistence_mode="volatile",
        )
        self.manager.register_llm_client("default", client)
        self.addAsyncCleanup(self.manager.close)
        team = self.manager.create_agent_team(self.root)
        before = set(self.manager._agents_by_id)
        result = await self.manager.supervisor.audit_team_dialog(team, "Small audit fixture.")
        self.assertEqual(result.status.value, "healthy")
        self.assertEqual(set(self.manager._agents_by_id), before)
        self.assertFalse(self.records("activity_admissions"))
        self.assertEqual(len(self.records("audit_model_requests")), 7)
        self.assertEqual(len(self.records("audit_participants")), 3)
        self.assertEqual(self.records("audit_runs")[0].values["status"], "completed")
        self.assertTrue(
            all(
                row.values["scoped_agent_id"] not in before
                for row in self.records("audit_model_requests")
            )
        )
        self.assertTrue(
            all(
                row.values["audit_request_id"] is not None
                for row in self.records("model_token_claims")
            )
        )
        self.assertEqual(self.manager.token_budget.available("default"), 1_000_000 - 7 * 9)
        admitted = await self.manager.activate_agent(self.root.agent_id)
        await self.wait(admitted)
        self.assertEqual(self.manager.token_budget.available("default"), 1_000_000 - 8 * 9)
        self.assertEqual(len(self.records("model_requests")), 1)

    async def test_excluded_cooldown_restores_its_remainder_not_elapsed_offline_time(self):
        await self.manager.close()
        self.manager = self.make_manager(
            self.root,
            durable=True,
            config=ATTConfig(
                workspace_root=self.workspace.name,
                tool_calling_mode="native",
                activity={"cooldown_downtime": "exclude"},
            ),
        )
        self.manager.register_runtime_clock(self.clock)
        attempts = 0

        async def faulty() -> str:
            nonlocal attempts
            attempts += 1
            raise RuntimeError("Synthetic execution fault")

        self.manager.register_tool("faulty", func=faulty)
        self.steps(call("faulty"), idle())
        admitted = await self.manager.activate_agent(self.root.agent_id)
        await self.wait(admitted)
        self.clock.advance(60)
        await self.manager.save_state()
        path = self.manager.db_path
        row = self.records("tool_cooldowns")[0]
        self.assertEqual(row.values["remaining_seconds"], 540)
        await self.manager.close()
        clock = self.clock.restarted(offline_seconds=3600)
        self.addCleanup(clock.close)
        client = ScriptedModelClient(ModelStep(call("faulty")), ModelStep(idle()))
        restored = ATTManager(
            Agent("Host", "Architect", client),
            ATTConfig(workspace_root=self.workspace.name),
            persistence_mode="volatile",
        )
        restored.register_llm_client("fixture", client)
        restored.register_tool("faulty", func=faulty)
        restored.register_runtime_clock(clock)
        self.addAsyncCleanup(restored.close)
        await restored.load_state(path)
        row = restored._records.index[row.identity]
        self.assertEqual(restored._activity.cooldown_remaining(row), 540)
        clock.advance(10)
        self.assertEqual(restored._activity.cooldown_remaining(row), 530)
        admitted = await restored.activate_agent(self.root.agent_id)
        await asyncio.wait_for(
            restored.wait_for_activity_checkpoint(admitted.admission_id, intent="idle"), 10
        )
        self.assertEqual(
            attempts,
            1,
            "A cooling execution is not automatically replayed on restore or admission.",
        )
