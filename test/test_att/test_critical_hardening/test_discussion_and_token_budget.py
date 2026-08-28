from test.test_att.test_critical_hardening._support import (
    ATTConfig,
    ATTManager,
    Agent,
    CriticalHardeningTestCase,
    HandlerClientAdapter,
    LLMResponse,
    StateRestoreError,
    TokenLimitExceededError,
    asyncio,
    closing,
    generate_with_retry,
    get_default_tools,
    os,
    parse_governance_decision,
    patch,
    sqlite3,
)
from ai_team_team.core.manager.discussions.cleanup import (
    finalize_discussion_session,
)


class TestCriticalHardening(CriticalHardeningTestCase):
    async def test_discussion_cleanup_always_releases_session_state(self):
        team = self.manager.create_agent_team(self.root)
        team.is_running = True
        discussion_token = self.manager._active_discussion_id.set(
            "DISC-cleanup"
        )

        class AutoSaveContext:
            exited = False

            async def __aexit__(self, exc_type, exc, tb):
                self.exited = True

        auto_save_context = AutoSaveContext()
        with patch.object(
            self.manager,
            "_finish_durable_alert_processing",
            side_effect=RuntimeError("cleanup failure"),
        ):
            with self.assertRaisesRegex(RuntimeError, "cleanup failure"):
                await finalize_discussion_session(
                    self.manager,
                    team,
                    set(),
                    set(),
                    {"operational-alert"},
                    False,
                    auto_save_context,
                    discussion_token,
                )

        self.assertTrue(auto_save_context.exited)
        self.assertFalse(team.is_running)
        self.assertIsNone(self.manager._active_discussion_id.get())

    async def test_discussions_serialize_per_team_but_not_across_teams(self):
        team_a = self.manager.create_agent_team(self.root)
        team_b = self.manager.create_agent_team(self.root)
        first_a_started = asyncio.Event()
        release_first_a = asyncio.Event()
        second_a_started = asyncio.Event()
        b_started = asyncio.Event()
        a_calls = 0

        async def fake_session(team, prompt, rounds=2, skip_audit=False):
            nonlocal a_calls
            if team is team_a:
                a_calls += 1
                if a_calls == 1:
                    first_a_started.set()
                    await release_first_a.wait()
                else:
                    second_a_started.set()
            else:
                b_started.set()
            return prompt

        self.manager._execute_team_discussion_session = fake_session
        first = asyncio.create_task(
            self.manager.execute_team_discussion(team_a, "ordinary")
        )
        await first_a_started.wait()
        emergency = asyncio.create_task(
            self.manager.execute_emergency_discussion(
                team_a, {"reason": "urgent"}, skip_audit=True
            )
        )
        other_team = asyncio.create_task(
            self.manager.execute_team_discussion(team_b, "parallel")
        )
        await asyncio.wait_for(b_started.wait(), timeout=1)
        await asyncio.sleep(0)
        self.assertFalse(second_a_started.is_set())

        release_first_a.set()
        await asyncio.wait_for(second_a_started.wait(), timeout=1)
        await asyncio.gather(first, emergency, other_team)

    async def test_token_budget_reservation_is_atomic_and_refunds_unused(self):
        started = asyncio.Event()
        release = asyncio.Event()

        class BlockingClient:
            def supports_output_token_limit(self):
                return "max_output_tokens"

            async def generate(self, prompt, max_output_tokens=None, **kwargs):
                started.set()
                await release.wait()
                return LLMResponse(
                    "ok",
                    usage={"input_tokens": 2, "output_tokens": 1},
                )

        manager = ATTManager(
            Agent("BudgetRoot", "Architect", BlockingClient()),
            ATTConfig(
                workspace_root=self.tmpdir,
                model_token_limits={"default": 10},
                model_max_output_tokens={"default": 6},
            ),
        )
        first = asyncio.create_task(
            generate_with_retry(
                manager.root_ai.llm_client,
                "12345678",
                manager=manager,
                retries=1,
            )
        )
        await started.wait()
        self.assertEqual(manager.token_budget.available("default"), 2)
        with self.assertRaises(TokenLimitExceededError):
            await generate_with_retry(
                manager.root_ai.llm_client,
                "12345678",
                manager=manager,
                retries=1,
            )
        release.set()
        await first
        self.assertEqual(manager.model_token_usage["default"], 3)
        self.assertEqual(manager.token_budget.available("default"), 7)
        await manager.close()

    async def test_cancelled_sent_request_charges_prompt_and_releases_output(self):
        started = asyncio.Event()

        class HangingClient:
            def supports_output_token_limit(self):
                return "max_output_tokens"

            async def generate(self, prompt, **kwargs):
                started.set()
                await asyncio.Event().wait()

        manager = ATTManager(
            Agent("CancelRoot", "Architect", HangingClient()),
            ATTConfig(
                workspace_root=self.tmpdir,
                model_token_limits={"default": 20},
                model_max_output_tokens={"default": 5},
            ),
        )
        task = asyncio.create_task(
            generate_with_retry(
                manager.root_ai.llm_client,
                "12345678",
                manager=manager,
                retries=1,
            )
        )
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(manager.model_token_usage["default"], 2)
        self.assertEqual(manager.token_budget.available("default"), 18)
        await manager.close()

    async def test_handler_max_tokens_cap_is_forwarded(self):
        observed = []

        async def handler(
            model_name,
            prompt,
            max_tokens,
            system_instruction=None,
            temperature=0.3,
            require_json=False,
        ):
            observed.append((model_name, max_tokens))
            return "ok"

        client = HandlerClientAdapter("bounded", handler)
        manager = ATTManager(
            Agent("HandlerRoot", "Architect", client),
            ATTConfig(
                workspace_root=self.tmpdir,
                model_token_limits={"bounded": 20},
                model_max_output_tokens={"bounded": 4},
            ),
        )
        manager.register_llm_client("bounded", client)
        await generate_with_retry(
            client, "12345678", manager=manager, retries=1
        )
        self.assertEqual(observed, [("bounded", 4)])
        await manager.close()
