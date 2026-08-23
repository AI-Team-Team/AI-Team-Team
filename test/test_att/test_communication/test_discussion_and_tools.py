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
