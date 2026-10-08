"""Relationship mutations preserve the same continuing person's owned state."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_team_team import ATTConfig, ATTManager, Agent
from ai_team_team.tool import get_default_tools

from test.test_att.test_autonomous_activity_phase0._fixtures import (
    AgentIdentitySnapshot,
    ScriptedModelClient,
)


class TestRelationshipIdentitySnapshots(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.workspace = tempfile.TemporaryDirectory(prefix="att-phase0-identity-")
        self.addCleanup(self.workspace.cleanup)
        self.client = ScriptedModelClient()
        self.root = Agent("Root", "Architect", self.client)
        self.manager = ATTManager(self.root, ATTConfig(workspace_root=self.workspace.name))
        self.addAsyncCleanup(self.manager.close)
        self.manager.register_llm_client("fixture", self.client)
        self.person = Agent(
            "Mira",
            "Researcher",
            self.client,
            system_instructions="Continuing personal instructions.",
        )
        self.manager.register_agent(self.person)
        self.person.messages.append({"role": "user", "content": "Continuing working context."})
        self.person.last_context = {"personal_plan": ["retain this plan"]}
        self.manager._inbox.notify(self.person.agent_id, "personal_note", {"note": "retained"})
        self.manager.libraries[self.person.private_doc_library_id].write_file(
            "notes.txt", "private"
        )
        self.parent = self.manager.create_agent_team(self.root)

    def make_team(self, prefix):
        return self.manager.bootstrap_agent_team(
            self.parent,
            member_configs={f"{prefix}{number}": {"model": "fixture"} for number in range(3)},
            existing_member_ids=[self.person.agent_id],
        )

    async def test_join_shared_memberships_and_leave_preserve_every_owned_field(self):
        before = AgentIdentitySnapshot.capture(self.person, self.manager)
        first = self.make_team("First")
        second = self.make_team("Second")
        self.assertEqual(AgentIdentitySnapshot.capture(self.person, self.manager), before)
        self.assertIs(
            next(member for member in first.members if member is self.person), self.person
        )
        self.assertIs(
            next(member for member in second.members if member is self.person), self.person
        )

        actor = self.parent.members[0]
        tools = get_default_tools(self.manager.tools_context, actor)
        actor_token = self.manager._active_tool_agent.set(actor)
        scope_token = self.manager._active_team.set(self.parent)
        try:
            result = await tools["remove_team_member"](first.team_id, self.person.name)
        finally:
            self.manager._active_team.reset(scope_token)
            self.manager._active_tool_agent.reset(actor_token)
        self.assertIn("Successfully removed", result)
        self.assertNotIn(self.person, first.members)
        self.assertIn(self.person, second.members)
        self.assertEqual(AgentIdentitySnapshot.capture(self.person, self.manager), before)
        self.assertEqual(self.client.requests, [])

    def test_snapshot_is_nonmutating_and_detects_equal_container_replacement(self):
        self.assertIsNone(self.person._lock)
        before = AgentIdentitySnapshot.capture(self.person, self.manager)
        self.assertIsNone(self.person._lock)
        self.person.messages = list(self.person.messages)
        self.assertNotEqual(AgentIdentitySnapshot.capture(self.person, self.manager), before)

    def test_snapshot_detects_private_artifact_change_without_logging_body(self):
        before = AgentIdentitySnapshot.capture(self.person, self.manager)
        self.manager.libraries[self.person.private_doc_library_id].write_file(
            "notes.txt", "changed"
        )
        after = AgentIdentitySnapshot.capture(self.person, self.manager)
        self.assertNotEqual(after, before)
        self.assertNotIn("changed", repr(after.private_entries))

    def test_snapshot_records_links_without_reading_their_targets(self):
        library = self.manager.libraries[self.person.private_doc_library_id]
        target = Path(self.workspace.name) / "outside-private-library.txt"
        link = Path(library.root_dir) / "external-link.txt"
        link.symlink_to(target)
        original_read = Path.read_bytes

        def reject_link_read(path):
            if path.is_symlink():
                raise AssertionError("Identity snapshots must not follow symbolic links.")
            return original_read(path)

        with patch.object(Path, "read_bytes", autospec=True, side_effect=reject_link_read):
            snapshot = AgentIdentitySnapshot.capture(self.person, self.manager)
        self.assertIn(("external-link.txt", ("symlink", str(target))), snapshot.private_entries)

    def test_snapshot_failure_representation_does_not_expose_personal_content(self):
        secret = "PRIVATE_AGENT_CONTENT_NEVER_LOGGED"
        self.person.messages.append({"role": "user", "content": secret})
        self.person.last_context["private_note"] = secret.encode("utf-8")
        snapshot = AgentIdentitySnapshot.capture(self.person, self.manager)
        self.assertNotIn(secret, repr(snapshot))
        self.person.messages[-1]["content"] = secret + "-changed"
        self.assertNotEqual(AgentIdentitySnapshot.capture(self.person, self.manager), snapshot)
