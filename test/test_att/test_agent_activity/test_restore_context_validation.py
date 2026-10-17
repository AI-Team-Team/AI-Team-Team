"""Corrupt personal recovery metadata cannot reach runtime/file publication."""

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from ai_team_team import ATTConfig, ATTManager, Agent, StateRestoreError
from ai_team_team.core.activity.contracts import AgentTeamScope

from ._support import ActivityTestCase, idle


class RestoreContextValidationTests(ActivityTestCase):
    async def source_checkpoint(self):
        await self.manager.close()
        self.manager = self.make_manager(self.root, durable=True)
        team = self.manager.bootstrap_agent_team(
            self.root,
            existing_members=[self.root],
            member_configs={"PeerA": {"model": "fixture"}, "PeerB": {"model": "fixture"}},
        )
        self.steps(idle())
        admission = await self.manager.activate_agent(
            self.root.agent_id, scope=AgentTeamScope(team_id=team.team_id)
        )
        await self.wait(admission)
        await self.settle()
        return team

    def restore_target(self):
        root = Agent("UnchangedHostRoot", "Architect", self.client)
        target = ATTManager(
            root,
            ATTConfig(workspace_root=str(Path(self.workspace.name) / "target")),
            persistence_mode="volatile",
        )
        target.register_llm_client("fixture", self.client)
        self.addAsyncCleanup(target.close)
        target.libraries[root.private_doc_library_id].write_file("original.txt", "ORIGINAL_DATA")
        return target

    def replace_context(self, value):
        with closing(sqlite3.connect(self.manager.db_path)) as database:
            database.execute(
                "UPDATE agents SET last_context=? WHERE agent_id=?",
                (json.dumps(value), self.root.agent_id),
            )
            database.commit()

    async def test_invalid_context_matrix_is_rejected_before_any_publication(self):
        team = await self.source_checkpoint()
        outsider_team = self.manager.bootstrap_agent_team(
            self.root,
            member_configs={f"Outsider{i}": {"model": "fixture"} for i in range(3)},
        )
        await self.manager.save_state()
        await self.manager.close()
        target = self.restore_target()
        original_root = target.root_ai
        original_agents, original_libraries = dict(target._agents_by_id), dict(target.libraries)
        original_config, original_records = target.config, target._records.snapshot()
        original_file = target.libraries[original_root.private_doc_library_id]
        for context in (
            None,
            [],
            17,
            "invalid container",
            {"activity_scope": None},
            {"activity_scope": []},
            {"activity_scope": {}},
            {"activity_scope": {"kind": "unknown"}},
            {"activity_scope": {"kind": "personal", "team_id": team.team_id}},
            {"activity_scope": {"kind": "agent_team"}},
            {"activity_scope": {"kind": "agent_team", "team_id": 17}},
            {"activity_scope": {"kind": "agent_team", "team_id": True}},
            {"activity_scope": {"kind": "agent_team", "team_id": ""}},
            {"activity_scope": {"kind": "agent_team", "team_id": "missing-team"}},
            {"activity_scope": {"kind": "agent_team", "team_id": outsider_team.team_id}},
        ):
            with self.subTest(context=context):
                self.replace_context(context)
                with self.assertRaises(StateRestoreError):
                    await target.load_state(self.manager.db_path)
                self.assertIs(target.root_ai, original_root)
                self.assertIs(target.config, original_config)
                self.assertEqual(target._agents_by_id, original_agents)
                self.assertEqual(target.libraries, original_libraries)
                self.assertEqual(target._records.snapshot(), original_records)
                self.assertEqual(original_file.read_file("original.txt"), "ORIGINAL_DATA")
                self.assertIsNone(target.db_path)
                self.assertFalse(target._activity.sessions)

    async def test_absent_checkpoint_scope_uses_the_validated_latest_invocation(self):
        team = await self.source_checkpoint()
        await self.manager.save_state()
        await self.manager.close()
        self.replace_context({"unrelated_metadata": "retained"})
        target = self.restore_target()
        await target.load_state(self.manager.db_path)
        self.assertEqual(
            target.inspect_agent_activity(self.root.agent_id).scope,
            AgentTeamScope(team_id=team.team_id),
        )
        self.assertEqual(target.root_ai.last_context, {"unrelated_metadata": "retained"})

    async def test_past_scope_remains_history_after_membership_ends(self):
        team = await self.source_checkpoint()
        context = dict(self.root.last_context)
        # Trusted fixture mutation records a real departure without changing
        # this person's own fields or granting any new live team authority.
        with self.manager._resources.mutation():
            team.members.remove(self.root)
        self.manager._auto_save(teams={team.team_id})
        await self.manager.save_state()
        await self.manager.close()
        target = self.restore_target()
        await target.load_state(self.manager.db_path)
        self.assertEqual(target.root_ai.last_context, context)
        self.assertEqual(
            target.inspect_agent_activity(self.root.agent_id).scope,
            AgentTeamScope(team_id=team.team_id),
        )
        with self.assertRaises(PermissionError):
            await target.activate_agent(
                self.root.agent_id, scope=AgentTeamScope(team_id=team.team_id)
            )
        self.assertFalse(target._activity.workers)
