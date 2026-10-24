from test.governance_client import settle_governance_activity, submit_case_ballots, approve_pending_business
from ai_team_team import ParentApprovalCommunicationConfig
from ai_team_team.core.decision import DecisionOutcome

from test.test_att.test_communication._support import CommunicationTestCase


class TestAutonomousCommunication(CommunicationTestCase):

    async def test_one_way_delivery_idempotency_and_endpoint_revocation(self):
        manager = self.manager(
            ParentApprovalCommunicationConfig(direction="one_way")
        )
        sender = manager.create_agent_team(self.root, parent=self.root, member_count=3)
        recipient = manager.create_agent_team(self.root, parent=self.root, member_count=3)
        outsider = manager.create_agent_team(self.root, parent=self.root, member_count=3)
        request_result = await manager.broker.request_peer_communication(
            sender, recipient, sender.members[0].agent_id, "one way"
        )
        request = manager.broker.communication_requests[
            request_result.request_id
        ]
        await self.wait_for_status(request, "APPROVED")
        agreement = next(iter(manager.broker.agreements.values()))

        first = await manager.broker.send_peer_message(
            sender,
            recipient,
            sender.members[0].agent_id,
            "once",
            invocation_id="one-way-call",
        )
        duplicate = await manager.broker.send_peer_message(
            sender,
            recipient,
            sender.members[0].agent_id,
            "once",
            invocation_id="one-way-call",
        )
        with self.assertRaisesRegex(ValueError, "already bound"):
            await manager.broker.send_peer_message(
                sender,
                recipient,
                sender.members[0].agent_id,
                "different payload",
                invocation_id="one-way-call",
            )
        reverse = await manager.broker.send_peer_message(
            recipient,
            sender,
            recipient.members[0].agent_id,
            "reverse",
        )
        forbidden = await manager.broker.revoke_agreement(
            agreement.agreement_id, outsider.team_id, "not my channel"
        )
        revoked = await manager.broker.revoke_agreement(
            agreement.agreement_id, recipient.team_id, "finished"
        )

        self.assertEqual(first.message_id, duplicate.message_id)
        self.assertEqual(
            sum(
                message.get("message_id") == first.message_id
                for message in recipient.message_inbox
            ),
            1,
        )
        self.assertEqual(reverse.status, "NO_AGREEMENT")
        self.assertEqual(forbidden.status, "FORBIDDEN")
        self.assertEqual(revoked.status, "REVOKED")
        self.assertFalse(manager.broker.agreements[agreement.agreement_id].active)
        await manager.close()
    async def test_relevant_topology_change_creates_stale_successor(self):
        self.client.respond = False
        manager = self.manager(ParentApprovalCommunicationConfig())
        parent_a = manager.create_agent_team(self.root, parent=self.root, member_count=3)
        parent_b = manager.create_agent_team(self.root, parent=self.root, member_count=3)
        parent_c = manager.create_agent_team(self.root, parent=self.root, member_count=3)
        sender = manager.create_agent_team(parent_a, parent=parent_a, member_count=3)
        recipient = manager.create_agent_team(parent_b, parent=parent_b, member_count=3)

        result = await manager.broker.request_peer_communication(
            sender, recipient, sender.members[0].agent_id, "route changes"
        )
        request = manager.broker.communication_requests[result.request_id]
        await settle_governance_activity(manager)
        case = manager._governance.latest("communication", request.request_id, request.approval_principals[0])
        await submit_case_ballots(manager, case)
        await settle_governance_activity(manager)
        manager.config.migration_policy = "permissive"
        migration = await manager.negotiate_and_execute_migration(recipient, parent_c, "Accepted route change.")
        await approve_pending_business(manager, migration.request_id)
        self.assertEqual(manager.inspect_migration_request(migration.request_id).status, "EXECUTED")
        request = await self.wait_for_status(request, "STALE")

        self.assertEqual(request.status.value, "STALE")
        self.assertIsNotNone(request.superseded_by_request_id)
        successor = manager.broker.communication_requests[
            request.superseded_by_request_id
        ]
        self.assertEqual(successor.supersedes_request_id, request.request_id)
        self.assertEqual(
            [principal.principal_id for principal in successor.approval_principals],
            [parent_a.team_id, parent_c.team_id],
        )
        self.assertEqual(len(manager.broker.agreements), 0)
        await manager.close()
    async def test_denial_cannot_be_overwritten_by_late_approval(self):
        self.client.respond = False
        manager = self.manager(ParentApprovalCommunicationConfig())
        parent_a = manager.create_agent_team(self.root, parent=self.root, member_count=3)
        parent_b = manager.create_agent_team(self.root, parent=self.root, member_count=3)
        sender = manager.create_agent_team(parent_a, parent=parent_a, member_count=3)
        recipient = manager.create_agent_team(parent_b, parent=parent_b, member_count=3)
        result = await manager.broker.request_peer_communication(
            sender, recipient, sender.members[0].agent_id, "concurrent"
        )
        request = manager.broker.communication_requests[result.request_id]
        first, second = manager.broker.approvals_for_request(request.request_id)
        await settle_governance_activity(manager)
        case = manager._governance.latest("communication", request.request_id, first.principal)
        await submit_case_ballots(manager, case, approved=False)
        request = await self.wait_for_status(request, "DENIED")
        await manager.broker._complete_approval(
            request.request_id,
            second.principal,
            DecisionOutcome("approved", "late approval"),
        )

        self.assertEqual(request.status.value, "DENIED")
        self.assertEqual(manager.broker.communication_approvals[second.key].status.value, "CANCELLED")
        self.assertEqual(len(manager.broker.agreements), 0)
        await manager.close()
    async def test_bidirectional_request_supersedes_one_way_channel(self):
        manager = self.manager(
            ParentApprovalCommunicationConfig(direction="one_way")
        )
        sender = manager.create_agent_team(self.root, parent=self.root, member_count=3)
        recipient = manager.create_agent_team(self.root, parent=self.root, member_count=3)
        first_result = await manager.broker.request_peer_communication(
            sender, recipient, sender.members[0].agent_id, "one way first"
        )
        first_request = manager.broker.communication_requests[
            first_result.request_id
        ]
        await self.wait_for_status(first_request, "APPROVED")
        old_agreement = next(iter(manager.broker.agreements.values()))

        manager.config.communication = ParentApprovalCommunicationConfig(
            direction="bidirectional"
        )
        upgrade_result = await manager.broker.request_peer_communication(
            sender, recipient, sender.members[0].agent_id, "upgrade"
        )
        self.assertEqual(upgrade_result.status, "PENDING_APPROVAL")
        upgrade = manager.broker.communication_requests[
            upgrade_result.request_id
        ]
        await self.wait_for_status(upgrade, "APPROVED")

        active = [
            agreement
            for agreement in manager.broker.agreements.values()
            if agreement.active
        ]
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].direction.value, "bidirectional")
        old_agreement = manager.broker.agreements[old_agreement.agreement_id]
        self.assertFalse(old_agreement.active)
        self.assertEqual(
            old_agreement.superseded_by_agreement_id,
            active[0].agreement_id,
        )
        await manager.close()
