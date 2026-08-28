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
    shutil,
    sqlite3,
)


class TestATTHardening(ATTHardeningTestCase):
    async def test_concurrent_nested_suppression_keeps_batches_separate(self):
        first = self.manager.create_agent_team(self.root)
        second = self.manager.create_agent_team(self.root)
        submitted = []
        self.manager.db_path = os.path.join(self.tmpdir, "unused.db")
        self.manager._submit_dirty_state = submitted.append
        rendezvous = asyncio.Event()

        async def mutate(team, wait):
            async with self.manager.suppress_auto_save():
                self.manager._auto_save(teams={team.team_id})
                async with self.manager.suppress_auto_save():
                    self.manager._auto_save(teams={team.team_id})
                if wait:
                    rendezvous.set()
                else:
                    await rendezvous.wait()

        await asyncio.gather(
            mutate(first, True),
            mutate(second, False),
        )

        self.assertEqual(len(submitted), 2)
        self.assertEqual(
            {frozenset(batch["teams"]) for batch in submitted},
            {
                frozenset({first.team_id}),
                frozenset({second.team_id}),
            },
        )
    async def test_incremental_agent_write_preserves_other_messages(self):
        db_path = os.path.join(self.tmpdir, "state.db")
        manager = ATTManager(
            self.root,
            ATTConfig(workspace_root=self.tmpdir),
            db_path=db_path,
        )
        manager.register_llm_client("test", self.client)
        team = manager.create_agent_team(self.root)
        await manager.save_state()
        untouched = team.members[1]
        changed = team.members[0]

        with closing(sqlite3.connect(db_path)) as connection:
            before = connection.execute(
                "SELECT id FROM agent_messages WHERE agent_id = ?",
                (untouched.agent_id,),
            ).fetchall()

        changed.messages.append({"role": "user", "content": "delta"})
        manager._auto_save(agents={changed.name})
        await manager.flush_state()

        with closing(sqlite3.connect(db_path)) as connection:
            after = connection.execute(
                "SELECT id FROM agent_messages WHERE agent_id = ?",
                (untouched.agent_id,),
            ).fetchall()
        self.assertEqual(before, after)
        await manager.close()
    async def test_slow_database_write_does_not_block_heartbeat(self):
        db_path = os.path.join(self.tmpdir, "slow.db")
        manager = ATTManager(
            self.root,
            ATTConfig(workspace_root=self.tmpdir),
            db_path=db_path,
        )
        manager.register_llm_client("test", self.client)
        original_write = DatabaseStore.write

        def slow_write(store, snapshot):
            import time

            time.sleep(0.15)
            return original_write(store, snapshot)

        heartbeats = 0

        async def heartbeat():
            nonlocal heartbeats
            for _ in range(5):
                await asyncio.sleep(0.02)
                heartbeats += 1

        with patch.object(DatabaseStore, "write", slow_write):
            manager._auto_save(configs=True)
            await heartbeat()
            self.assertEqual(heartbeats, 5)
            await manager.flush_state()
        await manager.close()
    async def test_incremental_doc_file_restore_and_missing_binding(self):
        db_path = os.path.join(self.tmpdir, "files.db")
        manager = ATTManager(
            self.root,
            ATTConfig(workspace_root=self.tmpdir),
            db_path=db_path,
        )
        manager.register_llm_client("test", self.client)
        team = manager.create_agent_team(self.root)
        await manager.save_state()
        team.doc_library.write_file("delta/note.txt", "persisted delta")
        await manager.flush_state()
        shutil.rmtree(team.doc_library.root_dir)
        await manager.close()

        restored = ATTManager(
            Agent("Root", "Architect", llm_client=self.client),
            ATTConfig(workspace_root=self.tmpdir),
        )
        restored.register_llm_client("test", self.client)
        await restored.load_state(db_path)
        restored_team = restored.teams[team.team_id]
        self.assertIn(
            "persisted delta",
            restored_team.doc_library.read_file("delta/note.txt"),
        )
        await restored.close()

        rebinder = ATTManager(
            Agent("Root", "Architect", llm_client=self.client),
            ATTConfig(workspace_root=self.tmpdir),
            db_path=db_path,
        )
        rebinder.register_llm_client("test", self.client)
        await rebinder.load_state(db_path)
        rebinder.llm_clients.pop("test")
        rebinder.register_llm_client("named", self.client)
        await rebinder.save_state()
        await rebinder.close()
        missing = ATTManager(
            Agent("Root", "Architect", llm_client=self.client),
            ATTConfig(workspace_root=self.tmpdir),
        )
        with self.assertRaisesRegex(StateRestoreError, "named"):
            await missing.load_state(db_path)
        await missing.close()
    async def test_incremental_inbox_and_proposal_restore(self):
        db_path = os.path.join(self.tmpdir, "governance.db")
        manager = ATTManager(
            self.root,
            ATTConfig(
                enable_membership_voting=True,
                workspace_root=self.tmpdir,
            ),
            db_path=db_path,
        )
        manager.register_llm_client("test", self.client)
        team = manager.create_agent_team(self.root)
        await manager.flush_state()
        tools = get_default_tools(
            {"att_manager": manager}, team.members[0]
        )
        response = await tools["initiate_membership_vote"](
            "add", "Reviewer", "Need review."
        )
        proposal_id = response.split("'")[1]
        team.receive_message(
            {
                "type": "status_update",
                "from": "peer",
                "objective": "incremental inbox",
            }
        )
        await manager.flush_state()
        await manager.close()

        restored = ATTManager(
            Agent("Root", "Architect", llm_client=self.client),
            ATTConfig(workspace_root=self.tmpdir),
        )
        restored.register_llm_client("test", self.client)
        await restored.load_state(db_path)
        restored_team = restored.teams[team.team_id]
        self.assertIn(proposal_id, restored_team.proposals)
        self.assertEqual(
            restored_team.message_inbox[0]["objective"],
            "incremental inbox",
        )
        await restored.close()
    async def test_async_context_flushes_and_closes(self):
        db_path = os.path.join(self.tmpdir, "context.db")
        scoped = ATTManager(
            Agent("ScopedRoot", "Architect", llm_client=self.client),
            ATTConfig(workspace_root=self.tmpdir),
            db_path=db_path,
        )
        scoped.register_llm_client("test", self.client)
        async with scoped:
            scoped.create_agent_team(scoped.root_ai)
        self.assertTrue(scoped._persistence._closed)
        self.assertTrue(os.path.exists(db_path))
