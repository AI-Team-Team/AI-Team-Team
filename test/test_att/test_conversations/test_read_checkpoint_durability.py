"""Real SQLite commits bind returned tool bodies and read acknowledgements together."""

import asyncio
import threading
from unittest.mock import patch

from ai_team_team import Agent
from test.test_att.test_agent_activity._support import ActivityTestCase, call, idle


class ReadCheckpointDurabilityTests(ActivityTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        await self.manager.close()
        self.manager = self.make_manager(self.root, durable=True)
        self.peer = self.manager.register_agent(Agent("Sender", "Researcher", self.client))
        with patch.object(self.manager._activity, "schedule_notice"):
            self.source = await self.manager.send_direct_message(self.root.agent_id, "A durable body observation", actor=self.peer)
        await self.manager.save_state()

    async def test_read_marker_and_observation_share_the_same_writer_snapshot(self):
        snapshots = []
        store = self.manager._persistence._store(self.manager.db_path)
        original = store.write

        def inspect(snapshot):
            if any(row.table_name == "chat_personal_views" and row.values["agent_id"] == self.root.agent_id
                   and row.values["read_revision_number"] for row in snapshot.get("records", ())):
                snapshots.append(snapshot)
            return original(snapshot)

        self.steps(call("read_chat_message", {"message_id": self.source.message_id}), idle())
        with patch.object(store, "write", inspect):
            admission = await self.manager.activate_agent(self.root.agent_id)
            await self.wait(admission)
            await self.settle()
        self.assertTrue(snapshots)
        for snapshot in snapshots:
            self.assertTrue(any(agent["agent_id"] == self.root.agent_id and any(
                message.get("source_chat_message_id") == self.source.message_id
                and "A durable body observation" in message["content"] for message in agent["messages"]
            ) for agent in snapshot["agents"]))
        await self.manager.load_state(self.manager.db_path)
        self.assertEqual(self.manager.list_direct_messages(self.peer.agent_id, actor=self.manager.root_ai).unread_count, 0)

    async def test_cancel_after_observation_acceptance_preserves_both_the_body_and_its_read_fact(self):
        entered, release = threading.Event(), threading.Event()
        store = self.manager._persistence._store(self.manager.db_path)
        original = store.write

        def slow(snapshot):
            if any(row.table_name == "chat_personal_views" and row.values["agent_id"] == self.root.agent_id
                   and row.values["read_revision_number"] for row in snapshot.get("records", ())):
                entered.set()
                if not release.wait(10):
                    raise TimeoutError("The test did not release the observation writer.")
            return original(snapshot)

        self.steps(call("read_chat_message", {"message_id": self.source.message_id}))
        with patch.object(store, "write", slow):
            admission = await self.manager.activate_agent(self.root.agent_id)
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 5))
                worker = next(iter(self.manager._activity.workers))
                worker.cancel()
                await asyncio.sleep(0)
                worker.cancel()
            finally:
                release.set()
            with self.assertRaises(asyncio.CancelledError):
                await self.wait(admission)
            await asyncio.gather(*tuple(self.manager._activity.workers), return_exceptions=True)
            await asyncio.sleep(0)
        self.assertFalse(self.manager._activity.workers)
        self.assertFalse(self.manager._activity.dispatch_tasks)
        self.assertFalse(self.manager._activity.models.tasks)
        self.assertFalse(self.manager._activity.tool_tasks)
        self.assertFalse(any(session.active for session in self.manager._activity.sessions.values()))
        await self.manager.load_state(self.manager.db_path)
        self.assertEqual(self.manager.list_direct_messages(self.peer.agent_id, actor=self.manager.root_ai).unread_count, 0)
        self.assertTrue(any(message.get("source_chat_message_id") == self.source.message_id
            and "A durable body observation" in message["content"] for message in self.manager.root_ai.messages))
