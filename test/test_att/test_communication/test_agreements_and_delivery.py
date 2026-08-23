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

    async def test_one_way_delivery_idempotency_and_endpoint_revocation(self):
        manager = self.manager(
            ParentApprovalCommunicationConfig(direction="one_way")
        )
        sender = manager.create_agent_team(self.root, member_count=3)
        recipient = manager.create_agent_team(self.root, member_count=3)
        outsider = manager.create_agent_team(self.root, member_count=3)
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
        self.assertFalse(agreement.active)
        await manager.close()
    async def test_relevant_topology_change_creates_stale_successor(self):
        manager = self.manager(ParentApprovalCommunicationConfig())
        parent_a = manager.create_agent_team(self.root, member_count=3)
        parent_b = manager.create_agent_team(self.root, member_count=3)
        parent_c = manager.create_agent_team(self.root, member_count=3)
        sender = manager.create_agent_team(parent_a, member_count=3)
        recipient = manager.create_agent_team(parent_b, member_count=3)

        result = await manager.broker.request_peer_communication(
            sender, recipient, sender.members[0].agent_id, "route changes"
        )
        request = manager.broker.communication_requests[result.request_id]
        await manager.execute_team_discussion(parent_a, "first approval", rounds=1)

        with manager._topology_lock:
            parent_b.child_teams.remove(recipient)
            parent_c.child_teams.append(recipient)
            recipient._parent_team = parent_c
            manager._team_parent_map[recipient.team_id] = parent_c.team_id
            recipient.invalidate_depth_cache()

        await manager.execute_team_discussion(parent_b, "old route", rounds=1)

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
        manager = self.manager(ParentApprovalCommunicationConfig())
        parent_a = manager.create_agent_team(self.root, member_count=3)
        parent_b = manager.create_agent_team(self.root, member_count=3)
        sender = manager.create_agent_team(parent_a, member_count=3)
        recipient = manager.create_agent_team(parent_b, member_count=3)
        result = await manager.broker.request_peer_communication(
            sender, recipient, sender.members[0].agent_id, "concurrent"
        )
        request = manager.broker.communication_requests[result.request_id]
        first, second = manager.broker.approvals_for_request(request.request_id)
        await manager.broker._claim_approval(request.request_id, first.principal)
        await manager.broker._claim_approval(request.request_id, second.principal)

        await manager.broker._complete_approval(
            request.request_id,
            first.principal,
            DecisionOutcome("denied", "first denied"),
        )
        await manager.broker._complete_approval(
            request.request_id,
            second.principal,
            DecisionOutcome("approved", "late approval"),
        )

        self.assertEqual(request.status.value, "DENIED")
        self.assertEqual(second.status.value, "CANCELLED")
        self.assertEqual(len(manager.broker.agreements), 0)
        await manager.close()
    async def test_bidirectional_request_supersedes_one_way_channel(self):
        manager = self.manager(
            ParentApprovalCommunicationConfig(direction="one_way")
        )
        sender = manager.create_agent_team(self.root, member_count=3)
        recipient = manager.create_agent_team(self.root, member_count=3)
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
        self.assertFalse(old_agreement.active)
        self.assertEqual(
            old_agreement.superseded_by_agreement_id,
            active[0].agreement_id,
        )
        await manager.close()
