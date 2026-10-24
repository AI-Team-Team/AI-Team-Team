"""Explicit mail cases and receipt-published channels replace team discussions."""

import asyncio
from pathlib import Path
from unittest.mock import patch

from ai_team_team import ATTConfig, Agent, ParentApprovalCommunicationConfig, StatePersistenceError
from test.governance_client import PersonalGovernanceClient, settle_governance_activity
from test.test_att.test_agent_activity._support import ActivityTestCase


class InstitutionalCommunicationTests(ActivityTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.root = Agent("Governor", "Architect", PersonalGovernanceClient(native=True))
        self.manager = self.make_manager(self.root, config=ATTConfig(
            workspace_root=self.workspace.name, tool_calling_mode="native",
            communication=ParentApprovalCommunicationConfig(),
        ))

    async def test_queue_delivers_personal_ballots_without_a_discussion(self):
        parent = self.manager.create_agent_team(self.root)
        sender = self.manager.create_agent_team(self.root, parent=parent)
        recipient = self.manager.create_agent_team(self.root, parent=self.root)
        result = await self.manager.broker.request_peer_communication(
            sender, recipient, sender.members[0].agent_id, "Choose a voluntary channel."
        )
        self.assertEqual(result.status, "PENDING_APPROVAL")
        await settle_governance_activity(self.manager)
        request = self.manager.broker.communication_requests[result.request_id]
        self.assertEqual(request.status.value, "APPROVED")
        self.assertEqual(len(self.manager.broker.agreements), 1)
        cases = [case for case in self.manager._governance.cases.values() if case.business_id == result.request_id]
        self.assertEqual(sorted(len(case.ballots) for case in cases), [1, 3])
        self.assertTrue(all(approval.case_id for approval in self.manager.broker.approvals_for_request(result.request_id)))
        self.assertFalse(any(item.get("type") == "communication_approval_request" for item in parent.message_inbox))
        self.assertFalse(hasattr(self.manager, "execute_team_discussion"))
        self.assertFalse(hasattr(parent, "discussion_lock"))

    async def test_independent_pair_needs_neither_request_nor_channel(self):
        sender = self.manager.create_agent_team(self.root)
        recipient = self.manager.create_agent_team(self.root)
        result = await self.manager.broker.request_peer_communication(
            sender, recipient, sender.members[0].agent_id, "Independent peers."
        )
        self.assertEqual(result.status, "APPROVED")
        self.assertIsNone(result.request_id)
        self.assertFalse(self.manager.broker.communication_requests)
        self.assertFalse(self.manager.broker.agreements)
        with patch.object(self.manager._activity, "schedule_notice"):
            result = await self.manager.broker.send_peer_message(
                sender, recipient, sender.members[0].agent_id, "A deliberately addressed peer body.", invocation_id="peer-once"
            )
            repeated = await self.manager.broker.send_peer_message(
                sender, recipient, sender.members[0].agent_id, "A deliberately addressed peer body.", invocation_id="peer-once"
            )
        self.assertEqual(result.message_id, repeated.message_id)
        self.assertEqual(len(recipient.message_inbox), 1)
        self.assertEqual(len(self.records("agent_notifications")), 3)
        for member in recipient.members:
            self.assertNotIn("A deliberately addressed peer body.", str(member.messages))
            self.assertNotIn("A deliberately addressed peer body.", str(member.agent_inbox))

    async def test_failed_request_or_delivery_never_publishes_candidates(self):
        sender = self.manager.create_agent_team(self.root, parent=self.root)
        recipient = self.manager.create_agent_team(self.root, parent=self.root)
        with patch.object(self.manager._records, "commit", side_effect=StatePersistenceError("Synthetic failed receipt")):
            with self.assertRaises(StatePersistenceError):
                await self.manager.broker.request_peer_communication(
                    sender, recipient, sender.members[0].agent_id, "Must not appear."
                )
        self.assertFalse(self.manager.broker.communication_requests)
        self.manager.config.communication = {"policy": "permissive"}
        with patch.object(self.manager._records, "commit", side_effect=StatePersistenceError("Synthetic failed receipt")):
            with self.assertRaises(StatePersistenceError):
                await self.manager.broker.send_peer_message(
                    sender, recipient, sender.members[0].agent_id, "Must not appear."
                )
        self.assertFalse(self.manager.broker.peer_messages)
        self.assertFalse(recipient.message_inbox)
        self.assertTrue(all(not member.agent_inbox for member in recipient.members))

    async def test_relevant_detachment_stales_even_before_any_ballot(self):
        self.root.llm_client.respond = False
        sender = self.manager.create_agent_team(self.root, parent=self.root)
        recipient = self.manager.create_agent_team(self.root)
        result = await self.manager.broker.request_peer_communication(
            sender, recipient, sender.members[0].agent_id, "Pending before departure."
        )
        await settle_governance_activity(self.manager)
        migration = await self.manager.negotiate_and_execute_migration(sender, None, "Choose independence.")
        self.assertEqual(migration.status, "EXECUTED")
        await settle_governance_activity(self.manager)
        prior = self.manager.broker.communication_requests[result.request_id]
        self.assertEqual(prior.status.value, "STALE")
        successor = self.manager.broker.communication_requests[prior.superseded_by_request_id]
        self.assertEqual(successor.status.value, "APPROVED")
        self.assertFalse(successor.approval_principals)
        self.assertFalse(self.manager.broker.agreements)

    async def test_case_and_channel_restore_keep_exact_ballot_provenance(self):
        sender = self.manager.create_agent_team(self.root, parent=self.root)
        recipient = self.manager.create_agent_team(self.root, parent=self.root)
        result = await self.manager.broker.request_peer_communication(
            sender, recipient, sender.members[0].agent_id, "Retained exact authority."
        )
        await settle_governance_activity(self.manager)
        path = str(Path(self.workspace.name) / "communication.sqlite")
        await self.manager.save_state(path)
        await self.manager.load_state(path)
        self.assertEqual(self.manager.broker.communication_requests[result.request_id].status.value, "APPROVED")
        self.assertEqual(len(self.manager.broker.agreements), 1)
        approval = self.manager.broker.approvals_for_request(result.request_id)[0]
        self.assertEqual(self.manager._governance.cases[approval.case_id].principal.principal_id, self.root.agent_id)
