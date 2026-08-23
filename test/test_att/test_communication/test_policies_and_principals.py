import asyncio
import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from ai_team_team import (
    ATTConfig,
    ATTManager,
    Agent,
    LineageApprovalCommunicationConfig,
    ParentApprovalCommunicationConfig,
    PermissiveCommunicationConfig,
)
from ai_team_team.core.decision import DecisionOutcome


class GovernanceClient:
    def __init__(self, approved=True):
        self.approved = approved

    async def generate(
        self,
        prompt=None,
        system_instruction=None,
        require_json=False,
        **kwargs,
    ):
        prompt_text = str(prompt)
        system_text = str(system_instruction)
        if (
            "final ballot" in prompt_text
            or "governance principal" in system_text
        ):
            return json.dumps(
                {"approved": self.approved, "reason": "governance vote"}
            )
        if require_json:
            return '{"is_healthy": true, "reason": "healthy"}'
        return "Final Answer: discussed"

    def supports_output_token_limit(self):
        return True

    def supports_native_tool_calling(self):
        return False

class TestAutonomousCommunication(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.old_cwd = os.getcwd()
        self.workspace = tempfile.mkdtemp(prefix="att-communication-")
        os.chdir(self.workspace)
        self.client = GovernanceClient()
        self.root = Agent("Root", "Root governor", self.client)

    async def asyncTearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.workspace, ignore_errors=True)

    def manager(self, communication=None, db_path=None):
        manager = ATTManager(
            self.root,
            ATTConfig(
                communication=communication
                or PermissiveCommunicationConfig(),
                workspace_root=self.workspace,
            ),
            db_path,
        )
        manager.register_llm_client("default", self.client)
        return manager

    async def wait_for_status(self, request, expected, timeout=1.0):
        async with asyncio.timeout(timeout):
            while request.status.value != expected:
                await asyncio.sleep(0.01)

    async def test_permissive_delivery_needs_no_agreement(self):
        manager = self.manager()
        first = manager.create_agent_team(self.root, member_count=3)
        second = manager.create_agent_team(self.root, member_count=3)

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
        first = manager.create_agent_team(self.root, member_count=3)
        second = manager.create_agent_team(self.root, member_count=3)

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
        parent_a = manager.create_agent_team(self.root, member_count=3)
        parent_b = manager.create_agent_team(self.root, member_count=3)
        sender = manager.create_agent_team(parent_a, member_count=3)
        recipient = manager.create_agent_team(parent_b, member_count=3)

        result = await manager.broker.request_peer_communication(
            sender, recipient, sender.members[0].agent_id, "reject this"
        )
        request = manager.broker.communication_requests[result.request_id]
        await manager.execute_team_discussion(parent_a, "normal work", rounds=1)

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
        first = manager.create_agent_team(self.root, member_count=3)
        second = manager.create_agent_team(self.root, member_count=3)

        result = await manager.broker.request_peer_communication(
            first, second, first.members[0].agent_id, "strict decision"
        )
        request = manager.broker.communication_requests[result.request_id]
        await asyncio.sleep(0.05)

        self.assertEqual(request.status.value, "PENDING")
        self.assertEqual(
            manager.broker.approvals_for_request(request.request_id)[0].status.value,
            "PENDING",
        )
        self.assertEqual(len(manager.broker.agreements), 0)
        await manager.close()
    async def test_top_level_parent_approval_is_root_agent(self):
        manager = self.manager(ParentApprovalCommunicationConfig())
        first = manager.create_agent_team(self.root, member_count=3)
        second = manager.create_agent_team(self.root, member_count=3)

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

        await asyncio.sleep(0.05)
        self.assertEqual(request.status.value, "APPROVED")
        agreement = next(iter(manager.broker.agreements.values()))
        self.assertEqual(agreement.direction.value, "bidirectional")
        await manager.close()
    async def test_parent_approval_queue_uses_both_agent_teams(self):
        manager = self.manager(ParentApprovalCommunicationConfig())
        parent_a = manager.create_agent_team(self.root, member_count=3)
        parent_b = manager.create_agent_team(self.root, member_count=3)
        sender = manager.create_agent_team(parent_a, member_count=3)
        recipient = manager.create_agent_team(parent_b, member_count=3)

        result = await manager.broker.request_peer_communication(
            sender, recipient, sender.members[0].agent_id, "coordinate"
        )
        request = manager.broker.communication_requests[result.request_id]
        self.assertEqual(
            [principal.principal_id for principal in request.approval_principals],
            [parent_a.team_id, parent_b.team_id],
        )
        self.assertEqual(request.status.value, "PENDING")

        await manager.execute_team_discussion(parent_a, "normal work", rounds=1)
        self.assertEqual(request.status.value, "PENDING")
        await manager.execute_team_discussion(parent_b, "normal work", rounds=1)
        self.assertEqual(request.status.value, "APPROVED")
        self.assertEqual(len(manager.broker.agreements), 1)
        await manager.close()
    async def test_lineage_path_excludes_sender_and_includes_root(self):
        manager = self.manager(LineageApprovalCommunicationConfig())
        branch_a = manager.create_agent_team(self.root, member_count=3)
        branch_b = manager.create_agent_team(self.root, member_count=3)
        sender = manager.create_agent_team(branch_a, member_count=3)
        recipient = manager.create_agent_team(branch_b, member_count=3)

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
