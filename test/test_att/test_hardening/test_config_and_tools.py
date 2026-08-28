from test.test_att.test_hardening._support import (
    ATTConfig,
    ATTManager,
    ATTHardeningTestCase,
    Agent,
    AsyncMock,
    AuditResult,
    AuditStatus,
    BaseModel,
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
    def test_config_rejects_unknown_policies(self):
        cases = {
            "migration_policy": "silent",
            "failover_policy": "random",
            "tool_calling_mode": "maybe",
            "audit_unknown_escalation_mode": "ignore",
            "agent_private_data_policy": "expose",
        }
        for name, value in cases.items():
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    ATTConfig(**{name: value})
        with self.assertRaises(ValueError):
            ATTConfig(communication={"policy": "open"})
        for invalid in (False, 0, ""):
            with self.subTest(communication=invalid):
                with self.assertRaises(ValueError):
                    ATTConfig(communication=invalid)
        with self.assertRaises(ValueError):
            ATTConfig(
                communication={
                    "policy": "parent_approval",
                    "request_delivery": "queue",
                    "direction": "bidirectional",
                    "unexpected": True,
                }
            )
        config = ATTConfig(
            communication={"policy": "parent_approval"}
        )
        self.assertIsInstance(config, BaseModel)
        with self.assertRaises(ValueError):
            ATTConfig(unknown_setting=True)
        with self.assertRaises(ValueError):
            config.communication.direction = "both"
        config.communication = {
            "policy": "lineage_approval",
            "request_delivery": "wake",
        }
        self.assertEqual(config.communication.policy, "lineage_approval")
        self.assertEqual(config.to_dict(), config.model_dump(mode="json"))

    def test_builtin_tools_have_manager_context_immediately(self):
        team = self.manager.create_agent_team(self.root)
        self.assertIs(
            self.manager.tools_context["att_manager"], self.manager
        )
        self.assertIn("dispatch_subagent", team.tools)
        self.manager.register_tools_context(
            {"att_manager": object(), "service": "value"}
        )
        self.assertIs(
            self.manager.tools_context["att_manager"], self.manager
        )
