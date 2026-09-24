"""Managed supervisory AgentTeams, isolation, and audit evidence."""

import asyncio
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from unittest.mock import patch

from ai_team_team import ATTConfig, ATTManager, Agent, AuditStatus, StatePersistenceError


class _AuditClient:
    def __init__(self) -> None:
        self.manager = None
        self.seen_teams: dict[str, set[str]] = {}
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.pause_parallel = False
        self.pause_all = False
        self.cancel_delay = 0.0

    async def generate(
        self,
        prompt,
        system_instruction=None,
        temperature=0.3,
        require_json=False,
        **_kwargs,
    ):
        if self.manager is not None:
            team = self.manager._active_team.get()
            if team is not None and team.team_kind == "supervisory":
                self.seen_teams.setdefault(team.team_id, set()).update(
                    agent.agent_id for agent in team.members
                )
                if (self.pause_all or self.pause_parallel) and not require_json:
                    if self.pause_all or len(self.seen_teams) >= 2:
                        self.entered.set()
                    try:
                        await self.release.wait()
                    except asyncio.CancelledError:
                        if self.cancel_delay:
                            await asyncio.sleep(self.cancel_delay)
                        raise
        if require_json:
            return '{"is_healthy": true, "reason": "The audit team approved."}'
        for marker in ("BUSINESS_ALPHA_MARKER", "BUSINESS_BETA_MARKER"):
            if marker in str(prompt):
                return f"Final Answer: The business team completed {marker}."
        return "Final Answer: The discussion is coherent."


class TestSupervisoryTeamLifecycle(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.workspace = tempfile.TemporaryDirectory(prefix="att-supervision-")
        self.addCleanup(self.workspace.cleanup)
        self.client = _AuditClient()
        self.root = Agent("Root", "Architect", llm_client=self.client)
        self.manager = ATTManager(
            self.root,
            ATTConfig(workspace_root=self.workspace.name),
        )
        self.client.manager = self.manager
        self.manager.register_llm_client("default", self.client)
        self.addAsyncCleanup(self.manager.close)
        self.team = self.manager.create_agent_team(self.root, member_count=3)

    async def test_each_audit_uses_new_registered_team_and_disposes_it(self) -> None:
        before_agents = set(self.manager._agents_by_id)
        before_teams = set(self.manager.teams)
        before_libraries = set(self.manager.libraries)

        first = await self.manager.supervisor.audit_team_dialog(self.team, "first input")
        second = await self.manager.supervisor.audit_team_dialog(self.team, "second input")

        self.assertIs(first.status, AuditStatus.HEALTHY)
        self.assertIs(second.status, AuditStatus.HEALTHY)
        self.assertEqual(len(self.client.seen_teams), 2)
        member_groups = list(self.client.seen_teams.values())
        self.assertFalse(member_groups[0].intersection(member_groups[1]))
        self.assertEqual(set(self.manager._agents_by_id), before_agents)
        self.assertEqual(set(self.manager.teams), before_teams)
        self.assertEqual(set(self.manager.libraries), before_libraries)
        evidence = [
            event for event in self.manager._memory.events.values()
            if event.event_type == "supervisory_audit_completed"
        ]
        self.assertEqual(len(evidence), 2)
        self.assertEqual(
            {event.payload["source_transcript"] for event in evidence},
            {"first input", "second input"},
        )
        self.assertTrue(all(event.payload["debate_transcript"] for event in evidence))

    async def test_temporary_team_creation_does_not_submit_identity_state(self) -> None:
        with patch.object(self.manager, "_auto_save", side_effect=AssertionError("unexpected save")):
            supervisory = self.manager._team_creation.create_supervisory_team()
        self.assertIs(self.manager.teams[supervisory.team_id], supervisory)
        await self.manager._team_creation.dissolve_supervisory_team(
            supervisory, persist=False
        )

    async def test_parallel_audits_have_distinct_live_team_and_agent_owners(self) -> None:
        other = self.manager.create_agent_team(self.root, member_count=3)
        self.client.pause_parallel = True
        first = asyncio.create_task(
            self.manager.supervisor.audit_team_dialog(self.team, "alpha input")
        )
        second = asyncio.create_task(
            self.manager.supervisor.audit_team_dialog(other, "beta input")
        )
        try:
            await asyncio.wait_for(self.client.entered.wait(), timeout=5)
            live = [
                team for team in self.manager.teams.values()
                if team.team_kind == "supervisory"
            ]
            self.assertEqual(len(live), 2)
            self.assertTrue(all(self.manager.get_available_tools(team) == {} for team in live))
            self.assertFalse(
                {agent.agent_id for agent in live[0].members}
                & {agent.agent_id for agent in live[1].members}
            )
            public_topology = self.manager.render_topology_tree()
            for team in live:
                self.assertIs(self.manager.teams[team.team_id], team)
                self.assertNotIn(team.team_id, public_topology)
                self.assertIsNone(self.manager.find_parent_team(team))
                self.assertTrue(
                    all(self.manager._agents_by_id[agent.agent_id] is agent for agent in team.members)
                )
                with self.assertRaises(ValueError):
                    self.manager._resolve_existing_team_members([team.members[0]], None)
        finally:
            self.client.release.set()
        results = await asyncio.wait_for(asyncio.gather(first, second), timeout=5)
        self.assertTrue(all(result.status is AuditStatus.HEALTHY for result in results))
        self.assertFalse(
            any(team.team_kind == "supervisory" for team in self.manager.teams.values())
        )

    async def test_parallel_business_discussions_keep_separate_live_audit_contexts(self) -> None:
        other = self.manager.create_agent_team(self.root, member_count=3)
        self.client.pause_parallel = True
        first = asyncio.create_task(
            self.manager.execute_team_discussion_detailed(
                self.team, "BUSINESS_ALPHA_MARKER", rounds=1
            )
        )
        second = asyncio.create_task(
            self.manager.execute_team_discussion_detailed(
                other, "BUSINESS_BETA_MARKER", rounds=1
            )
        )
        try:
            await asyncio.wait_for(self.client.entered.wait(), timeout=5)
            live = [team for team in self.manager.teams.values() if team.team_kind == "supervisory"]
            self.assertEqual(len(live), 2)
            for marker in ("BUSINESS_ALPHA_MARKER", "BUSINESS_BETA_MARKER"):
                matching = [
                    team for team in live
                    if all(marker in str(agent.messages) for agent in team.members)
                ]
                self.assertEqual(len(matching), 1)
        finally:
            self.client.release.set()
        results = await asyncio.wait_for(asyncio.gather(first, second), timeout=5)
        self.assertTrue(all(result.audit.status is AuditStatus.HEALTHY for result in results))

    async def test_audit_evidence_survives_database_restore_without_live_auditors(self) -> None:
        database_path = os.path.join(self.workspace.name, "state.db")
        self.manager.db_path = database_path
        await self.manager.save_state()
        result = await self.manager.supervisor.audit_team_dialog(self.team, "saved input")
        self.assertIs(result.status, AuditStatus.HEALTHY)
        await self.manager.flush_state()
        await self.manager.close()

        new_root = Agent("Replacement", "Architect", llm_client=self.client)
        restored = ATTManager(
            new_root,
            ATTConfig(workspace_root=self.workspace.name),
            db_path=database_path,
        )
        restored.register_llm_client("default", self.client)
        try:
            await restored.load_state(database_path)
            self.assertFalse(
                any(team.team_kind == "supervisory" for team in restored.teams.values())
            )
            self.assertFalse(
                any(agent.name.startswith("Auditor_") for agent in restored._agents_by_id.values())
            )
            evidence = [
                event for event in restored._memory.events.values()
                if event.event_type == "supervisory_audit_completed"
            ]
            self.assertEqual(len(evidence), 1)
            self.assertEqual(evidence[0].payload["source_transcript"], "saved input")
        finally:
            await restored.close()

    async def test_snapshot_during_audit_excludes_temporary_identities_and_files(self) -> None:
        database_path = os.path.join(self.workspace.name, "inflight-snapshot.db")
        self.manager.db_path = database_path
        await self.manager.save_state()
        self.client.pause_all = True
        task = asyncio.create_task(
            self.manager.supervisor.audit_team_dialog(self.team, "inflight input")
        )
        try:
            await asyncio.wait_for(self.client.entered.wait(), timeout=5)
            supervisory = next(
                team for team in self.manager.teams.values()
                if team.team_kind == "supervisory"
            )
            auditor_ids = {agent.agent_id for agent in supervisory.members}
            temporary_library_ids = {f"DL-{supervisory.team_id}"} | {
                f"PDL-{agent_id}" for agent_id in auditor_ids
            }
            await self.manager.flush_state()
            for full_save in (False, True):
                if full_save:
                    await self.manager.save_state(database_path)
                with closing(sqlite3.connect(database_path)) as connection:
                    self.assertEqual(
                        connection.execute(
                            "SELECT COUNT(*) FROM teams WHERE team_id = ?",
                            (supervisory.team_id,),
                        ).fetchone()[0],
                        0,
                    )
                    for agent_id in auditor_ids:
                        self.assertEqual(
                            connection.execute(
                                "SELECT COUNT(*) FROM agents WHERE agent_id = ?", (agent_id,)
                            ).fetchone()[0],
                            0,
                        )
                    for lib_id in temporary_library_ids:
                        self.assertEqual(
                            connection.execute(
                                "SELECT COUNT(*) FROM libraries WHERE lib_id = ?", (lib_id,)
                            ).fetchone()[0],
                            0,
                        )
        finally:
            self.client.release.set()
        await asyncio.wait_for(task, timeout=5)
        await self.manager.close()

        restored = ATTManager(
            Agent("Restore Root", "Architect", llm_client=self.client),
            ATTConfig(workspace_root=self.workspace.name),
            db_path=database_path,
        )
        restored.register_llm_client("default", self.client)
        try:
            await restored.load_state(database_path)
            self.assertFalse(
                any(team.team_kind == "supervisory" for team in restored.teams.values())
            )
        finally:
            await restored.close()

    async def test_failed_deletion_commit_restores_registered_team_and_files(self) -> None:
        database_path = os.path.join(self.workspace.name, "rollback.db")
        self.manager.db_path = database_path
        await self.manager.save_state()
        supervisory = self.manager._team_creation.create_supervisory_team()
        await self.manager.flush_state()
        library_roots = [
            supervisory.doc_library.root_dir,
            *(
                self.manager.libraries[agent.private_doc_library_id].root_dir
                for agent in supervisory.members
            ),
        ]
        original_commit = self.manager._commit_dirty_state

        async def fail_deletion(dirty):
            if dirty["deleted_teams"]:
                raise RuntimeError("injected deletion failure")
            await original_commit(dirty)

        with patch.object(self.manager, "_commit_dirty_state", side_effect=fail_deletion):
            with self.assertRaisesRegex(RuntimeError, "injected deletion failure"):
                await self.manager._team_creation.dissolve_supervisory_team(supervisory)
        self.assertIs(self.manager.teams[supervisory.team_id], supervisory)
        self.assertTrue(all(os.path.isdir(root) for root in library_roots))
        self.assertTrue(
            all(self.manager._agents_by_id[agent.agent_id] is agent for agent in supervisory.members)
        )
        await self.manager._team_creation.dissolve_supervisory_team(supervisory)

    async def test_deletion_keeps_names_reserved_until_commit_finishes(self) -> None:
        supervisory = self.manager._team_creation.create_supervisory_team()
        auditor = supervisory.members[0]
        entered_commit = asyncio.Event()
        release_commit = asyncio.Event()
        original_commit = self.manager._commit_dirty_state

        async def pause_deletion(dirty):
            if dirty["deleted_teams"]:
                entered_commit.set()
                await release_commit.wait()
            await original_commit(dirty)

        with patch.object(self.manager, "_commit_dirty_state", side_effect=pause_deletion):
            teardown = asyncio.create_task(
                self.manager._team_creation.dissolve_supervisory_team(supervisory)
            )
            try:
                await asyncio.wait_for(entered_commit.wait(), timeout=5)
                self.assertIs(self.manager.teams[supervisory.team_id], supervisory)
                self.assertIs(self.manager.agents[auditor.name], auditor)
                with self.assertRaises(ValueError):
                    self.manager.register_agent(
                        Agent(auditor.name, "Duplicate", llm_client=self.client)
                    )
            finally:
                release_commit.set()
            await asyncio.wait_for(teardown, timeout=5)
        self.assertNotIn(auditor.name, self.manager.agents)

    async def test_full_save_cannot_resurrect_team_during_deletion(self) -> None:
        database_path = os.path.join(self.workspace.name, "save-race.db")
        self.manager.db_path = database_path
        await self.manager.save_state()
        supervisory = self.manager._team_creation.create_supervisory_team()
        await self.manager.flush_state()
        entered_commit = asyncio.Event()
        release_commit = asyncio.Event()
        original_commit = self.manager._commit_dirty_state

        async def pause_deletion(dirty):
            if dirty["deleted_teams"]:
                entered_commit.set()
                await release_commit.wait()
            await original_commit(dirty)

        with patch.object(self.manager, "_commit_dirty_state", side_effect=pause_deletion):
            teardown = asyncio.create_task(
                self.manager._team_creation.dissolve_supervisory_team(supervisory)
            )
            await asyncio.wait_for(entered_commit.wait(), timeout=5)
            save = asyncio.create_task(self.manager.save_state(full=True))
            await asyncio.sleep(0)
            self.assertFalse(save.done())
            release_commit.set()
            await asyncio.wait_for(asyncio.gather(teardown, save), timeout=5)
        with closing(sqlite3.connect(database_path)) as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM teams WHERE team_id = ?", (supervisory.team_id,)
            ).fetchone()[0]
        self.assertEqual(count, 0)

    async def test_repeated_cancellation_does_not_roll_back_committed_deletion(self) -> None:
        database_path = os.path.join(self.workspace.name, "double-cancel.db")
        self.manager.db_path = database_path
        await self.manager.save_state()
        supervisory = self.manager._team_creation.create_supervisory_team()
        await self.manager.flush_state()
        entered_commit = asyncio.Event()
        release_commit = asyncio.Event()
        original_commit = self.manager._commit_dirty_state

        async def pause_deletion(dirty):
            if dirty["deleted_teams"]:
                entered_commit.set()
                await release_commit.wait()
            await original_commit(dirty)

        with patch.object(self.manager, "_commit_dirty_state", side_effect=pause_deletion):
            teardown = asyncio.create_task(
                self.manager._team_creation.dissolve_supervisory_team(supervisory)
            )
            await asyncio.wait_for(entered_commit.wait(), timeout=5)
            teardown.cancel()
            await asyncio.sleep(0)
            teardown.cancel()
            release_commit.set()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(teardown, timeout=5)
        self.assertNotIn(supervisory.team_id, self.manager.teams)
        with closing(sqlite3.connect(database_path)) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM teams WHERE team_id = ?", (supervisory.team_id,)
                ).fetchone()[0],
                0,
            )

    async def test_cancelled_audit_dissolves_team_and_keeps_cancellation_evidence(self) -> None:
        self.client.pause_all = True
        task = asyncio.create_task(
            self.manager.supervisor.audit_team_dialog(self.team, "cancelled input")
        )
        await asyncio.wait_for(self.client.entered.wait(), timeout=5)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=5)
        self.assertFalse(
            any(team.team_kind == "supervisory" for team in self.manager.teams.values())
        )
        evidence = [
            event for event in self.manager._memory.events.values()
            if event.event_type == "supervisory_audit_completed"
        ]
        self.assertEqual(len(evidence), 1)
        self.assertTrue(evidence[0].payload["cancelled"])

    async def test_cancellation_during_initial_flush_still_dissolves_team(self) -> None:
        entered_flush = asyncio.Event()
        original_flush = self.manager.flush_state
        flush_calls = 0

        async def pause_first_flush() -> None:
            nonlocal flush_calls
            flush_calls += 1
            if flush_calls == 1:
                entered_flush.set()
                await asyncio.Event().wait()
            await original_flush()

        with patch.object(self.manager, "flush_state", side_effect=pause_first_flush):
            task = asyncio.create_task(
                self.manager.supervisor.audit_team_dialog(self.team, "initial flush input")
            )
            await asyncio.wait_for(entered_flush.wait(), timeout=5)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=5)
        self.assertFalse(
            any(team.team_kind == "supervisory" for team in self.manager.teams.values())
        )

    async def test_initial_persistence_failure_dissolves_temporary_team(self) -> None:
        with patch.object(
            self.manager,
            "flush_state",
            side_effect=StatePersistenceError("injected initial flush failure"),
        ):
            with self.assertRaisesRegex(StatePersistenceError, "initial flush failure"):
                await self.manager.supervisor.audit_team_dialog(self.team, "failed input")
        self.assertFalse(
            any(team.team_kind == "supervisory" for team in self.manager.teams.values())
        )

    async def test_evidence_commit_failure_dissolves_temporary_team(self) -> None:
        original_commit = self.manager._commit_dirty_state

        async def fail_evidence(dirty):
            if dirty["memory_events"] and not dirty["deleted_teams"]:
                raise StatePersistenceError("injected evidence failure")
            await original_commit(dirty)

        with patch.object(self.manager, "_commit_dirty_state", side_effect=fail_evidence):
            with self.assertRaisesRegex(StatePersistenceError, "evidence failure"):
                await self.manager.supervisor.audit_team_dialog(self.team, "failed input")
        self.assertFalse(
            any(team.team_kind == "supervisory" for team in self.manager.teams.values())
        )
        self.assertFalse(
            any(
                event.event_type == "supervisory_audit_completed"
                for event in self.manager._memory.events.values()
            )
        )

    async def test_evidence_construction_failure_dissolves_temporary_team(self) -> None:
        original_record = self.manager._memory.record_event

        def fail_evidence(event_type, **kwargs):
            if event_type == "supervisory_audit_completed":
                raise RuntimeError("injected evidence construction failure")
            return original_record(event_type, **kwargs)

        with patch.object(self.manager._memory, "record_event", side_effect=fail_evidence):
            with self.assertRaisesRegex(RuntimeError, "evidence construction failure"):
                await self.manager.supervisor.audit_team_dialog(self.team, "failed input")
        self.assertFalse(
            any(team.team_kind == "supervisory" for team in self.manager.teams.values())
        )

    async def test_teardown_commit_failure_keeps_evidence_without_live_team(self) -> None:
        database_path = os.path.join(self.workspace.name, "teardown-failure.db")
        self.manager.db_path = database_path
        await self.manager.save_state()
        original_commit = self.manager._commit_dirty_state

        async def fail_teardown(dirty):
            if dirty["deleted_teams"]:
                raise StatePersistenceError("injected teardown failure")
            await original_commit(dirty)

        with patch.object(self.manager, "_commit_dirty_state", side_effect=fail_teardown):
            with self.assertRaisesRegex(StatePersistenceError, "teardown failure"):
                await self.manager.supervisor.audit_team_dialog(self.team, "saved input")
        self.assertFalse(
            any(team.team_kind == "supervisory" for team in self.manager.teams.values())
        )
        await self.manager.flush_state()
        with closing(sqlite3.connect(database_path)) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM system_memory_events "
                    "WHERE event_type = 'supervisory_audit_completed'"
                ).fetchone()[0],
                1,
            )

    async def test_close_waits_for_supervisory_teardown_after_cancellation(self) -> None:
        self.client.pause_all = True
        task = asyncio.create_task(
            self.manager.supervisor.audit_team_dialog(self.team, "shutdown input")
        )
        await asyncio.wait_for(self.client.entered.wait(), timeout=5)
        await asyncio.wait_for(self.manager.close(), timeout=5)
        await asyncio.gather(task, return_exceptions=True)
        self.assertFalse(
            any(team.team_kind == "supervisory" for team in self.manager.teams.values())
        )
        self.assertFalse(self.manager.supervisor.finalizers)

    async def test_close_waits_for_delayed_cooperative_audit_cancellation(self) -> None:
        database_path = os.path.join(self.workspace.name, "delayed-close.db")
        self.manager.db_path = database_path
        await self.manager.save_state()
        self.client.pause_all = True
        self.client.cancel_delay = 0.1
        task = asyncio.create_task(
            self.manager.supervisor.audit_team_dialog(self.team, "delayed shutdown input")
        )
        await asyncio.wait_for(self.client.entered.wait(), timeout=5)
        await asyncio.wait_for(self.manager.close(), timeout=5)
        await asyncio.gather(task, return_exceptions=True)
        self.assertFalse(
            any(team.team_kind == "supervisory" for team in self.manager.teams.values())
        )

    async def test_close_propagates_supervisory_teardown_failure(self) -> None:
        self.client.pause_all = True
        task = asyncio.create_task(
            self.manager.supervisor.audit_team_dialog(self.team, "failed shutdown input")
        )
        await asyncio.wait_for(self.client.entered.wait(), timeout=5)
        original_commit = self.manager._commit_dirty_state

        async def fail_deletion(dirty):
            if dirty["deleted_teams"]:
                raise RuntimeError("supervisory teardown failed")
            await original_commit(dirty)

        with patch.object(self.manager, "_commit_dirty_state", side_effect=fail_deletion):
            with self.assertRaisesRegex(RuntimeError, "supervisory teardown failed"):
                await asyncio.wait_for(self.manager.close(), timeout=5)
        await asyncio.gather(task, return_exceptions=True)
        self.assertTrue(self.manager._closed)


if __name__ == "__main__":
    unittest.main()
