"""Directory knowledge never supplies consent, an Agreement, or document ACLs."""

import asyncio
import json
import os
import unittest

from ai_team_team import ParentApprovalCommunicationConfig, TeamFormationRequest
from ai_team_team.core.tool_runtime import ToolExecutor

from ._fixture import DiscoveryFixture


class DiscoveryAuthorityTests(DiscoveryFixture, unittest.IsolatedAsyncioTestCase):
    async def test_discovery_does_not_create_membership_consent(self):
        invitees = [self.person(f"Invitee{index}") for index in range(3)]
        for person in invitees:
            self.manager.inspect_entity("agent", person.agent_id)
        request = self.manager.create_agent_team(self.root, existing_members=invitees)
        self.assertIsInstance(request, TeamFormationRequest)
        self.assertEqual(len(self.manager.teams), 0)
        self.assertEqual(
            [
                self.manager.get_team_formation_invitation(
                    request.request_id, person.agent_id
                ).attitude.value
                for person in invitees
            ],
            ["no_response"] * 3,
        )

    async def test_discovering_a_team_does_not_grant_communication_or_document_access(self):
        self.manager.config.communication = ParentApprovalCommunicationConfig()
        first = self.manager.create_agent_team(self.root)
        second = self.manager.create_agent_team(self.root)
        self.manager.inspect_entity("agent_team", second.team_id)
        sent = await self.manager.broker.send_peer_message(
            first, second, first.members[0].agent_id, "A message without an Agreement."
        )
        self.assertEqual(sent.status, "NO_AGREEMENT")
        self.assertFalse(self.manager.broker.communication_requests)
        self.assertFalse(self.manager.broker.agreements)
        second.doc_library.write_file("private-team.txt", "Private team artifact")
        tools = self.manager.get_available_tools(first)
        result = await ToolExecutor(first, first.members[0], self.manager).execute(
            "read_library_file",
            kwargs={"lib_id": second.doc_library.lib_id, "path": "private-team.txt"},
            tools=tools,
        )
        self.assertNotIn("Private team artifact", result.content)
        self.assertNotEqual(result.status.value, "success")

    async def test_snapshot_metadata_stays_internally_consistent_during_parallel_queries_and_changes(
        self,
    ):
        async def add_people():
            for index in range(20):
                self.person(f"Added{index:02}")
                await asyncio.sleep(0)

        async def query():
            for _ in range(20):
                page = self.manager.list_entities("agent", end_index=999)
                self.assertEqual(page.total_results, len(page.items))
                self.assertEqual(page.returned_count, len(page.items))
                self.assertEqual(page.actual_end_index, page.total_results)
                self.assertEqual(page.maximum_index, page.total_results)
                await asyncio.sleep(0)

        await asyncio.gather(add_people(), query(), query())

    async def test_round_trip_uses_restored_registries_without_a_persisted_discovery_index(self):
        person = self.person("RestoredResearcher", description="Public database expertise")
        first = self.manager.create_agent_team(self.root)
        child = self.manager.create_agent_team(first, team_purpose="Restored research team")
        before = self.manager.list_entities(end_index=999).model_dump()
        path = os.path.join(self.workspace.name, "state.sqlite")
        await self.manager.save_state(path)
        await self.manager.load_state(path)
        self.assertEqual(self.manager.list_entities(end_index=999).model_dump(), before)
        self.assertEqual(
            self.manager.inspect_entity("agent", person.agent_id).name, "RestoredResearcher"
        )
        self.assertEqual(
            self.manager.inspect_entity("agent_team", child.team_id).parent_team_id, first.team_id
        )
        tools = self.manager.get_available_tools(self.manager.teams[first.team_id])
        result = await ToolExecutor(
            self.manager.teams[first.team_id],
            self.manager.teams[first.team_id].members[0],
            self.manager,
        ).execute("search_entities", kwargs={"keywords": ["database"]}, tools=tools)
        self.assertEqual(json.loads(result.content)["items"][0]["agent_id"], person.agent_id)
