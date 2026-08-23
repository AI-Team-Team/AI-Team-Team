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
