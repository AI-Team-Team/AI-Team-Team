"""Unaccepted lifecycle and permission observations cannot escape in another save."""

import asyncio
from unittest.mock import Mock, patch

from ai_team_team import Agent, StatePersistenceError
from test.test_att.test_agent_activity._support import ActivityTestCase


class PublicationSafetyTests(ActivityTestCase):
    async def test_unrelated_full_export_excludes_a_later_rejected_death_event(self):
        person = self.manager.register_agent(Agent("Person", "Researcher", self.client))
        saving_waits, staged, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        original_acquire = self.manager._runtime_gate.acquire
        original_commit = self.manager._records.commit
        saving = None
        path = self.workspace.name + "/concurrent-export.sqlite"
        async def acquire():
            if asyncio.current_task() is saving:
                saving_waits.set()
            return await original_acquire()
        async def commit(records, **kwargs):
            if str(kwargs.get("operation_id", "")).startswith("DEATH-"):
                staged.set()
                await release.wait()
                raise StatePersistenceError("The death was not accepted")
            return await original_commit(records, **kwargs)
        with patch.object(self.manager._runtime_gate, "acquire", acquire), patch.object(self.manager._records, "commit", commit):
            dying = None
            try:
                async with self.manager._runtime_gate:
                    saving = asyncio.create_task(self.manager.save_state(path))
                    await asyncio.wait_for(saving_waits.wait(), 10)
                    dying = asyncio.create_task(self.manager.mark_agent_dead(person.agent_id, confirm=True))
                    await asyncio.wait_for(staged.wait(), 10)
                    self.assertTrue(self.manager._memory.provisional_events)
                    self.assertIn(person.agent_id, {item.agent_id for item in self.manager.list_entities("agent").items})
                await asyncio.wait_for(saving, 10)
                state = await self.manager._persistence.read(path, reconcile=False)
                self.assertFalse(any(event["event_type"] == "agent_lifecycle_changed" and event["payload"].get("lifecycle_state") == "dead"
                                     for event in state["memory_events"]))
                self.assertEqual(next(row["lifecycle_state"] for row in state["agents"] if row["agent_id"] == person.agent_id), "active")
            finally:
                release.set()
                if dying is not None:
                    with self.assertRaises(StatePersistenceError):
                        await dying
        self.assertFalse(self.manager._memory.provisional_events)
        self.assertEqual(person.lifecycle_state, "active")

    async def test_permission_and_protected_notice_share_a_receipt_and_rollback(self):
        self.manager._activity.schedule_notice = Mock()
        first = self.manager.create_agent_team(self.root, parent=self.root)
        second = self.manager.create_agent_team(self.root, parent=self.root)
        library = first.doc_library
        await self.manager._library_service.change_permission(first, library.lib_id, "/", second.team_id, "READ")
        self.assertTrue(self.manager.check_library_access(second.team_id, library.lib_id, "file.txt", "READ"))
        self.assertEqual(len([row for row in self.records("agent_notifications") if row.values["classification"] == "permission"]), 3)
        original = self.manager._records.snapshot()
        with patch.object(self.manager._records, "commit", side_effect=StatePersistenceError("ACL receipt rejected")):
            with self.assertRaises(StatePersistenceError):
                await self.manager._library_service.change_permission(first, library.lib_id, "/", second.team_id, None)
        self.assertTrue(self.manager.check_library_access(second.team_id, library.lib_id, "file.txt", "READ"))
        self.assertEqual(self.manager._records.snapshot(), original)
        self.assertFalse(self.manager._memory.provisional_events)

    async def test_first_permission_delta_captures_the_target_without_rewriting_unrelated_people(self):
        self.manager._activity.schedule_notice = Mock()
        first, second = [self.manager.create_agent_team(self.root, parent=self.root) for _ in range(2)]
        path = self.workspace.name + "/permissions.sqlite"
        # The first export makes durable reference validation observable.
        await self.manager.save_state(path)
        await self.manager.load_state(path)
        self.manager._activity.schedule_notice = Mock()
        first, second = self.manager.teams[first.team_id], self.manager.teams[second.team_id]
        await self.manager._library_service.change_permission(first, first.doc_library.lib_id, "/", second.team_id, "WRITE")
        await self.manager.load_state(path)
        self.assertTrue(self.manager.check_library_access(second.team_id, first.doc_library.lib_id, "/", "WRITE"))
