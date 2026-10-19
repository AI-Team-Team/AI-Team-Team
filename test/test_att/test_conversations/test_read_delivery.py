"""Cancelled Host reads and cancelled Native batches never acknowledge unseen bodies."""

import asyncio
import threading
from unittest.mock import patch

from ai_team_team import Agent, LLMResponse, ToolCall, StateRestoreError
from test.test_att.test_autonomous_activity_phase0._fixtures import AsyncBarrier
from test.test_att.test_agent_activity._support import ActivityTestCase, call, idle
from ._support import ChatTestCase


class HostReadDeliveryTests(ChatTestCase):
    async def test_restore_cannot_cross_an_unfinished_host_read_delivery(self):
        source = await self.manager.send_direct_message(self.other.agent_id, "A pending Host read", actor=self.root)
        await self.manager.save_state()
        barrier = AsyncBarrier()
        original = self.manager._library_service._read_model_file

        async def paused(*args, **kwargs):
            await barrier.pause()
            return await original(*args, **kwargs)

        with patch.object(self.manager._library_service, "_read_model_file", paused):
            reading = asyncio.create_task(self.manager.read_chat_message(source.message_id, actor=self.other))
            try:
                await barrier.wait_entered()
                with self.assertRaisesRegex(StateRestoreError, "read delivery"):
                    await self.manager.load_state(self.path)
            finally:
                barrier.release()
            self.assertIn("pending Host read", (await reading).content)
        self.assertFalse(self.manager._messaging.read_deliveries)
        await self.manager.load_state(self.path)

    async def test_cancelled_read_restores_the_exact_previous_watermark_and_unread_override(self):
        for previously_read in (False, True):
            with self.subTest(previously_read=previously_read):
                item = await self.manager.send_direct_message(self.other.agent_id, "Only a delivered body is read", actor=self.root)
                if previously_read:
                    await self.manager.read_chat_message(item.message_id, actor=self.other)
                    await self.manager.control_chat_message("mark_message_unread", item.message_id, actor=self.other)
                view = self.manager._messaging.view(self.other, item.message_id)
                expected = {key: view.values[key] for key in ("read_at", "read_revision_number", "unread_override")}
                await self.manager.save_state()
                entered, release = threading.Event(), threading.Event()
                store = self.manager._persistence._store(self.path)
                original = store.write

                def slow(snapshot):
                    entered.set()
                    if not release.wait(10):
                        raise TimeoutError("The test did not release the read writer.")
                    return original(snapshot)

                with patch.object(store, "write", slow):
                    reading = asyncio.create_task(self.manager.read_chat_message(item.message_id, actor=self.other))
                    try:
                        self.assertTrue(await asyncio.to_thread(entered.wait, 5))
                        reading.cancel()
                        await asyncio.sleep(0)
                        reading.cancel()
                    finally:
                        release.set()
                    with self.assertRaises(asyncio.CancelledError):
                        await reading
                current = self.manager._messaging.view(self.other, item.message_id)
                self.assertEqual({key: current.values[key] for key in expected}, expected)
        await self.manager.load_state(self.path)
        peer = self.manager._agents_by_id[self.other.agent_id]
        self.assertEqual(self.manager.list_direct_messages(self.manager.root_ai.agent_id, actor=peer).unread_count, 2)


class RuntimeReadDeliveryTests(ActivityTestCase):
    async def source(self):
        peer = self.manager.register_agent(Agent("Sender", "Researcher", self.client))
        with patch.object(self.manager._activity, "schedule_notice"):
            source = await self.manager.send_direct_message(self.root.agent_id, "Explicitly delivered observation", actor=peer)
        return peer, source

    async def test_text_and_native_reads_are_acknowledged_with_the_observation(self):
        for native in (False, True):
            with self.subTest(native=native):
                # Reuse the continuing person, but address a different source.
                self.manager.config.tool_calling_mode = "native" if native else "text_react"
                peer = self.manager.register_agent(Agent(f"Sender-{native}", "Researcher", self.client))
                with patch.object(self.manager._activity, "schedule_notice"):
                    source = await self.manager.send_direct_message(self.root.agent_id, "Delivered through a checkpoint", actor=peer)
                reading = call("read_chat_message", {"message_id": source.message_id}) if native else LLMResponse(
                    text=f"Action: read_chat_message(message_id={source.message_id!r})")
                self.steps(reading, idle(native=native))
                admission = await self.manager.activate_agent(self.root.agent_id)
                await self.wait(admission)
                await self.settle()
                self.assertEqual(self.manager.list_direct_messages(peer.agent_id, actor=self.root).unread_count, 0)
                self.assertTrue(any(message.get("source_chat_message_id") == source.message_id
                    and "Delivered through a checkpoint" in message["content"] for message in self.root.message_history))
                session = self.manager._activity.sessions[self.root.agent_id]
                self.assertFalse(session.prepared_chat_reads)
                self.assertFalse(session.pending_chat_read_acknowledgements)

    async def test_cancelled_native_sibling_does_not_mark_a_prepared_body_read(self):
        peer, source = await self.source()
        completed = asyncio.Event()
        original = self.manager._activity.execute_tool

        async def tracked(session, name, *args, **kwargs):
            result = await original(session, name, *args, **kwargs)
            if name == "read_chat_message":
                completed.set()
            return result

        async def cancel_batch() -> str:
            await completed.wait()
            raise asyncio.CancelledError("Cancel before observation delivery")

        self.manager.register_tool("cancel_read_batch", func=cancel_batch)
        self.steps(LLMResponse(tool_calls=[ToolCall("read", "read_chat_message", {"message_id": source.message_id}),
                                          ToolCall("cancel", "cancel_read_batch", {})]))
        with patch.object(self.manager._activity, "execute_tool", tracked):
            admission = await self.manager.activate_agent(self.root.agent_id)
            with self.assertRaises(asyncio.CancelledError):
                await self.wait(admission)
            await asyncio.gather(*tuple(self.manager._activity.workers), return_exceptions=True)
        self.assertTrue(completed.is_set())
        self.assertEqual(self.manager.list_direct_messages(peer.agent_id, actor=self.root).unread_count, 1)
        self.assertFalse(any(message.get("source_chat_message_id") == source.message_id for message in self.root.message_history))
        session = self.manager._activity.sessions[self.root.agent_id]
        self.assertFalse(session.prepared_chat_reads)
        self.assertFalse(session.pending_chat_read_acknowledgements)

    async def test_a_new_revision_during_batch_settlement_remains_unread(self):
        peer, source = await self.source()
        prepared, release = asyncio.Event(), asyncio.Event()
        original = self.manager._activity.execute_tool

        async def paused(session, name, *args, **kwargs):
            result = await original(session, name, *args, **kwargs)
            if name == "read_chat_message":
                prepared.set()
                await release.wait()
            return result

        self.steps(call("read_chat_message", {"message_id": source.message_id}), idle())
        with patch.object(self.manager._activity, "execute_tool", paused):
            admission = await self.manager.activate_agent(self.root.agent_id)
            try:
                await asyncio.wait_for(prepared.wait(), 10)
                self.assertEqual(self.manager.list_direct_messages(peer.agent_id, actor=self.root).unread_count, 1)
                await self.manager.edit_chat_message(source.message_id, "New content after the prepared V1 read", actor=peer)
            finally:
                release.set()
            await self.wait(admission)
            await self.settle()
        view = self.manager._messaging.view(self.root, source.message_id)
        self.assertEqual(view.values["read_revision_number"], 1)
        self.assertEqual(self.manager.list_direct_messages(peer.agent_id, actor=self.root).unread_count, 1)

    async def test_multiple_reads_of_one_view_in_a_native_batch_share_one_acknowledgement_projection(self):
        peer, source = await self.source()
        self.steps(LLMResponse(tool_calls=[ToolCall(f"read-{index}", "read_chat_message", {"message_id": source.message_id})
                                         for index in range(2)]), idle())
        admission = await self.manager.activate_agent(self.root.agent_id)
        await self.wait(admission)
        await self.settle()
        view = self.manager._messaging.view(self.root, source.message_id)
        self.assertEqual(view.values["read_revision_number"], 1)
        self.assertEqual(view.version, 2)
        self.assertEqual(self.manager.list_direct_messages(peer.agent_id, actor=self.root).unread_count, 0)
