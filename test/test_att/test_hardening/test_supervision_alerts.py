from test.test_att.test_hardening._support import (
    ATTConfig,
    ATTManager,
    ATTHardeningTestCase,
    Agent,
    AsyncMock,
    AuditResult,
    AuditStatus,
    DatabaseStore,
    MagicMock,
    StateRestoreError,
    asyncio,
    closing,
    get_default_tools,
    os,
    patch,
    sqlite3,
)


class TestATTHardening(ATTHardeningTestCase):
    async def test_unknown_wake_queue_and_deduplication(self):
        parent = self.manager.create_agent_team(self.root)
        child = self.manager.create_agent_team(parent)
        self.manager.execute_emergency_discussion = AsyncMock(
            return_value="handled"
        )
        result = AuditResult(
            AuditStatus.UNKNOWN,
            "Audit unavailable.",
            "TimeoutError: timeout",
        )

        await asyncio.gather(
            self.manager.supervisor.report_unknown(
                child, result, self.manager
            ),
            self.manager.supervisor.report_unknown(
                child, result, self.manager
            ),
        )
        await asyncio.sleep(0)
        self.manager.execute_emergency_discussion.assert_awaited_once()
        self.assertTrue(
            self.manager.execute_emergency_discussion.await_args.kwargs[
                "skip_audit"
            ]
        )

        self.manager.execute_emergency_discussion.reset_mock()
        self.manager.config.audit_unknown_escalation_mode = "queue"
        await self.manager.supervisor.report_unknown(
            child, result, self.manager
        )
        await asyncio.sleep(0)
        self.manager.execute_emergency_discussion.assert_not_awaited()
        self.assertTrue(
            any(
                message.get("type") == "audit_unknown_escalation"
                for message in parent.message_inbox
            )
        )
    async def test_unhealthy_keeps_emergency_escalation(self):
        parent = self.manager.create_agent_team(self.root)
        child = self.manager.create_agent_team(parent)
        self.manager.execute_emergency_discussion = AsyncMock(
            return_value="handled"
        )

        await self.manager.supervisor.report_anomaly(
            child, "Confirmed deadlock.", self.manager
        )
        await asyncio.sleep(0)

        self.manager.execute_emergency_discussion.assert_awaited_once()
        alert = (
            self.manager.execute_emergency_discussion
            .await_args.args[1]
        )
        self.assertEqual(alert["type"], "child_failure_escalation")
        self.assertFalse(
            self.manager.execute_emergency_discussion.await_args.kwargs[
                "skip_audit"
            ]
        )
