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

    async def test_wake_delivery_runs_governance_discussions(self):
        manager = self.manager(
            ParentApprovalCommunicationConfig(request_delivery="wake")
        )
        parent_a = manager.create_agent_team(self.root, member_count=3)
        parent_b = manager.create_agent_team(self.root, member_count=3)
        sender = manager.create_agent_team(parent_a, member_count=3)
        recipient = manager.create_agent_team(parent_b, member_count=3)

        result = await manager.broker.request_peer_communication(
            sender, recipient, sender.members[0].agent_id, "wake both"
        )
        request = manager.broker.communication_requests[result.request_id]
        await self.wait_for_status(request, "APPROVED")

        self.assertEqual(len(manager.broker.agreements), 1)
        self.assertFalse(parent_a.discussion_lock.locked())
        self.assertFalse(parent_b.discussion_lock.locked())
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

    async def test_schema_six_restores_pending_request_and_delivery(self):
        db_path = os.path.join(self.workspace, "communication.db")
        source = self.manager(
            ParentApprovalCommunicationConfig(), db_path=db_path
        )
        parent_a = source.create_agent_team(self.root, member_count=3)
        parent_b = source.create_agent_team(self.root, member_count=3)
        sender = source.create_agent_team(parent_a, member_count=3)
        recipient = source.create_agent_team(parent_b, member_count=3)
        result = await source.broker.request_peer_communication(
            sender, recipient, sender.members[0].agent_id, "persist request"
        )
        await source.save_state()
        await source.close()

        restored = ATTManager(
            Agent("RestoreRoot", "Root governor", self.client),
            ATTConfig(workspace_root=self.workspace),
        )
        restored.register_llm_client("default", self.client)
        await restored.load_state(db_path)
        request = restored.broker.communication_requests[result.request_id]
        self.assertEqual(request.status.value, "PENDING")
        self.assertEqual(
            restored.broker.queued_request_ids_for_team(parent_a.team_id),
            [request.request_id],
        )

        await restored.execute_team_discussion(
            restored.teams[parent_a.team_id], "approve A", rounds=1
        )
        await restored.execute_team_discussion(
            restored.teams[parent_b.team_id], "approve B", rounds=1
        )
        self.assertEqual(request.status.value, "APPROVED")
        delivered = await restored.broker.send_peer_message(
            restored.teams[sender.team_id],
            restored.teams[recipient.team_id],
            restored.teams[sender.team_id].members[0].agent_id,
            "durable",
            invocation_id="restore-delivery",
        )
        await restored.save_state()
        await restored.close()

        final = ATTManager(
            Agent("FinalRoot", "Root governor", self.client),
            ATTConfig(workspace_root=self.workspace),
        )
        final.register_llm_client("default", self.client)
        await final.load_state(db_path)
        self.assertTrue(final.broker.agreements)
        message = final.broker.peer_messages[delivered.message_id]
        self.assertEqual(message.delivery_state, "pending")
        self.assertTrue(
            any(
                item.get("message_id") == message.message_id
                for item in final.teams[recipient.team_id].message_inbox
            )
        )
        await final.close()

    async def test_authoritative_write_failures_roll_back_runtime_state(self):
        governed = self.manager(ParentApprovalCommunicationConfig())
        parent_a = governed.create_agent_team(self.root, member_count=3)
        parent_b = governed.create_agent_team(self.root, member_count=3)
        sender = governed.create_agent_team(parent_a, member_count=3)
        recipient = governed.create_agent_team(parent_b, member_count=3)
        with patch.object(
            governed,
            "_commit_dirty_state",
            AsyncMock(side_effect=OSError("request disk failure")),
        ):
            with self.assertRaisesRegex(OSError, "request disk failure"):
                await governed.broker.request_peer_communication(
                    sender,
                    recipient,
                    sender.members[0].agent_id,
                    "must roll back",
                )
        self.assertEqual(governed.broker.communication_requests, {})
        self.assertFalse(
            any(
                item.get("type") == "communication_approval_request"
                for item in parent_a.message_inbox + parent_b.message_inbox
            )
        )

        valid = await governed.broker.request_peer_communication(
            sender,
            recipient,
            sender.members[0].agent_id,
            "approval rollback",
        )
        request = governed.broker.communication_requests[valid.request_id]
        approval = governed.broker.approvals_for_request(request.request_id)[0]
        await governed.broker._claim_approval(
            request.request_id, approval.principal
        )

        async def fail_after_unrelated_inbox_change(dirty):
            with parent_a.inbox_lock:
                parent_a.message_inbox.append(
                    {"type": "unrelated", "reason": "preserve me"}
                )
            raise OSError("approval disk failure")

        with patch.object(
            governed,
            "_commit_dirty_state",
            side_effect=fail_after_unrelated_inbox_change,
        ):
            with self.assertRaisesRegex(OSError, "approval disk failure"):
                await governed.broker._complete_approval(
                    request.request_id,
                    approval.principal,
                    DecisionOutcome("approved", "approved"),
                )
        restored_request = governed.broker.communication_requests[
            request.request_id
        ]
        restored_approval = governed.broker.communication_approvals[
            approval.key
        ]
        self.assertEqual(restored_request.status.value, "PENDING")
        self.assertEqual(restored_approval.status.value, "PENDING")
        self.assertTrue(
            any(
                item.get("type") == "unrelated"
                for item in parent_a.message_inbox
            )
        )
        self.assertTrue(
            any(
                item.get("request_id") == request.request_id
                for item in parent_a.message_inbox
            )
        )
        await governed.close()

        direct = self.manager(PermissiveCommunicationConfig())
        first = direct.create_agent_team(self.root, member_count=3)
        second = direct.create_agent_team(self.root, member_count=3)
        with patch.object(
            direct,
            "_commit_dirty_state",
            AsyncMock(side_effect=OSError("message disk failure")),
        ):
            with self.assertRaisesRegex(OSError, "message disk failure"):
                await direct.broker.send_peer_message(
                    first,
                    second,
                    first.members[0].agent_id,
                    "must roll back",
                )
        self.assertEqual(direct.broker.peer_messages, {})
        self.assertEqual(second.message_inbox, [])
        await direct.close()

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

    async def test_failed_discussion_does_not_complete_team_approval(self):
        manager = self.manager(ParentApprovalCommunicationConfig())
        parent_a = manager.create_agent_team(self.root, member_count=3)
        parent_b = manager.create_agent_team(self.root, member_count=3)
        sender = manager.create_agent_team(parent_a, member_count=3)
        recipient = manager.create_agent_team(parent_b, member_count=3)
        result = await manager.broker.request_peer_communication(
            sender, recipient, sender.members[0].agent_id, "retry after failure"
        )
        request = manager.broker.communication_requests[result.request_id]
        approval = manager.broker.approvals_for_request(request.request_id)[0]

        with patch.object(
            manager.supervisor,
            "audit_team_dialog",
            AsyncMock(side_effect=RuntimeError("audit failed")),
        ):
            with self.assertRaisesRegex(RuntimeError, "audit failed"):
                await manager.execute_team_discussion(
                    parent_a, "attempt approval", rounds=1
                )

        self.assertEqual(request.status.value, "PENDING")
        self.assertEqual(approval.status.value, "PENDING")
        self.assertTrue(
            any(
                item.get("request_id") == request.request_id
                for item in parent_a.message_inbox
            )
        )
        await manager.close()

    async def test_partial_member_failure_keeps_team_approval_pending(self):
        manager = self.manager(ParentApprovalCommunicationConfig())
        parent_a = manager.create_agent_team(self.root, member_count=3)
        parent_b = manager.create_agent_team(self.root, member_count=3)
        sender = manager.create_agent_team(parent_a, member_count=3)
        recipient = manager.create_agent_team(parent_b, member_count=3)
        result = await manager.broker.request_peer_communication(
            sender,
            recipient,
            sender.members[0].agent_id,
            "complete discussion required",
        )
        request = manager.broker.communication_requests[result.request_id]
        approval = manager.broker.approvals_for_request(request.request_id)[0]

        with patch.object(
            parent_a,
            "execute_reasoning_step",
            AsyncMock(side_effect=RuntimeError("member failed")),
        ):
            await manager.execute_team_discussion(
                parent_a, "attempt approval", rounds=1
            )

        self.assertEqual(request.status.value, "PENDING")
        self.assertEqual(approval.status.value, "PENDING")
        self.assertTrue(
            any(
                item.get("request_id") == request.request_id
                for item in parent_a.message_inbox
            )
        )
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

    async def test_tools_require_invocation_context_and_never_accept_mode(self):
        manager = self.manager(ParentApprovalCommunicationConfig())
        first = manager.create_agent_team(self.root, member_count=3)
        second = manager.create_agent_team(self.root, member_count=3)
        request_tool = first.tools["request_peer_communication"]
        self.assertNotIn("mode", request_tool.json_schema["properties"])
        self.assertNotIn("sender_team_id", request_tool.json_schema["properties"])

        outside = await request_tool(second.team_id, "coordinate")
        self.assertIn("requires an active AgentTeam invocation context", outside)

        team_token = manager._active_team.set(first)
        agent_token = manager._active_tool_agent.set(first.members[0])
        try:
            inside = json.loads(
                await request_tool(team_id=second.team_id, rationale="coordinate")
            )
        finally:
            manager._active_tool_agent.reset(agent_token)
            manager._active_team.reset(team_token)
        self.assertEqual(inside["status"], "PENDING_APPROVAL")
        await manager.close()


if __name__ == "__main__":
    unittest.main()
