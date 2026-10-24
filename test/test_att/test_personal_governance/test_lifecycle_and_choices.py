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
    TokenLimitExceededError,
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
            persistence_mode="volatile",
        )
        self.manager.register_llm_client("default", self.client)
        self.addAsyncCleanup(self.manager.close)
        self.principal = ApprovalPrincipal(kind="agent", principal_id=self.root.agent_id)

    def resource_scope(self):
        replacement = PersonalGovernanceClient(respond=False)
        self.manager.register_llm_client("spare", replacement)
        self.manager.config.failover_policy = "parent"
        self.manager.config.model_token_limits["default"] = 0
        # Governance has its own available binding; the requester owns the exhausted one.
        self.root.llm_client = replacement
        team = self.manager.create_agent_team(self.root, parent=self.root,
            member_configs={name: {"model": "default"} for name in ("A", "B", "C")})
        error = TokenLimitExceededError("Resource exhausted.")
        error.required_tokens = 1
        return team, error

    async def test_failover_timeout_closes_authority_but_retains_mail(self):
        team, error = self.resource_scope()
        result = await self.manager.request_model_resource(team.members[0], team, error)
        self.assertEqual(result.status, "PENDING")
        async with asyncio.timeout(5):
            while not any(case.status == "EXPIRED" for case in self.manager._governance.cases.values()):
                await asyncio.sleep(0.001)
        item = next(iter(self.manager._governance.cases.values()))
        token = self.manager._active_tool_agent.set(self.root)
        try:
            result = await self.manager.submit_governance_choice(
                item.case_id, {"model_alias": "spare"}, actor=self.root)
        finally:
            self.manager._active_tool_agent.reset(token)
        self.assertEqual(result.status, "CLOSED")
        self.assertFalse(self.manager._governance.cases[item.case_id].ballots)
        self.assertEqual(len(self.root.agent_inbox), 1)

    async def test_cancelled_case_observer_does_not_expire_an_accepted_resource_attempt(self):
        self.manager.config.parent_failover_timeout_seconds = 5
        team, error = self.resource_scope()
        committed = asyncio.Event()
        original_commit = self.manager._records.commit

        async def pause_after_commit(*args, **kwargs):
            result = await original_commit(*args, **kwargs)
            if str(kwargs.get("operation_id", "")).startswith("CASE-"):
                committed.set()
                await asyncio.Event().wait()
            return result

        with patch.object(self.manager._records, "commit", side_effect=pause_after_commit):
            result = await self.manager.request_model_resource(team.members[0], team, error)
            await asyncio.wait_for(committed.wait(), 5)
            task = self.manager._failover.tasks[f"prepare:{result.attempt_id}"]
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        item = next(iter(self.manager._governance.cases.values()))
        row = self.manager._records.index[("resource_decisions", (result.attempt_id,))]
        self.assertEqual(row.values["status"], "pending")
        self.assertEqual(item.status, "PENDING")
        self.assertEqual(len(self.root.agent_inbox), 1)

    async def test_close_cancels_hanging_personal_notification(self):
        entered = asyncio.Event()

        async def hanging_generate(**kwargs):
            entered.set()
            await asyncio.Event().wait()

        self.client.generate = hanging_generate
        first = self.manager.create_agent_team(self.root, parent=self.root)
        second = self.manager.create_agent_team(self.root, parent=self.root)
        result = await self.manager.broker.request_peer_communication(
            first, second, first.members[0].agent_id, "Public request."
        )
        await asyncio.wait_for(entered.wait(), timeout=2)
        await asyncio.wait_for(self.manager.close(), timeout=2)
        self.assertEqual(
            self.manager.broker.communication_requests[result.request_id].status.value, "PENDING"
        )
        self.assertFalse(next(iter(self.manager._governance.cases.values())).ballots)

    async def test_formation_four_attitudes_are_independent_of_email_read_state(self):
        invitees = [Agent(f"Invitee-{number}", "Independent", self.client) for number in range(4)]
        for agent in invitees:
            self.manager.register_agent(agent)
        request = self.manager.create_agent_team(
            self.root, parent=self.root, member_count=4, existing_members=invitees
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
        self.assertFalse(self.manager._governance.cases)
