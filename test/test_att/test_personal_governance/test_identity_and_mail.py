import asyncio
import tempfile
import unittest

from ai_team_team import (
    ATTConfig,
    ATTManager,
    Agent,
    ParentApprovalCommunicationConfig,
    ToolArgumentError,
    ToolBusinessError,
)
from test.governance_client import PersonalGovernanceClient


class PersonalGovernanceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.workspace = tempfile.TemporaryDirectory(prefix="att-personal-governance-")
        self.addCleanup(self.workspace.cleanup)
        self.client = PersonalGovernanceClient()
        self.root = Agent("Root", "Root", self.client, system_instructions="My enduring mission.")
        self.manager = ATTManager(
            self.root,
            ATTConfig(
                workspace_root=self.workspace.name,
                enable_memory_compression=False,
                communication=ParentApprovalCommunicationConfig(),
            ),
        )
        self.manager.register_llm_client("default", self.client)
        self.addAsyncCleanup(self.manager.close)

    async def settle(self):
        async with asyncio.timeout(5):
            while self.manager._emergency_tasks:
                await asyncio.gather(*tuple(self.manager._emergency_tasks))
                await asyncio.sleep(0)

    async def request(self):
        first = self.manager.create_agent_team(self.root)
        second = self.manager.create_agent_team(self.root)
        result = await self.manager.broker.request_peer_communication(
            first, second, first.members[0].agent_id, "Keep communication autonomous."
        )
        await self.settle()
        return self.manager.broker.communication_requests[result.request_id]

    async def test_root_uses_ordinary_history_and_explicit_tools(self):
        self.root.append_message({"role": "assistant", "content": "My prior public experience."})
        request = await self.request()
        self.assertEqual(request.status.value, "APPROVED")
        ordinary = [call for call in self.client.calls if isinstance(call[0], list)]
        self.assertTrue(ordinary)
        self.assertIn("My enduring mission.", ordinary[0][1])
        self.assertIn("My prior public experience.", str(ordinary[0][0]))
        self.assertIn("Public governance choice", str(self.root.message_history))
        self.assertIn("Keep communication autonomous.", str(self.root.message_history))
        self.assertFalse(
            any(team.team_purpose == "Governance" for team in self.manager.teams.values())
        )
        self.assertIsNone(self.root.agent_inbox[0]["read_at"])

    async def test_unanswered_read_email_never_becomes_a_vote(self):
        self.client.respond = False
        request = await self.request()
        item = next(iter(self.manager._governance.rounds.values()))
        email = self.root.agent_inbox[0]
        opened = self.manager.open_agent_mail(email["message_id"], actor=self.root)
        self.assertEqual(opened["governance"]["round_id"], item.round_id)
        self.assertIsNone(email["read_at"])
        await self.manager.mark_agent_inbox_read(self.root.agent_id)
        self.assertEqual(request.status.value, "PENDING")
        self.assertFalse(item.ballots)
        self.assertEqual(len(self.manager.list_governance_requests(actor=self.root)), 1)
        self.assertIn(email["message_id"], self.manager._inbox.render(self.root.agent_id))

    async def test_native_notifications_use_the_same_tool_contract(self):
        self.client.native = True
        self.manager.config.tool_calling_mode = "native"
        request = await self.request()
        self.assertEqual(request.status.value, "APPROVED")
        self.assertTrue(
            all(
                call[2].get("tools")
                for call in self.client.calls
                if not call[2].get("require_json") and isinstance(call[0], list)
            )
        )
        pending = set()
        for message in self.root.messages:
            if message.get("tool_calls"):
                self.assertFalse(pending)
                pending = {call["id"] for call in message["tool_calls"]}
            elif message["role"] == "tool":
                self.assertIn(message["tool_call_id"], pending)
                pending.remove(message["tool_call_id"])
            else:
                self.assertFalse(
                    pending, "Ordinary messages must not interrupt a native tool batch."
                )
        self.assertFalse(pending)

    async def test_private_files_are_not_injected_into_voting_context(self):
        secret = "PRIVATE-NOTES-NEVER-AUTOMATICALLY-READ"
        self.manager.libraries[self.root.private_doc_library_id].write_file("private.txt", secret)
        callbacks = []
        self.manager.on_system_event = lambda *args: callbacks.append(args)
        request = await self.request()
        await self.manager.flush_callbacks()
        self.assertEqual(request.status.value, "APPROVED")
        self.assertNotIn(secret, str(self.client.calls))
        self.assertNotIn(secret, str(self.root.message_history))
        self.assertNotIn(secret, str(callbacks))

    async def test_strict_immutable_choice_and_cross_identity_rejection(self):
        self.client.respond = False
        await self.request()
        item = next(iter(self.manager._governance.rounds.values()))
        token = self.manager._active_tool_agent.set(self.root)
        try:
            for invalid in ("true", 1, None):
                with self.assertRaises(ToolArgumentError):
                    await self.manager.submit_governance_choice(
                        item.round_id, {"approved": invalid}, actor=self.root
                    )
            first = await self.manager.submit_governance_choice(
                item.round_id, {"approved": True}, actor=self.root
            )
            same = await self.manager.submit_governance_choice(
                item.round_id, {"approved": True}, actor=self.root
            )
            self.assertEqual(first.status, "SUBMITTED")
            self.assertEqual(same.status, "ALREADY_SUBMITTED")
            with self.assertRaises(ToolBusinessError):
                await self.manager.submit_governance_choice(
                    item.round_id, {"approved": False}, actor=self.root
                )
        finally:
            self.manager._active_tool_agent.reset(token)
        other = self.manager.create_agent_team(self.root).members[0]
        with self.assertRaises(PermissionError):
            self.manager.open_agent_mail(self.root.agent_inbox[0]["message_id"], actor=other)
        await self.settle()
