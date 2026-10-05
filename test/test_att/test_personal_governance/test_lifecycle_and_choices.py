import asyncio
import tempfile
import unittest
from unittest.mock import patch

from ai_team_team import (
    ATTConfig,
    ATTManager,
    Agent,
    ApprovalPrincipal,
    ParentApprovalCommunicationConfig,
)
from test.governance_client import PersonalGovernanceClient


class GovernanceLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.workspace = tempfile.TemporaryDirectory(prefix="att-governance-lifecycle-")
        self.addCleanup(self.workspace.cleanup)
        self.client = PersonalGovernanceClient(respond=False)
        self.root = Agent("Root", "Root", self.client)
        self.manager = ATTManager(
            self.root,
            ATTConfig(
                workspace_root=self.workspace.name,
                enable_memory_compression=False,
                parent_failover_timeout_seconds=0.05,
                communication=ParentApprovalCommunicationConfig(),
            ),
        )
        self.manager.register_llm_client("default", self.client)
        self.addAsyncCleanup(self.manager.close)
        self.principal = ApprovalPrincipal(kind="agent", principal_id=self.root.agent_id)

    async def test_failover_timeout_closes_authority_but_retains_mail(self):
        with self.assertRaises(asyncio.TimeoutError):
            await self.manager.broker.decision_provider.decide_agent_model(
                self.principal, "Choose a replacement model.", ["spare"]
            )
        item = next(iter(self.manager._governance.rounds.values()))
        self.assertEqual(item.status, "EXPIRED")
        token = self.manager._active_tool_agent.set(self.root)
        try:
            result = await self.manager.submit_governance_choice(
                item.round_id, {"model_alias": "spare"}, actor=self.root
            )
        finally:
            self.manager._active_tool_agent.reset(token)
        self.assertEqual(result.status, "CLOSED")
        self.assertFalse(item.ballots)
        self.assertEqual(len(self.root.agent_inbox), 1)
        self.assertEqual(self.manager._governance.waiters, {})

    async def test_cancellation_during_committed_round_creation_expires_attempt(self):
        self.manager.config.parent_failover_timeout_seconds = 5
        committed = asyncio.Event()
        original_commit = self.manager._commit_dirty_state

        async def pause_after_commit(dirty):
            await original_commit(dirty)
            if dirty["governance_rounds"] and any(
                item.status == "PENDING" for item in self.manager._governance.rounds.values()
            ):
                committed.set()
                await asyncio.Event().wait()

        with patch.object(self.manager, "_commit_dirty_state", side_effect=pause_after_commit):
            task = asyncio.create_task(
                self.manager.broker.decision_provider.decide_agent_model(
                    self.principal, "Choose a replacement model.", ["spare"]
                )
            )
            await asyncio.wait_for(committed.wait(), timeout=2)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        item = next(iter(self.manager._governance.rounds.values()))
        self.assertEqual(item.status, "EXPIRED")
        self.assertEqual(len(self.root.agent_inbox), 1)
        self.assertEqual(self.manager._governance.waiters, {})

    async def test_close_cancels_hanging_personal_notification(self):
        entered = asyncio.Event()

        async def hanging_generate(**kwargs):
            entered.set()
            await asyncio.Event().wait()

        self.client.generate = hanging_generate
        first = self.manager.create_agent_team(self.root)
        second = self.manager.create_agent_team(self.root)
        result = await self.manager.broker.request_peer_communication(
            first, second, first.members[0].agent_id, "Public request."
        )
        await asyncio.wait_for(entered.wait(), timeout=2)
        await asyncio.wait_for(self.manager.close(), timeout=2)
        self.assertEqual(
            self.manager.broker.communication_requests[result.request_id].status.value, "PENDING"
        )
        self.assertFalse(next(iter(self.manager._governance.rounds.values())).ballots)

    async def test_formation_four_attitudes_are_independent_of_email_read_state(self):
        invitees = [Agent(f"Invitee-{number}", "Independent", self.client) for number in range(4)]
        for agent in invitees:
            self.manager.register_agent(agent)
        request = self.manager.create_agent_team(
            self.root, member_count=4, existing_members=invitees
        )
        for actor, attitude in zip(invitees, ("accepted", "declined", "explicitly_ignored", None)):
            self.assertTrue(all(message["read_at"] is None for message in actor.agent_inbox))
            await self.manager.respond_team_invitation(
                request.request_id,
                actor=actor,
                proposal_revision=request.proposal_revision,
                attitude=attitude,
            )
            self.assertTrue(all(message["read_at"] is None for message in actor.agent_inbox))
            await self.manager.mark_agent_inbox_read(actor.agent_id)
        summary = self.manager.inspect_team_formation(request.request_id, actor=self.root).summary
        self.assertEqual(
            (summary.accepted, summary.declined, summary.explicitly_ignored, summary.no_response),
            (1, 1, 1, 1),
        )
        self.assertFalse(self.manager._governance.rounds)
