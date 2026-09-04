import os
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing
from unittest.mock import patch

from ai_team_team import ATTConfig, ATTManager, Agent
from ai_team_team.tool import get_default_tools


class EchoClient:
    async def generate(self, prompt, system_instruction=None, **kwargs):
        return "Final Answer: complete"


class TestSharedAgentMembership(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="att-shared-membership-")
        self.client = EchoClient()
        self.root = Agent("Root", "Architect", self.client)
        self.manager = ATTManager(
            self.root,
            ATTConfig(workspace_root=self.tmpdir),
        )
        self.manager.register_llm_client("shared-model", self.client)
        self.shared = Agent(
            "Alice",
            "Researcher",
            self.client,
            role_description="Persistent identity",
            system_instructions="Preserve evidence provenance.",
        )
        self.manager.register_agent(self.shared)
        self.parent = self.manager.create_agent_team(self.root)

    async def asyncTearDown(self):
        await self.manager.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @staticmethod
    def _new_member_configs(prefix, count):
        return {f"{prefix}{index}": {"model": "shared-model"} for index in range(1, count + 1)}

    def _identity_state(self):
        return {
            "agent_id": self.shared.agent_id,
            "name": self.shared.name,
            "role": self.shared.role,
            "role_description": self.shared.role_description,
            "system_instructions": self.shared.system_instructions,
            "llm_client": self.shared.llm_client,
            "model_alias": self.shared._model_alias,
            "lifecycle_state": self.shared.lifecycle_state,
            "private_doc_library_id": self.shared.private_doc_library_id,
            "messages_object_id": id(self.shared.messages),
            "messages": tuple(dict(message) for message in self.shared.messages),
            "message_history_object_id": id(self.shared.message_history),
            "message_history": tuple(dict(message) for message in self.shared.message_history),
            "history_seen_ids": frozenset(self.shared._history_seen_ids),
            "last_context_object_id": id(self.shared.last_context),
            "last_context": (dict(self.shared.last_context) if self.shared.last_context else None),
            "invocation_lock": self.shared.lock,
            "lifecycle_lock": self.shared.lifecycle_lock,
        }

    def _persisted_identity_state(self, db_path):
        with closing(sqlite3.connect(db_path)) as connection:
            agent = connection.execute(
                "SELECT agent_id, name, role, role_description, system_instructions, "
                "model_alias, last_context, lifecycle_state FROM agents WHERE agent_id = ?",
                (self.shared.agent_id,),
            ).fetchone()
            messages = connection.execute(
                "SELECT id, agent_id, role, content, created_at, tool_calls, tool_call_id, "
                "name, team_id, discussion_id FROM agent_messages WHERE agent_id = ? "
                "ORDER BY id",
                (self.shared.agent_id,),
            ).fetchall()
            library = connection.execute(
                "SELECT lib_id, name, library_kind, owner_team_id, owner_agent_id, "
                "lifecycle_state, description, is_public_visible FROM libraries "
                "WHERE lib_id = ?",
                (self.shared.private_doc_library_id,),
            ).fetchone()
            files = connection.execute(
                "SELECT lib_id, path, content FROM doc_lib_files WHERE lib_id = ? ORDER BY path",
                (self.shared.private_doc_library_id,),
            ).fetchall()
        return agent, messages, library, files

    async def test_membership_is_role_neutral_and_removal_is_team_local(self):
        self.shared.messages.append(
            {"role": "user", "content": "Unsynchronized compatibility message"}
        )
        identity_before = self._identity_state()
        private_library = self.manager.libraries[self.shared.private_doc_library_id]

        team_a = self.manager.create_agent_team(
            self.parent,
            member_configs=self._new_member_configs("A", 3),
            existing_members=[self.shared],
        )
        team_b = self.manager.create_agent_team(
            self.parent,
            member_configs=self._new_member_configs("B", 2),
            existing_member_ids=[self.shared.agent_id],
        )

        self.assertIs(
            next(member for member in team_a.members if member is self.shared), self.shared
        )
        self.assertIs(
            next(member for member in team_b.members if member is self.shared), self.shared
        )
        self.assertEqual(self._identity_state(), identity_before)
        self.assertIs(
            self.manager.libraries[self.shared.private_doc_library_id],
            private_library,
        )

        private_tools = get_default_tools(self.manager.tools_context, self.shared)
        agent_token = self.manager._active_tool_agent.set(self.shared)
        team_token = self.manager._active_team.set(team_a)
        try:
            await private_tools["write_private_file"]("notes/shared.txt", "one workspace")
        finally:
            self.manager._active_team.reset(team_token)
            self.manager._active_tool_agent.reset(agent_token)

        agent_token = self.manager._active_tool_agent.set(self.shared)
        team_token = self.manager._active_team.set(team_b)
        try:
            content = await private_tools["read_private_file"]("notes/shared.txt")
        finally:
            self.manager._active_team.reset(team_token)
            self.manager._active_tool_agent.reset(agent_token)
        self.assertIn("one workspace", content)

        parent_agent = self.parent.members[0]
        membership_tools = get_default_tools(self.manager.tools_context, parent_agent)
        agent_token = self.manager._active_tool_agent.set(parent_agent)
        team_token = self.manager._active_team.set(self.parent)
        try:
            result = await membership_tools["remove_team_member"](
                team_a.team_id,
                self.shared.name,
            )
        finally:
            self.manager._active_team.reset(team_token)
            self.manager._active_tool_agent.reset(agent_token)

        self.assertIn("Successfully removed", result)
        self.assertNotIn(self.shared, team_a.members)
        self.assertIn(self.shared, team_b.members)
        self.assertIs(self.manager.agents[self.shared.name], self.shared)
        self.assertIs(
            self.manager.libraries[self.shared.private_doc_library_id],
            private_library,
        )
        self.assertEqual(self._identity_state(), identity_before)

    def test_invalid_or_legacy_membership_inputs_are_atomic(self):
        managed_root = os.path.join(self.tmpdir, ".att_doc_libs")
        before = (
            dict(self.manager.agents),
            dict(self.manager.teams),
            dict(self.manager.libraries),
            set(os.listdir(managed_root)),
        )

        invalid_calls = [
            {
                "member_configs": {
                    "AssignedRole": self.shared,
                    **self._new_member_configs("Direct", 2),
                }
            },
            {
                "member_configs": {
                    "Legacy": {"hire_agent": self.shared.name},
                    **self._new_member_configs("LegacyHelper", 2),
                }
            },
            {
                "member_configs": {
                    "ImplicitReuse": {"model": self.shared.name},
                    **self._new_member_configs("AliasHelper", 2),
                }
            },
            {
                "member_configs": self._new_member_configs("Duplicate", 1),
                "existing_members": [self.shared, self.shared],
            },
            {
                "member_configs": self._new_member_configs("DuplicateId", 1),
                "existing_members": [self.shared],
                "existing_member_ids": [self.shared.agent_id],
            },
            {
                "member_configs": self._new_member_configs("Unregistered", 2),
                "existing_members": [Agent("Unknown", "Researcher", self.client)],
            },
        ]
        for kwargs in invalid_calls:
            with self.subTest(kwargs=tuple(kwargs)), self.assertRaises((TypeError, ValueError)):
                self.manager.create_agent_team(self.parent, **kwargs)

        self.assertEqual(self.manager.agents, before[0])
        self.assertEqual(self.manager.teams, before[1])
        self.assertEqual(self.manager.libraries, before[2])
        self.assertEqual(set(os.listdir(managed_root)), before[3])

    async def test_save_and_restore_reuses_one_agent_object_for_all_memberships(self):
        team_a = self.manager.create_agent_team(
            self.parent,
            member_configs=self._new_member_configs("PersistA", 2),
            existing_members=[self.shared],
        )
        team_b = self.manager.create_agent_team(
            self.parent,
            member_configs=self._new_member_configs("PersistB", 2),
            existing_member_ids=[self.shared.agent_id],
        )
        self.shared.append_message(
            {
                "role": "assistant",
                "content": "Cross-team memory",
                "team_id": team_a.team_id,
                "discussion_id": "discussion-a",
            }
        )
        db_path = os.path.join(self.tmpdir, "shared-membership.db")
        await self.manager.save_state(db_path)
        await self.manager.close()

        with closing(sqlite3.connect(db_path)) as connection:
            membership_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(team_members)")
            }
        self.assertEqual(membership_columns, {"team_id", "agent_id"})

        restored = ATTManager(
            Agent("TemporaryRoot", "Architect", self.client),
            ATTConfig(workspace_root=self.tmpdir),
        )
        restored.register_llm_client("shared-model", self.client)
        await restored.load_state(db_path)
        restored_shared = restored._agents_by_id[self.shared.agent_id]

        self.assertIs(restored.agents[self.shared.name], restored_shared)
        self.assertIs(
            next(
                member
                for member in restored.teams[team_a.team_id].members
                if member.agent_id == self.shared.agent_id
            ),
            restored_shared,
        )
        self.assertIs(
            next(
                member
                for member in restored.teams[team_b.team_id].members
                if member.agent_id == self.shared.agent_id
            ),
            restored_shared,
        )
        self.assertEqual(restored_shared.private_doc_library_id, self.shared.private_doc_library_id)
        self.assertEqual(
            sum(
                library.owner_agent_id == self.shared.agent_id
                for library in restored.libraries.values()
            ),
            1,
        )
        self.assertTrue(
            any(
                message.get("content") == "Cross-team memory"
                and message.get("team_id") == team_a.team_id
                and message.get("discussion_id") == "discussion-a"
                for message in restored_shared.message_history
            )
        )
        await restored.close()

    async def test_membership_deltas_only_rewrite_the_team_agent_relation(self):
        self.shared.append_message(
            {
                "role": "assistant",
                "content": "Durable identity state",
                "team_id": self.parent.team_id,
                "discussion_id": "identity-baseline",
            }
        )
        private_library = self.manager.libraries[self.shared.private_doc_library_id]
        private_library.write_file("notes/stable.txt", "persistent private data")
        db_path = os.path.join(self.tmpdir, "membership-delta.db")
        self.manager.db_path = db_path
        await self.manager.save_state()
        before = self._persisted_identity_state(db_path)

        child = self.manager.create_agent_team(
            self.parent,
            member_configs=self._new_member_configs("Relation", 3),
            existing_members=[self.shared],
        )
        await self.manager.flush_state()
        self.assertEqual(self._persisted_identity_state(db_path), before)

        parent_agent = self.parent.members[0]
        membership_tools = get_default_tools(self.manager.tools_context, parent_agent)
        agent_token = self.manager._active_tool_agent.set(parent_agent)
        team_token = self.manager._active_team.set(self.parent)
        try:
            await membership_tools["remove_team_member"](child.team_id, self.shared.name)
        finally:
            self.manager._active_team.reset(team_token)
            self.manager._active_tool_agent.reset(agent_token)
        await self.manager.flush_state()

        self.assertEqual(self._persisted_identity_state(db_path), before)
        with closing(sqlite3.connect(db_path)) as connection:
            membership = connection.execute(
                "SELECT 1 FROM team_members WHERE team_id = ? AND agent_id = ?",
                (child.team_id, self.shared.agent_id),
            ).fetchone()
        self.assertIsNone(membership)

    async def test_persisted_membership_is_independent_of_agent_field_validation(self):
        db_path = os.path.join(self.tmpdir, "membership-isolation.db")
        self.manager.db_path = db_path
        await self.manager.save_state()
        before = self._persisted_identity_state(db_path)

        self.shared.llm_client = EchoClient()
        child = self.manager.create_agent_team(
            self.parent,
            member_configs=self._new_member_configs("Isolation", 2),
            existing_member_ids=[self.shared.agent_id],
        )
        await self.manager.flush_state()

        self.assertIn(self.shared, child.members)
        self.assertEqual(self._persisted_identity_state(db_path), before)

    async def test_dispatch_uses_existing_agent_ids_without_roles(self):
        dispatch_tool = self.parent.tools["dispatch_subagent"]
        schema = dispatch_tool.json_schema
        member_schema = schema["properties"]["member_configs"]["anyOf"][0]
        member_reference = member_schema["additionalProperties"]["$ref"]
        member_definition = schema["$defs"][member_reference.rsplit("/", 1)[-1]]
        self.assertNotIn("hire_agent", member_definition["properties"])
        self.assertIn("existing_member_ids", schema["properties"])

        captured_team = None

        async def capture_discussion(team, prompt, rounds=2):
            nonlocal captured_team
            captured_team = team
            return "captured"

        with patch.object(
            self.manager,
            "execute_team_discussion",
            side_effect=capture_discussion,
        ):
            result = await dispatch_tool(
                task="Use the shared researcher.",
                team_purpose="Role-neutral delegation",
                member_configs=self._new_member_configs("Dispatch", 2),
                existing_member_ids=[self.shared.agent_id],
            )

        self.assertEqual(result, "captured")
        self.assertIsNotNone(captured_team)
        self.assertIs(
            next(
                member
                for member in captured_team.members
                if member.agent_id == self.shared.agent_id
            ),
            self.shared,
        )
        self.assertEqual(self.shared.role, "Researcher")
