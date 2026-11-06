"""Host death retains a person while ending only their current authority."""

import asyncio
from unittest.mock import Mock, patch

from ai_team_team import Agent, StatePersistenceError
from ai_team_team.core.exceptions import ToolPermissionError
from test.test_att.test_agent_activity._support import ActivityTestCase
from test.test_att.test_runtime_contracts._fixtures import AsyncBarrier, ModelStep
from test.test_att.test_agent_activity._support import idle
from test.test_att.test_background_tasks._support import contract


class DeathTests(ActivityTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.person = self.manager.register_agent(Agent("Person", "Researcher", self.client))
        self.manager._activity.schedule_notice = Mock()

    async def test_death_is_explicit_host_only_terminal_and_preserves_private_artifacts(self):
        library = self.manager.libraries[self.person.private_doc_library_id]
        library.write_file("notes.md", "Retained private notes")
        with self.assertRaisesRegex(ValueError, "confirm=True"):
            await self.manager.mark_agent_dead(self.person.agent_id)
        with self.assertRaisesRegex(ValueError, "Root"):
            await self.manager.mark_agent_dead(self.root.agent_id, confirm=True)
        token = self.manager._active_tool_agent.set(self.root)
        try:
            with self.assertRaises(ToolPermissionError):
                await self.manager.mark_agent_dead(self.person.agent_id, confirm=True)
        finally:
            self.manager._active_tool_agent.reset(token)
        result = await self.manager.mark_agent_dead(self.person.agent_id, confirm=True)
        self.assertEqual(result["state"], "dead")
        self.assertIs(self.manager._agents_by_id[self.person.agent_id], self.person)
        self.assertNotIn(self.person.name, self.manager.agents)
        self.assertEqual(library.read_file("notes.md"), "Retained private notes")
        with self.assertRaises(PermissionError):
            library.write_file("notes.md", "No write")
        with self.assertRaisesRegex(ValueError, "terminal"):
            await self.manager.reactivate_agent(self.person.agent_id, "fixture")
        with self.assertRaises(PermissionError):
            await self.manager.activate_agent(self.person.agent_id)
        self.assertEqual((await self.manager.mark_agent_dead(self.person.agent_id, confirm=True))["state"], "dead")

    async def test_member_and_creator_death_preserves_teams_and_detaches_only_direct_children(self):
        team = self.manager.bootstrap_agent_team(self.person, existing_members=[self.person], parent=self.person,
            member_configs={"Peer1": {"model": "fixture"}, "Peer2": {"model": "fixture"}})
        child = self.manager.create_agent_team(team, parent=team)
        owned_fields = (self.root.messages, self.root.system_instructions, self.root.private_doc_library_id)
        await self.manager.mark_agent_dead(self.person.agent_id, confirm=True)
        self.assertIs(team.creator, self.person)
        self.assertNotIn(self.person, team.members)
        self.assertEqual(len(team.members), 2)
        self.assertIsNone(team.organizational_parent)
        self.assertIs(child.parent_team, team)
        self.assertEqual(getattr(team, "_lifecycle_state", "active"), "active")
        self.assertEqual(owned_fields, (self.root.messages, self.root.system_instructions, self.root.private_doc_library_id))

    async def test_failed_death_receipt_preserves_identity_memberships_and_parent(self):
        team = self.manager.bootstrap_agent_team(self.person, parent=self.person, existing_members=[self.person],
            member_configs={"Peer1": {"model": "fixture"}, "Peer2": {"model": "fixture"}})
        before = self.manager._records.snapshot()
        with patch.object(self.manager._records, "commit", side_effect=StatePersistenceError("Rejected death")):
            with self.assertRaises(StatePersistenceError):
                await self.manager.mark_agent_dead(self.person.agent_id, confirm=True)
        self.assertEqual(self.person.lifecycle_state, "active")
        self.assertIn(self.person, team.members)
        self.assertEqual(team.organizational_parent.principal_id, self.person.agent_id)
        self.assertEqual(before, self.manager._records.snapshot())
        self.assertFalse(self.manager._agent_registry.lifecycle_pending)

    async def test_active_invocation_is_cancelled_without_an_idle_lock_requirement(self):
        barrier = AsyncBarrier()
        self.client.steps.append(ModelStep(idle(), barrier))
        admission = await self.manager.activate_agent(self.person.agent_id)
        await barrier.wait_entered()
        self.assertTrue(self.person.lock.locked())
        try:
            result = await asyncio.wait_for(self.manager.mark_agent_dead(self.person.agent_id, confirm=True), 10)
            self.assertEqual(result["state"], "dead")
            await asyncio.gather(*tuple(self.manager._activity.workers), return_exceptions=True)
            self.assertEqual(self.manager._records.index[("activity_admissions", (admission.admission_id,))].values["disposition"], "cancelled")
            self.assertEqual(len(self.client.requests), 1)
        finally:
            barrier.release()

    async def test_creator_retirement_does_not_reassign_historical_identity(self):
        team = self.manager.create_agent_team(self.person, parent=self.person)
        await self.manager.retire_agent(self.person.agent_id, policy="archive")
        self.assertIs(team.creator, self.person)
        self.assertIsNone(team.organizational_parent)
        self.assertEqual(self.person.lifecycle_state, "archived")
        await self.manager.reactivate_agent(self.person.agent_id, "fixture")
        self.assertIs(team.creator, self.person)

    async def test_accepted_death_stops_the_owner_even_when_its_caller_sees_a_handoff_failure(self):
        barrier = AsyncBarrier()
        self.client.steps.append(ModelStep(idle(), barrier))
        await self.manager.activate_agent(self.person.agent_id)
        await barrier.wait_entered()
        original_commit = self.manager._records.commit
        async def fail_after_receipt(*args, **kwargs):
            receipt = await original_commit(*args, **kwargs)
            if kwargs.get("agent_lifecycles", {}).get(self.person.agent_id) == "dead":
                raise RuntimeError("Injected handoff failure after the death receipt")
            return receipt
        try:
            with patch.object(self.manager._records, "commit", fail_after_receipt):
                with self.assertRaisesRegex(RuntimeError, "handoff failure"):
                    await self.manager.mark_agent_dead(self.person.agent_id, confirm=True)
            await asyncio.gather(*tuple(self.manager._activity.workers), return_exceptions=True)
            self.assertEqual(self.person.lifecycle_state, "dead")
            self.assertFalse(self.manager._activity.sessions[self.person.agent_id].active)
            self.assertFalse(self.manager._agent_registry.lifecycle_pending)
            self.assertEqual(len(self.client.requests), 1)
        finally:
            barrier.release()

    async def test_dead_identity_round_trip_requires_no_model_binding_and_never_wakes(self):
        path = self.workspace.name + "/retained-death.sqlite"
        await self.manager.mark_agent_dead(self.person.agent_id, confirm=True)
        await self.manager.save_state(path)
        await self.manager.load_state(path)
        restored = self.manager._agents_by_id[self.person.agent_id]
        self.assertEqual(restored.lifecycle_state, "dead")
        self.assertIsNone(restored.llm_client)
        with self.assertRaisesRegex(ValueError, "terminal"):
            await self.manager.reactivate_agent(restored.agent_id, "fixture")
        self.assertFalse(self.client.requests)

    async def test_queued_owned_execution_is_cancelled_without_dispatch(self):
        dispatched = Mock()
        async def execute():
            dispatched()
            return "done"
        self.manager.register_tool("queued_work", func=execute, execution_contract=contract())
        with patch.object(self.manager._executions, "enqueue"):
            handle = await self.manager.start_background_task("queued_work", {}, actor=self.person)
        result = await self.manager.mark_agent_dead(self.person.agent_id, confirm=True)
        self.assertEqual(result["tasks"][0]["status"], "CANCELLED")
        self.assertEqual(self.manager._records.index[("executions", (handle.execution_id,))].values["status"], "cancelled")
        dispatched.assert_not_called()
