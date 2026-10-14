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
from ai_team_team import Tool


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
        await self._assert_discussion_serialization()

    async def test_discussion_serialization_fixture_detects_a_bypassed_lock(self):
        with self.assertRaisesRegex(AssertionError, "True is not false"):
            await self._assert_discussion_serialization(bypass_session_lock=True)

    async def _assert_discussion_serialization(self, *, bypass_session_lock=False):
        team_a = self.manager.create_agent_team(self.root)
        team_b = self.manager.create_agent_team(self.root)
        first_a_started = asyncio.Event()
        release_first_a = asyncio.Event()
        second_a_attempted = asyncio.Event()
        second_a_started = asyncio.Event()
        b_started = asyncio.Event()
        execution_order = []
        a_calls = 0

        class ObservedSessionLock:
            def __init__(self, real_lock):
                self.real_lock = real_lock
                self.attempts = 0
                self.owners = {}

            async def __aenter__(self):
                self.attempts += 1
                attempt = self.attempts
                if attempt == 2:
                    execution_order.append("A2-attempt")
                    second_a_attempted.set()
                # No suspension between notifying the test and trying the real lock.
                if not bypass_session_lock:
                    await self.real_lock.acquire()
                self.owners[asyncio.current_task()] = attempt
                return self

            async def __aexit__(self, exc_type, exc, tb):
                attempt = self.owners.pop(asyncio.current_task())
                if not bypass_session_lock:
                    self.real_lock.release()
                execution_order.append(f"A{attempt}-released")

            def locked(self):
                return self.real_lock.locked()

        async def fake_session(team, prompt, rounds=2, skip_audit=False):
            nonlocal a_calls
            if team is team_a:
                a_calls += 1
                execution_order.append(f"A{a_calls}-start")
                if a_calls == 1:
                    first_a_started.set()
                    await release_first_a.wait()
                else:
                    second_a_started.set()
            else:
                execution_order.append("B-start")
                b_started.set()
            return prompt

        observed_lock = ObservedSessionLock(team_a.discussion_lock)
        tasks = []
        with (
            patch.object(team_a, "_discussion_lock", observed_lock),
            patch.object(self.manager, "_execute_team_discussion_session", fake_session),
        ):
            try:
                first = asyncio.create_task(
                    self.manager.execute_team_discussion(team_a, "ordinary")
                )
                tasks.append(first)
                await asyncio.wait_for(first_a_started.wait(), timeout=10)
                emergency = asyncio.create_task(
                    self.manager.execute_emergency_discussion(
                        team_a, {"reason": "urgent"}, skip_audit=True
                    )
                )
                other_team = asyncio.create_task(
                    self.manager.execute_team_discussion(team_b, "parallel")
                )
                tasks.extend((emergency, other_team))
                await asyncio.wait_for(second_a_attempted.wait(), timeout=10)
                await asyncio.wait_for(b_started.wait(), timeout=10)
                self.assertFalse(second_a_started.is_set(), execution_order)

                release_first_a.set()
                await asyncio.wait_for(asyncio.gather(first, emergency, other_team), timeout=10)
                self.assertLess(
                    execution_order.index("A1-start"), execution_order.index("B-start")
                )
                self.assertLess(
                    execution_order.index("B-start"), execution_order.index("A1-released")
                )
                self.assertLess(
                    execution_order.index("A1-released"), execution_order.index("A2-start")
                )
                self.assertEqual(a_calls, 2)
                self.assertFalse(observed_lock.locked())
                self.assertFalse(team_a.is_running)
                self.assertFalse(team_b.is_running)
            finally:
                release_first_a.set()
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True), timeout=10
                )

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
            persistence_mode="volatile",
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

    async def test_hard_budget_reserves_system_and_transmitted_tool_inputs(self):
        for component in ("system_instruction", "tools"):
            with self.subTest(component=component):
                calls = []

                class CountingClient:
                    def supports_output_token_limit(self):
                        return "max_output_tokens"

                    async def generate(
                        self,
                        prompt,
                        system_instruction=None,
                        tools=None,
                        max_output_tokens=None,
                        **kwargs,
                    ):
                        calls.append(
                            {
                                "system_instruction": system_instruction,
                                "tools": tools,
                            }
                        )
                        return LLMResponse("ok")

                client = CountingClient()
                manager = ATTManager(
                    Agent(f"BudgetRoot-{component}", "Architect", client),
                    ATTConfig(
                        workspace_root=self.tmpdir,
                        model_token_limits={"default": 10},
                        model_max_output_tokens={"default": 2},
                    ),
                    persistence_mode="volatile",
                )
                manager.count_tokens = (
                    lambda text, model_alias=None: len(str(text).split())
                )
                system_instruction = (
                    "large " * 20
                    if component == "system_instruction"
                    else None
                )
                tools = (
                    [
                        Tool(
                            "large_tool",
                            "large " * 20,
                            lambda: "ok",
                        )
                    ]
                    if component == "tools"
                    else None
                )

                with self.assertRaises(TokenLimitExceededError):
                    await generate_with_retry(
                        client,
                        "small",
                        system_instruction=system_instruction,
                        tools=tools,
                        manager=manager,
                        retries=0,
                    )

                self.assertEqual(calls, [])
                self.assertEqual(
                    manager.model_token_usage.get("default", 0), 0
                )
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
            persistence_mode="volatile",
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
            persistence_mode="volatile",
        )
        manager.register_llm_client("bounded", client)
        await generate_with_retry(
            client, "12345678", manager=manager, retries=1
        )
        self.assertEqual(observed, [("bounded", 4)])
        await manager.close()
