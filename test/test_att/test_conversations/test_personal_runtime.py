"""Real Text and Native personal activity, without an implicit team publisher."""

import json

from ai_team_team import Agent, LLMResponse
from test.test_att.test_agent_activity._support import ActivityTestCase, call, idle
from test.test_att.test_autonomous_activity_phase0._fixtures import ScriptedModelClient, ModelStep


class ChatRuntimeTests(ActivityTestCase):
    async def test_repeated_native_call_id_in_distinct_requests_is_not_a_replayed_message(self):
        peer_client = ScriptedModelClient(ModelStep(idle()), ModelStep(idle()))
        peer = self.manager.register_agent(Agent("Peer", "Researcher", peer_client))
        self.manager.register_llm_client("peer", peer_client)
        self.steps(call("send_direct_message", {"agent_id": peer.agent_id, "markdown": "First"}, call_id="same"),
                   call("send_direct_message", {"agent_id": peer.agent_id, "markdown": "Second"}, call_id="same"), idle())
        admission = await self.manager.activate_agent(self.root.agent_id)
        await self.wait(admission)
        await self.settle()
        self.assertEqual(len(self.records("chat_messages")), 2)
        self.assertEqual(len({row.values["operation_key"] for row in self.records("chat_messages")}), 2)
        self.assertEqual(self.manager.list_direct_messages(self.root.agent_id, actor=peer).unread_count, 2)
        self.assertLessEqual(peer_client.maximum_in_flight, 1)
        self.assertEqual(peer_client.unexpected_requests, 0)

    async def test_text_and_native_publication_and_private_answer_have_the_same_contract(self):
        for native in (False, True):
            self.manager.config.tool_calling_mode = "native" if native else "text_react"
            peer_client = ScriptedModelClient(ModelStep(idle(native=native)))
            peer = self.manager.register_agent(Agent(f"Peer-{native}", "Researcher", peer_client))
            self.manager.register_llm_client(f"peer-{native}", peer_client)
            publish = call("send_direct_message", {"agent_id": peer.agent_id, "markdown": "Explicitly public"}) if native else LLMResponse(
                text=f"Action: send_direct_message(agent_id={peer.agent_id!r}, markdown='Explicitly public')")
            self.steps(LLMResponse(text="A personal answer, not a chat publication"), publish, idle(native=native))
            admission = await self.manager.activate_agent(self.root.agent_id)
            await self.wait(admission)
            await self.settle()
            sources = self.manager.list_direct_messages(self.root.agent_id, actor=peer)
            self.assertEqual(sources.total_count, 1)
            self.assertEqual(sources.items[0].preview, "Explicitly public")
            self.assertEqual(sources.unread_count, 1)
            self.assertEqual(peer_client.unexpected_requests, 0)
            self.assertIn("1 unread", json.dumps(peer_client.requests[0].prompt))

    async def test_tool_schema_does_not_allow_actor_or_operation_key_overrides(self):
        self.steps(idle())
        admission = await self.manager.activate_agent(self.root.agent_id)
        await self.wait(admission)
        tools = {tool.name: tool for tool in self.client.requests[0].tools}
        self.assertNotIn("send_team_message", tools)
        for name in ("send_direct_message", "read_chat_message", "respond_friendship"):
            self.assertNotIn("actor", tools[name].json_schema["properties"])
            self.assertNotIn("operation_key", tools[name].json_schema["properties"])
