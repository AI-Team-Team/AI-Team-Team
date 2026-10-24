"""Derived Working Context compaction preserves factual personal history."""

from test.test_att.test_agent_activity._support import ActivityTestCase, idle


class TestWorkingContextCompaction(ActivityTestCase):
    async def test_compaction_uses_references_without_an_extra_summary_model_call(self):
        self.manager.config.working_context_message_limit = 4
        original = [
            {"role": "system", "content": "Initial personal instructions"},
            {"role": "user", "content": "Earlier request one"},
            {"role": "assistant", "content": "Earlier answer one"},
            {"role": "user", "content": "Earlier request two"},
            {"role": "assistant", "content": "Earlier answer two"},
            {"role": "user", "content": "Current request"},
            {"role": "assistant", "content": "Current context"},
        ]
        for message in original:
            self.root.append_message(message)
        self.steps(idle())
        admission = await self.manager.activate_agent(self.root.agent_id)
        await self.wait(admission)
        self.assertEqual(len(self.client.requests), 1)
        self.assertTrue(any("Working Context was compacted" in message.get("content", "")
            for message in self.root.messages))
        self.assertTrue(all(message in self.root.message_history for message in original))
        self.assertEqual(self.root.messages[0]["content"], "Initial personal instructions")

    async def test_compaction_does_not_split_a_native_tool_exchange(self):
        self.manager.config.working_context_message_limit = 4
        for message in [
            {"role": "system", "content": "Personal instructions"},
            {"role": "user", "content": "Earlier question"},
            {"role": "assistant", "content": "Earlier answer"},
            {"role": "user", "content": "Read a source"},
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "earlier-call", "type": "function",
                 "function": {"name": "read_file", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "earlier-call", "content": "Earlier result"},
            {"role": "assistant", "content": "After reading"},
            {"role": "user", "content": "Continue"},
        ]:
            self.root.append_message(message)
        self.steps(idle())
        admission = await self.manager.activate_agent(self.root.agent_id)
        await self.wait(admission)
        pending = set()
        for message in self.client.requests[0].prompt:
            if message.get("tool_calls"):
                self.assertFalse(pending)
                pending = {call["id"] for call in message["tool_calls"]}
            elif message["role"] == "tool":
                self.assertIn(message["tool_call_id"], pending)
                pending.remove(message["tool_call_id"])
            else:
                self.assertFalse(pending)
        self.assertFalse(pending)
        self.assertTrue(any(message.get("tool_call_id") == "earlier-call"
            for message in self.root.message_history))

