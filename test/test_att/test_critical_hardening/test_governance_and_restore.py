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


class TestCriticalHardening(CriticalHardeningTestCase):
    async def test_governance_approval_requires_literal_boolean(self):
        events = []
        self.manager.on_system_event = lambda event, details: events.append(
            (event, details)
        )
        invalid_payloads = [
            '{"approved": "true"}',
            '{"approved": "false"}',
            '{"approved": 1}',
            '{"approved": 0}',
            '{"approved": null}',
            '{}',
        ]
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                approved, reason = parse_governance_decision(
                    payload, self.manager, "test authorization"
                )
                self.assertFalse(approved)
                self.assertIn("Invalid governance decision format", reason)
        await self.manager.flush_callbacks()
        self.assertEqual(
            sum(event == "governance_authorization_format_error" for event, _ in events),
            len(invalid_payloads),
        )
        self.assertEqual(
            parse_governance_decision(
                '{"approved": true, "reason": "valid"}',
                self.manager,
                "test authorization",
            ),
            (True, "valid"),
        )
        self.assertEqual(
            parse_governance_decision(
                '{"approved": false, "reason": "denied"}',
                self.manager,
                "test authorization",
            ),
            (False, "denied"),
        )

    async def test_corrupt_restore_preserves_live_manager_and_doclib(self):
        source_root = os.path.join(self.tmpdir, "source")
        db_path = os.path.join(self.tmpdir, "state.db")
        source = ATTManager(
            Agent("SourceRoot", "Architect", self.client),
            ATTConfig(workspace_root=source_root),
            db_path=db_path,
        )
        source.register_llm_client("test", self.client)
        persisted_team = source.create_agent_team(source.root_ai)
        persisted_team.doc_library.write_file("persisted.txt", "new state")
        await source.save_state()
        await source.close()
        with closing(sqlite3.connect(db_path)) as connection:
            connection.execute(
                "INSERT INTO team_members (team_id, agent_id) VALUES (?, ?)",
                (persisted_team.team_id, "missing-agent"),
            )
            connection.commit()

        original_team = self.manager.create_agent_team(self.root)
        original_team.doc_library.write_file("original.txt", "live state")
        old_config = self.manager.config
        old_root = self.manager.root_ai
        old_agents = self.manager.agents
        old_teams = self.manager.teams
        old_libraries = self.manager.libraries

        with self.assertRaisesRegex(StateRestoreError, "missing members"):
            await self.manager.load_state(db_path)

        self.assertIs(self.manager.config, old_config)
        self.assertIs(self.manager.root_ai, old_root)
        self.assertIs(self.manager.agents, old_agents)
        self.assertIs(self.manager.teams, old_teams)
        self.assertIs(self.manager.libraries, old_libraries)
        self.assertIn(
            "live state",
            original_team.doc_library.read_file("original.txt"),
        )

    async def test_restore_recomputes_depth_instead_of_trusting_database(self):
        source_root = os.path.join(self.tmpdir, "depth-source")
        db_path = os.path.join(self.tmpdir, "depth.db")
        source = ATTManager(
            Agent("DepthRoot", "Architect", self.client),
            ATTConfig(workspace_root=source_root),
            db_path=db_path,
        )
        source.register_llm_client("test", self.client)
        parent = source.create_agent_team(source.root_ai)
        child = source.create_agent_team(parent)
        await source.save_state()
        await source.close()
        with closing(sqlite3.connect(db_path)) as connection:
            connection.execute("UPDATE teams SET depth = 999")
            connection.commit()

        restored = ATTManager(
            Agent("DepthRoot", "Architect", self.client),
            ATTConfig(workspace_root=os.path.join(self.tmpdir, "unused")),
        )
        restored.register_llm_client("test", self.client)
        await restored.load_state(db_path)
        self.assertEqual(restored.teams[parent.team_id].depth, 1)
        self.assertEqual(restored.teams[child.team_id].depth, 2)
        await restored.close()

