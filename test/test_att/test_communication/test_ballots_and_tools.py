"""Normal personal activity supplies explicit votes without a team session."""

import json

from ai_team_team import ParentApprovalCommunicationConfig, ToolBusinessError
from ai_team_team.core.manager.activity.values import ModelUnavailable
from test.governance_client import PersonalGovernanceClient, settle_governance_activity
from test.test_att.test_communication._support import CommunicationTestCase


class TestAutonomousCommunication(CommunicationTestCase):
    async def test_queue_delivers_ballots_without_a_separate_team_activity(self):
        manager = self.manager(ParentApprovalCommunicationConfig())
        parent = manager.create_agent_team(self.root, parent=self.root)
        sender = manager.create_agent_team(parent, parent=parent)
        recipient = manager.create_agent_team(parent, parent=parent)
        result = await manager.broker.request_peer_communication(
            sender, recipient, sender.members[0].agent_id, "Voluntary personal ballots."
        )
        request = manager.broker.communication_requests[result.request_id]
        await self.wait_for_status(request, "APPROVED")
        self.assertEqual(len(manager.broker.agreements), 1)
        self.assertFalse(hasattr(parent, "discussion_lock"))
        self.assertFalse(hasattr(manager, "execute_team_discussion"))

    async def test_missing_personal_ballot_keeps_collective_authority_pending(self):
        manager = self.manager(ParentApprovalCommunicationConfig())
        parent = manager.create_agent_team(self.root, parent=self.root)
        sender = manager.create_agent_team(parent, parent=parent)
        recipient = manager.create_agent_team(parent, parent=parent)

        class UnavailableClient:
            def supports_native_tool_calling(self):
                return False

            async def generate(self, **kwargs):
                raise RuntimeError("A synthetic unavailable adapter.")

        client = UnavailableClient()
        manager.register_llm_client("unavailable-voter", client)
        parent.members[0].llm_client = client
        result = await manager.broker.request_peer_communication(
            sender, recipient, sender.members[0].agent_id, "Every predefined voter is required."
        )
        with self.assertRaises(ModelUnavailable):
            await settle_governance_activity(manager)
        case = next(item for item in manager._governance.cases.values() if item.business_id == result.request_id)
        self.assertEqual(len(case.ballots), len(case.voter_agent_ids) - 1)
        self.assertEqual(manager.broker.communication_requests[result.request_id].status.value, "PENDING")
        self.assertFalse(manager.broker.agreements)

    async def test_committed_vote_survives_a_later_ordinary_tool_failure(self):
        manager = self.manager(ParentApprovalCommunicationConfig())
        parent = manager.create_agent_team(self.root, parent=self.root)
        sender = manager.create_agent_team(parent, parent=parent)
        recipient = manager.create_agent_team(parent, parent=parent)

        class VoteThenFail(PersonalGovernanceClient):
            async def generate(self, prompt=None, **kwargs):
                if prompt and '"status":"SUBMITTED"' in (prompt[-1].get("content") or "").replace(" ", ""):
                    return "Action: ordinary_failure()"
                return await super().generate(prompt=prompt, **kwargs)

        async def ordinary_failure():
            raise ToolBusinessError("An unrelated ordinary operation was refused.")

        client = VoteThenFail()
        manager.register_llm_client("vote-then-fail", client)
        parent.members[0].llm_client = client
        manager.register_tool("ordinary_failure", func=ordinary_failure)
        result = await manager.broker.request_peer_communication(
            sender, recipient, sender.members[0].agent_id, "The accepted choice is already authoritative."
        )
        request = manager.broker.communication_requests[result.request_id]
        await self.wait_for_status(request, "APPROVED")
        await self.wait_for_governance_idle(request)
        self.assertTrue(any("ordinary_failure" in str(call[0]) for call in client.calls))
        self.assertTrue(manager.broker.agreements)

    async def test_tools_require_current_identity_and_do_not_accept_policy_overrides(self):
        manager = self.manager(ParentApprovalCommunicationConfig())
        first = manager.create_agent_team(self.root, parent=self.root)
        second = manager.create_agent_team(self.root, parent=self.root)
        tool = first.tools["request_peer_communication"]
        for field in ("mode", "policy", "sender_team_id"):
            self.assertNotIn(field, tool.json_schema["properties"])
        outside = json.loads(await tool(second.team_id, "coordinate"))
        self.assertEqual(outside["status"], "DENIED")
        team_token = manager._active_team.set(first)
        actor_token = manager._active_tool_agent.set(first.members[0])
        try:
            inside = json.loads(await tool(team_id=second.team_id, rationale="coordinate"))
        finally:
            manager._active_tool_agent.reset(actor_token)
            manager._active_team.reset(team_token)
        self.assertEqual(inside["status"], "PENDING_APPROVAL")
        await self.wait_for_governance_idle(manager.broker.communication_requests[inside["request_id"]])
