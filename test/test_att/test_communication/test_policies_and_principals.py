from ai_team_team import (
    LineageApprovalCommunicationConfig,
    ParentApprovalCommunicationConfig,
)

from test.test_att.test_communication._support import CommunicationTestCase


class TestAutonomousCommunication(CommunicationTestCase):

    async def test_permissive_delivery_needs_no_agreement(self):
        manager = self.manager()
        first = manager.create_agent_team(self.root, parent=self.root, member_count=3)
        second = manager.create_agent_team(self.root, parent=self.root, member_count=3)

        result = await manager.broker.send_peer_message(
            first,
            second,
            first.members[0].agent_id,
            "hello",
            invocation_id="permissive-call",
        )

        self.assertEqual(result.status, "DELIVERED")
        self.assertEqual(len(manager.broker.agreements), 0)
        self.assertEqual(second.message_inbox[0]["objective"], "hello")
        await manager.close()
    async def test_broker_rejects_forged_initiating_agent(self):
        manager = self.manager()
        first = manager.create_agent_team(self.root, parent=self.root, member_count=3)
        second = manager.create_agent_team(self.root, parent=self.root, member_count=3)

        with self.assertRaisesRegex(PermissionError, "not an active sender"):
            await manager.broker.send_peer_message(
                first,
                second,
                second.members[0].agent_id,
                "forged actor",
            )
        with self.assertRaisesRegex(PermissionError, "not an active sender"):
            await manager.broker.request_peer_communication(
                first,
                second,
                second.members[0].agent_id,
                "forged actor",
            )
        self.assertEqual(manager.broker.peer_messages, {})
        self.assertEqual(manager.broker.communication_requests, {})
        await manager.close()
    async def test_governance_rejection_cancels_remaining_approvals(self):
        self.client.approved = False
        manager = self.manager(ParentApprovalCommunicationConfig())
        parent_a = manager.create_agent_team(self.root, parent=self.root, member_count=3)
        parent_b = manager.create_agent_team(self.root, parent=self.root, member_count=3)
        sender = manager.create_agent_team(parent_a, parent=parent_a, member_count=3)
        recipient = manager.create_agent_team(parent_b, parent=parent_b, member_count=3)

        result = await manager.broker.request_peer_communication(
            sender, recipient, sender.members[0].agent_id, "reject this"
        )
        request = manager.broker.communication_requests[result.request_id]
        request = await self.wait_for_status(request, "DENIED")
        self.assertEqual(request.status.value, "DENIED")
        self.assertEqual(len(manager.broker.agreements), 0)
        statuses = {
            approval.status.value
            for approval in manager.broker.approvals_for_request(
                request.request_id
            )
        }
        self.assertEqual(statuses, {"DENIED", "CANCELLED"})
        await manager.close()
    async def test_non_literal_boolean_keeps_agent_approval_pending(self):
        self.client.approved = "true"
        manager = self.manager(ParentApprovalCommunicationConfig())
        events = []
        manager.on_system_event = lambda name, payload: events.append((name, payload))
        first = manager.create_agent_team(self.root, parent=self.root, member_count=3)
        second = manager.create_agent_team(self.root, parent=self.root, member_count=3)

        result = await manager.broker.request_peer_communication(
            first, second, first.members[0].agent_id, "strict decision"
        )
        request = manager.broker.communication_requests[result.request_id]
        await self.wait_for_governance_idle(request)
        await manager.flush_callbacks()

        self.assertTrue(
            any(
                name == "tool_execution_failed"
                and payload.get("tool_name") == "submit_governance_choice"
                and payload.get("agent_id") == self.root.agent_id
                and payload.get("status") == "invalid_arguments"
                for name, payload in events
            ),
            "The Agent must attempt a choice and receive strict argument validation.",
        )

        self.assertEqual(request.status.value, "PENDING")
        self.assertEqual(
            manager.broker.approvals_for_request(request.request_id)[0].status.value,
            "PENDING",
        )
        self.assertEqual(len(manager.broker.agreements), 0)
        voting_round = manager._governance.latest(
            "communication", request.request_id, request.approval_principals[0]
        )
        self.assertIsNotNone(voting_round)
        self.assertEqual(voting_round.ballots, [])
        await manager.close()
    async def test_top_level_parent_approval_is_root_agent(self):
        manager = self.manager(ParentApprovalCommunicationConfig())
        first = manager.create_agent_team(self.root, parent=self.root, member_count=3)
        second = manager.create_agent_team(self.root, parent=self.root, member_count=3)

        result = await manager.broker.request_peer_communication(
            first, second, first.members[0].agent_id, "coordinate"
        )
        request = manager.broker.communication_requests[result.request_id]
        self.assertEqual(
            [principal.kind for principal in request.approval_principals],
            ["agent"],
        )
        self.assertEqual(
            request.approval_principals[0].principal_id,
            self.root.agent_id,
        )

        request = await self.wait_for_status(request, "APPROVED")
        self.assertEqual(request.status.value, "APPROVED")
        agreement = next(iter(manager.broker.agreements.values()))
        self.assertEqual(agreement.direction.value, "bidirectional")
        await manager.close()
    async def test_parent_approval_queue_uses_both_agent_teams(self):
        manager = self.manager(ParentApprovalCommunicationConfig())
        parent_a = manager.create_agent_team(self.root, parent=self.root, member_count=3)
        parent_b = manager.create_agent_team(self.root, parent=self.root, member_count=3)
        sender = manager.create_agent_team(parent_a, parent=parent_a, member_count=3)
        recipient = manager.create_agent_team(parent_b, parent=parent_b, member_count=3)

        result = await manager.broker.request_peer_communication(
            sender, recipient, sender.members[0].agent_id, "coordinate"
        )
        request = manager.broker.communication_requests[result.request_id]
        self.assertEqual(
            [principal.principal_id for principal in request.approval_principals],
            [parent_a.team_id, parent_b.team_id],
        )
        self.assertEqual(request.status.value, "PENDING")

        self.assertEqual(request.status.value, "PENDING")
        request = await self.wait_for_status(request, "APPROVED")
        self.assertEqual(request.status.value, "APPROVED")
        self.assertEqual(len(manager.broker.agreements), 1)
        await manager.close()
    async def test_lineage_path_excludes_sender_and_includes_root(self):
        manager = self.manager(LineageApprovalCommunicationConfig())
        branch_a = manager.create_agent_team(self.root, parent=self.root, member_count=3)
        branch_b = manager.create_agent_team(self.root, parent=self.root, member_count=3)
        sender = manager.create_agent_team(branch_a, parent=branch_a, member_count=3)
        recipient = manager.create_agent_team(branch_b, parent=branch_b, member_count=3)

        path = manager.broker.approval_path(
            sender, recipient, manager.config.communication
        )
        self.assertEqual(
            [principal.key for principal in path],
            [
                f"agent_team:{branch_a.team_id}",
                f"agent:{self.root.agent_id}",
                f"agent_team:{branch_b.team_id}",
                f"agent_team:{recipient.team_id}",
            ],
        )
        self.assertNotIn(
            f"agent_team:{sender.team_id}",
            [principal.key for principal in path],
        )
        await manager.close()
