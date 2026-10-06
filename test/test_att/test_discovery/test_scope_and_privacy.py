"""Lifecycle eligibility, system-entity exclusion, and private-state boundaries."""

import asyncio
import copy
import unittest

from pydantic import ValidationError

from ai_team_team import ToolBusinessError, ToolPermissionError

from ._fixture import DiscoveryFixture


class DiscoveryScopeTests(DiscoveryFixture, unittest.IsolatedAsyncioTestCase):
    async def test_root_idle_busy_and_dependency_chain_agents_remain_discoverable(self):
        idle = self.person("Idle")
        busy = self.person("Busy")
        await busy.lock.acquire()
        chain = self.manager._agent_invocation_chain.set(((busy.agent_id, "busy-invocation"),))
        self.manager._active_agent_invocation_tokens.add("busy-invocation")
        try:
            async with asyncio.timeout(1):
                page = self.manager.list_entities("agent")
                self.assertEqual(
                    {record.agent_id for record in page.items},
                    {self.root.agent_id, idle.agent_id, busy.agent_id},
                )
                self.assertEqual(self.manager.inspect_entity("agent", busy.agent_id).name, "Busy")
        finally:
            busy.lock.release()
            self.manager._agent_invocation_chain.reset(chain)
            self.manager._active_agent_invocation_tokens.remove("busy-invocation")

    async def test_inactive_deleted_and_audit_entities_are_excluded_from_every_operation(self):
        archived = self.person("Archived")
        retained = self.person("Retained")
        deleted = self.person("Deleted")
        await self.manager.retire_agent(archived.agent_id, "archive")
        await self.manager.retire_agent(retained.agent_id, "retain")
        await self.manager.retire_agent(deleted.agent_id, "delete", confirm_delete=True)
        audit = self.manager._team_creation.create_supervisory_team()
        try:
            excluded = {archived.agent_id, retained.agent_id, deleted.agent_id}
            excluded.update(agent.agent_id for agent in audit.members)
            page = self.manager.list_entities(end_index=999)
            self.assertEqual([record.agent_id for record in page.items], [self.root.agent_id])
            for identifier in excluded:
                self.assertEqual(self.manager.search_entities([identifier]).items, [])
                with self.assertRaises(KeyError):
                    self.manager.inspect_entity("agent", identifier)
            self.assertEqual(self.manager.search_entities([audit.team_id]).items, [])
            with self.assertRaises(KeyError):
                self.manager.inspect_entity("agent_team", audit.team_id)
        finally:
            await self.manager._team_creation.dissolve_supervisory_team(audit, persist=False)
        await self.manager.reactivate_agent(archived.agent_id, "default")
        self.assertEqual(self.manager.inspect_entity("agent", archived.agent_id).name, "Archived")

    async def test_directory_contains_no_private_fields_or_hidden_content_search(self):
        person = self.person("Public", description="Public database description")
        secret = "PRIVATE_SECRET_NOT_DIRECTORY_DATA"
        person.system_instructions = secret
        person.append_message({"role": "assistant", "content": secret})
        self.manager.libraries[person.private_doc_library_id].write_file("private.txt", secret)
        record = self.manager.inspect_entity("agent", person.agent_id)
        self.assertEqual(
            set(record.model_dump()),
            {"entity_type", "agent_id", "name", "role", "role_description"},
        )
        self.assertNotIn(secret, record.model_dump_json())
        self.assertEqual(self.manager.search_entities([secret]).items, [])
        self.assertEqual(self.manager.search_entities([person.private_doc_library_id]).items, [])
        with self.assertRaises(ValidationError):
            record.role = "Changed"
        self.assertEqual(person.role, "Researcher")

    async def test_topology_is_public_across_branches_and_depth_caches_are_not_mutated(self):
        first = self.manager.create_agent_team(self.root)
        second = self.manager.create_agent_team(self.root)
        child = self.manager.create_agent_team(first, team_purpose="Distant research")
        for team in (first, second, child):
            team._cached_depth = None
        state = self.manager._state_version
        before = dict(self.root.__dict__)
        history = copy.deepcopy(self.root.messages)
        record = self.manager.inspect_entity("agent_team", child.team_id)
        self.assertEqual((record.parent_team_id, record.depth), (first.team_id, 2))
        self.assertEqual(
            {item.team_id for item in self.manager.list_entities("agent_team").items},
            {first.team_id, second.team_id, child.team_id},
        )
        self.assertTrue(all(team._cached_depth is None for team in (first, second, child)))
        self.assertEqual(self.manager._state_version, state)
        self.assertEqual(self.root.messages, history)
        self.assertEqual(self.root.__dict__, before)
        self.assertEqual(
            set(record.model_dump()),
            {"entity_type", "team_id", "team_purpose", "team_progress", "parent_team_id", "depth"},
        )
        self.assertFalse(child.doc_library.is_public_visible)

    async def test_tools_require_active_identity_but_no_agent_team_or_target_actor_override(self):
        tools = self.manager.get_available_tools(None, self.root)
        names = {"list_entities", "search_entities", "inspect_entity"}
        self.assertTrue(names <= tools.keys())
        with self.assertRaises(ToolPermissionError):
            await tools["list_entities"].invoke()
        token = self.manager._active_tool_agent.set(self.root)
        try:
            page = await tools["list_entities"].invoke()
            self.assertEqual(page.items[0].agent_id, self.root.agent_id)
            with self.assertRaises(ToolBusinessError):
                await tools["inspect_entity"].invoke(entity_type="agent", entity_id="missing")
            self.assertIsNone(self.manager._active_team.get())
        finally:
            self.manager._active_tool_agent.reset(token)

    async def test_shared_person_has_one_directory_record_and_unchanged_personal_state(self):
        members = [self.person(f"Shared{index}") for index in range(3)]
        first = self.manager.bootstrap_agent_team(self.root, existing_members=members)
        second = self.manager.bootstrap_agent_team(self.root, existing_members=members)
        person = members[0]
        person.append_message({"role": "assistant", "content": "Continuing personal experience."})
        before = dict(person.__dict__)
        messages = copy.deepcopy(person.messages)
        page = self.manager.search_entities([person.agent_id], entity_type="agent")
        self.assertEqual(page.total_results, 1)
        self.assertEqual(page.items[0].agent_id, person.agent_id)
        self.assertIs(first.members[0], second.members[0])
        self.assertEqual(person.__dict__, before)
        self.assertEqual(person.messages, messages)

    async def test_migration_is_reflected_in_next_directory_query_without_cached_depth(self):
        self.manager.config.migration_policy = "permissive"
        first = self.manager.create_agent_team(self.root)
        second = self.manager.create_agent_team(self.root)
        child = self.manager.create_agent_team(first)
        before = self.manager.inspect_entity("agent_team", second.team_id)
        self.assertEqual((before.parent_team_id, before.depth), (None, 1))
        result = await self.manager.negotiate_and_execute_migration(
            second, child, "Move this team below another branch."
        )
        self.assertEqual(result.status, "EXECUTED")
        second._cached_depth = 999
        current = self.manager.inspect_entity("agent_team", second.team_id)
        self.assertEqual((current.parent_team_id, current.depth), (child.team_id, 3))
        self.assertEqual(second._cached_depth, 999)
        page = self.manager.search_entities([child.team_id], entity_type="agent_team")
        self.assertIn(second.team_id, [record.team_id for record in page.items])
