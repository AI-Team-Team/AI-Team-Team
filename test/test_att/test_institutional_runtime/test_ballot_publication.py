"""Ballot visibility and cancellation are tied to exact accepted operations."""

import asyncio
from unittest.mock import patch

from ai_team_team import ATTConfig, Agent, ParentApprovalCommunicationConfig, StatePersistenceError
from test.governance_client import PersonalGovernanceClient, settle_governance_activity
from test.test_att.test_agent_activity._support import ActivityTestCase


class BallotPublicationTests(ActivityTestCase):
    async def pending_case(self):
        self.root = Agent("Governor", "Architect", PersonalGovernanceClient(native=True, respond=False))
        self.manager = self.make_manager(self.root, config=ATTConfig(
            workspace_root=self.workspace.name, tool_calling_mode="native",
            communication=ParentApprovalCommunicationConfig(),
        ))
        sender = self.manager.create_agent_team(self.root, parent=self.root)
        recipient = self.manager.create_agent_team(self.root, parent=self.root)
        result = await self.manager.broker.request_peer_communication(
            sender, recipient, sender.members[0].agent_id, "Explicit channel authority."
        )
        await settle_governance_activity(self.manager)
        case = next(item for item in self.manager._governance.cases.values() if item.business_id == result.request_id)
        return case

    async def submit(self, case):
        token = self.manager._active_tool_agent.set(self.root)
        try:
            return await self.manager.submit_governance_choice(case.case_id, {"approved": True, "reason": "Explicit choice."}, actor=self.root)
        finally:
            self.manager._active_tool_agent.reset(token)

    async def test_failed_or_preacceptance_cancelled_vote_has_no_public_authority(self):
        case = await self.pending_case()
        history = list(self.root.message_history)
        for failure in (StatePersistenceError("Rejected receipt"), asyncio.CancelledError()):
            with self.subTest(failure=type(failure).__name__):
                with patch.object(self.manager._records, "commit", side_effect=failure):
                    with self.assertRaises(type(failure)):
                        await self.submit(case)
                current = self.manager._governance.cases[case.case_id]
                self.assertEqual(current.status, "PENDING")
                self.assertFalse(current.ballots)
                self.assertEqual(self.root.message_history, history)
                self.assertFalse(self.manager.broker.agreements)

    async def test_candidate_is_not_visible_before_acknowledgement(self):
        case = await self.pending_case()
        started, release = asyncio.Event(), asyncio.Event()
        original = self.manager._records._settle_publication

        async def hold(*args, **kwargs):
            started.set()
            await release.wait()
            return await original(*args, **kwargs)

        with patch.object(self.manager._records, "_settle_publication", hold):
            task = asyncio.create_task(self.submit(case))
            try:
                await started.wait()
                self.assertFalse(self.manager._governance.cases[case.case_id].ballots)
                self.assertFalse(self.manager.broker.agreements)
            finally:
                release.set()
            await task
        await settle_governance_activity(self.manager)
        self.assertEqual(self.manager._governance.cases[case.case_id].status, "APPROVED")
        self.assertEqual(len(self.manager.broker.agreements), 1)

    async def test_receipt_owned_cancellation_preserves_committed_choice(self):
        case = await self.pending_case()
        original = self.manager._records.commit

        async def cancel_after_receipt(*args, **kwargs):
            result = await original(*args, **kwargs)
            if str(kwargs.get("operation_id", "")).startswith("BALLOT-"):
                raise asyncio.CancelledError
            return result

        with patch.object(self.manager._records, "commit", cancel_after_receipt):
            with self.assertRaises(asyncio.CancelledError):
                await self.submit(case)
        await settle_governance_activity(self.manager)
        current = self.manager._governance.cases[case.case_id]
        self.assertEqual(current.status, "APPROVED")
        self.assertEqual(len(current.ballots), 1)
        self.assertEqual(len(self.manager.broker.agreements), 1)
