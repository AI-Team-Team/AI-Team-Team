"""Explicit-parent migration tools preserve accepted topology and person identity."""

import json
import tempfile
import unittest

from ai_team_team import ATTConfig, ATTManager, Agent
from ai_team_team.core.tool_runtime import ToolExecutor
from test.governance_client import PersonalGovernanceClient, settle_governance_activity


class TestATTMigration(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        workspace = tempfile.TemporaryDirectory(prefix="att-migration-tools-")
        self.addCleanup(workspace.cleanup)
        client = PersonalGovernanceClient()
        self.root = Agent("Root", "Architect", client)
        self.manager = ATTManager(self.root, ATTConfig(workspace_root=workspace.name), persistence_mode="volatile")
        self.manager.register_llm_client("default", client)
        self.addAsyncCleanup(self.manager.close)

    async def request(self, team, target, reason):
        return await ToolExecutor(team, team.members[0], self.manager).execute(
            "request_migration", kwargs={"target_parent": {"kind": "agent_team", "principal_id": target.team_id},
                "rationale": reason}, tools=team.tools)

    async def test_migration_commits_once_and_notifies_affected_people(self):
        first = self.manager.create_agent_team(self.root, parent=self.root)
        moving = first.members[0].launch_att(self.manager, parent=first)
        second = self.manager.create_agent_team(self.root, parent=self.root)
        identities = [(person.agent_id, person.role, person.private_doc_library_id) for person in moving.members]
        events = []
        self.manager.on_system_event = lambda event, details: events.append((event, details))
        response = await self.request(moving, second, "Choose the second organization.")
        handle = json.loads(response.content)
        self.assertEqual(handle["status"], "PENDING")
        await settle_governance_activity(self.manager)
        await self.manager.flush_callbacks()
        self.assertEqual(self.manager.inspect_migration_request(handle["request_id"]).status, "EXECUTED")
        self.assertIs(moving.parent_team, second)
        self.assertIn(moving, second.child_teams)
        self.assertNotIn(moving, first.child_teams)
        self.assertEqual([(person.agent_id, person.role, person.private_doc_library_id) for person in moving.members], identities)
        resolutions = [details for event, details in events if event == "migration_request_resolved"
            and details["request_id"] == handle["request_id"]]
        self.assertEqual(len(resolutions), 1)
        for person in [*first.members, *second.members, *moving.members]:
            notices = [mail for mail in person.agent_inbox if mail["message_type"] == "organizational_position_changed"
                and mail["payload"]["team_id"] == moving.team_id]
            self.assertEqual(len(notices), 1)
        denied = json.loads((await self.request(moving, first, "Move back immediately.")).content)
        self.assertEqual(denied["status"], "DENIED")
        self.assertIn("cooldown", denied["reason"])

    async def test_descendant_attachment_is_rejected_before_creating_any_request(self):
        parent = self.manager.create_agent_team(self.root, parent=self.root)
        child = parent.members[0].launch_att(self.manager, parent=parent)
        result = json.loads((await self.request(parent, child, "Invalid cycle.")).content)
        self.assertEqual(result["status"], "DENIED")
        self.assertIn("cycle", result["reason"])
        self.assertFalse(self.manager._migration.requests)
        self.assertIs(child.parent_team, parent)
