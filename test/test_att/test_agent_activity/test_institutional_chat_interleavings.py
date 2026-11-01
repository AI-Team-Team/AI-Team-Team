"""Shared people receive chat and institutional mail without implicit consent."""

import asyncio
import json
import random
import sqlite3
from contextlib import closing
from unittest.mock import patch

from ai_team_team import ATTConfig, Agent, LLMResponse, ParentApprovalCommunicationConfig
from ai_team_team.core.activity.contracts import AgentTeamScope, SuppressionPreference
from test.async_waits import wait_for_runtime
from test.test_att.test_autonomous_activity_phase0._fixtures import AsyncBarrier, ModelStep

from ._support import ActivityTestCase, call, idle


class InstitutionalChatInterleavingTests(ActivityTestCase):
    async def exercise(self, *, native, durable):
        await self.manager.close()
        self.client.native = native
        self.manager = self.make_manager(self.root, durable=durable, config=ATTConfig(
            workspace_root=self.workspace.name,
            tool_calling_mode="native" if native else "text_react",
            enable_memory_compression=False,
            communication=ParentApprovalCommunicationConfig(),
        ))
        # Bootstrap is setup, not the notification boundary under test.
        with patch.object(self.manager._activity, "schedule_notice"):
            first = self.manager.bootstrap_agent_team(self.root, existing_members=[self.root],
                member_configs={"PeerA": {"model": "fixture"}, "PeerB": {"model": "fixture"}})
            second = self.manager.bootstrap_agent_team(self.root, existing_members=[self.root],
                member_configs={"PeerC": {"model": "fixture"}, "PeerD": {"model": "fixture"}})
            sender = self.manager.create_agent_team(self.root, parent=self.root)
            recipient = self.manager.create_agent_team(self.root, parent=self.root)
            messenger = self.manager.register_agent(Agent("Messenger", "Researcher", self.client))
            for person in tuple(self.manager.agents.values()):
                if person is not self.root:
                    await self.manager.set_notification_suppression(SuppressionPreference(scope="all"), actor=person)
            await self.manager.flush_state()
            await self.manager.flush_callbacks()
        self.root.append_message({"role": "assistant", "content": "A prior personal experience."})
        private_id = self.root.private_doc_library_id
        barrier = AsyncBarrier()
        self.client.steps.extend((ModelStep(LLMResponse(text='{"approved": true}'), barrier),
                                  ModelStep(idle(native=native))))
        admission = await self.manager.activate_agent(self.root.agent_id, scope=AgentTeamScope(team_id=first.team_id))
        await barrier.wait_entered()
        operations = [
            ("team", lambda: self.manager.send_team_message(first.team_id, "# Team evidence", actor=first.members[1])),
            ("direct", lambda: self.manager.send_direct_message(self.root.agent_id, "# Direct evidence", actor=messenger)),
            ("governance", lambda: self.manager.broker.request_peer_communication(
                sender, recipient, sender.members[0].agent_id, "An explicit channel decision.")),
        ]
        random.Random(1709).shuffle(operations)
        try:
            outcomes = await asyncio.gather(*(operation() for _, operation in operations))
            delivered = dict(zip((name for name, _ in operations), outcomes))
            self.assertEqual(self.client.maximum_in_flight, 1)
            self.assertEqual(len(self.client.requests), 1)
        finally:
            barrier.release()
        await self.wait(admission)
        await self.settle()
        request = self.manager.broker.communication_requests[delivered["governance"].request_id]
        case = next(case for case in self.manager._governance.cases.values() if case.business_id == request.request_id)
        self.assertEqual(request.status.value, "PENDING")
        self.assertFalse(case.ballots)
        self.assertFalse(self.manager.broker.agreements)
        frame = json.dumps(self.client.requests[1].prompt)
        email = next(message for message in self.root.agent_inbox if message["payload"].get("case_id") == case.case_id)
        for reference in (delivered["team"].message_id, delivered["direct"].message_id, email["message_id"]):
            self.assertIn(reference, frame)
        self.assertTrue(all(message["read_at"] is None for message in self.root.agent_inbox))
        self.assertTrue(self.manager.list_team_messages(first.team_id, actor=self.root).items[0].unread)
        self.assertTrue(self.manager.list_direct_messages(messenger.agent_id, actor=self.root).items[0].unread)
        self.assertEqual(len(self.records("chat_messages")), 2)
        self.assertIn("A prior personal experience.", str(self.root.message_history))
        self.assertIs(self.manager.agents[self.root.name], self.root)
        self.assertIn(self.root, first.members)
        self.assertIn(self.root, second.members)
        self.assertEqual(self.root.private_doc_library_id, private_id)
        if native:
            choice = call("submit_governance_choice", {"case_id": case.case_id, "choice": {"approved": True}})
        else:
            choice = LLMResponse(text=f"Action: submit_governance_choice(case_id={case.case_id!r}, choice={{'approved': True}})")
        self.steps(choice, idle(native=native))
        explicit = await self.manager.activate_agent(self.root.agent_id)
        await self.wait(explicit)

        async def resolved():
            while self.manager.broker.communication_requests[request.request_id].status.value == "PENDING":
                await asyncio.sleep(0)
        await wait_for_runtime(self.manager, resolved(), label="Explicit personal ballot resolves the channel")
        self.assertEqual(self.manager.broker.communication_requests[request.request_id].status.value, "APPROVED")
        self.assertEqual(len(self.manager._governance.cases[case.case_id].ballots), 1)
        self.assertEqual(self.client.maximum_in_flight, 1)
        self.assertEqual(self.client.unexpected_requests, 0)
        self.assertEqual(len(self.records("chat_messages")), 2)
        if durable:
            await self.manager.save_state()
            with closing(sqlite3.connect(self.manager.db_path)) as database:
                votes = database.execute("SELECT voter_agent_id, choice FROM governance_ballots WHERE case_id=?", (case.case_id,)).fetchall()
                principal = database.execute("SELECT principal_agent_id, principal_team_id FROM governance_cases WHERE case_id=?", (case.case_id,)).fetchone()
            self.assertEqual([(voter, json.loads(choice)) for voter, choice in votes],
                             [(self.root.agent_id, {"approved": True, "reason": ""})])
            self.assertEqual(principal, (self.root.agent_id, None))

    async def test_native_volatile_mail_and_chat_preserve_explicit_authority(self):
        await self.exercise(native=True, durable=False)

    async def test_text_volatile_mail_and_chat_preserve_explicit_authority(self):
        await self.exercise(native=False, durable=False)

    async def test_native_durable_mail_and_chat_preserve_explicit_authority(self):
        await self.exercise(native=True, durable=True)

    async def test_text_durable_mail_and_chat_preserve_explicit_authority(self):
        await self.exercise(native=False, durable=True)
