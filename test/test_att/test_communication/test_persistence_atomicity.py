from test.governance_client import approve_pending_business, settle_governance_activity, submit_case_ballots
import os
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from ai_team_team import (
    Agent,
    ParentApprovalCommunicationConfig,
    PermissiveCommunicationConfig,
    StateRestoreError,
)
from ai_team_team.core.communication import CommunicationRequestStatus
from ai_team_team.core.decision import DecisionOutcome
from ai_team_team.core.manager.communication_validation.successors import (
    validate_successors_and_ballots,
)
from ai_team_team.database.persistence.coordinator import PersistenceCoordinator


from test.test_att.test_communication._support import CommunicationTestCase


class TestAutonomousCommunication(CommunicationTestCase):

    async def test_missing_nested_successor_is_reported_as_corrupt_state(self):
        first = SimpleNamespace(
            request_id="REQ-first",
            status=CommunicationRequestStatus.STALE,
            superseded_by_request_id="REQ-second",
            supersedes_request_id=None,
        )
        second = SimpleNamespace(
            request_id="REQ-second",
            status=CommunicationRequestStatus.STALE,
            superseded_by_request_id="REQ-missing",
            supersedes_request_id="REQ-first",
        )
        with self.assertRaisesRegex(StateRestoreError, "missing successor"):
            validate_successors_and_ballots(
                [first, second],
                [],
                [],
                {first.request_id: first, second.request_id: second},
                set(),
            )

    async def test_current_schema_restores_pending_request_and_delivery(self):
        await self._assert_pending_request_and_delivery_round_trip()

    async def test_pending_request_and_delivery_survive_slow_writes(self):
        original_write = PersistenceCoordinator._write

        def slow_write(coordinator, db_path, snapshot):
            # Runs on the real persistence worker, not the discussion event loop.
            time.sleep(0.1)
            return original_write(coordinator, db_path, snapshot)

        with patch.object(PersistenceCoordinator, "_write", slow_write):
            await self._assert_pending_request_and_delivery_round_trip()

    async def _assert_pending_request_and_delivery_round_trip(self):
        self.client.respond = False
        db_path = os.path.join(self.workspace, "communication.db")
        source = self.manager(
            ParentApprovalCommunicationConfig(), db_path=db_path
        )
        parent_a = source.create_agent_team(self.root, parent=self.root, member_count=3)
        parent_b = source.create_agent_team(self.root, parent=self.root, member_count=3)
        sender = source.create_agent_team(parent_a, parent=parent_a, member_count=3)
        recipient = source.create_agent_team(parent_b, parent=parent_b, member_count=3)
        result = await source.broker.request_peer_communication(
            sender, recipient, sender.members[0].agent_id, "persist request"
        )
        await source.save_state()
        await source.close()

        restored = self.manager(
            root_ai=Agent("RestoreRoot", "Root governor", self.client),
        )
        await restored.load_state(db_path)
        request = restored.broker.communication_requests[result.request_id]
        self.assertEqual(request.status.value, "PENDING")
        await settle_governance_activity(restored)
        self.assertTrue(any(case.business_id == request.request_id and case.status == "PENDING"
                            for case in restored._governance.cases.values()))
        await approve_pending_business(restored, request.request_id)
        request = await self.wait_for_status(request, "APPROVED")
        delivered = await restored.broker.send_peer_message(
            restored.teams[sender.team_id],
            restored.teams[recipient.team_id],
            restored.teams[sender.team_id].members[0].agent_id,
            "durable",
            invocation_id="restore-delivery",
        )
        await restored.save_state()
        await restored.close()

        final = self.manager(
            root_ai=Agent("FinalRoot", "Root governor", self.client),
        )
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
        self.client.respond = False
        governed = self.manager(ParentApprovalCommunicationConfig())
        parent_a = governed.create_agent_team(self.root, parent=self.root, member_count=3)
        parent_b = governed.create_agent_team(self.root, parent=self.root, member_count=3)
        sender = governed.create_agent_team(parent_a, parent=parent_a, member_count=3)
        recipient = governed.create_agent_team(parent_b, parent=parent_b, member_count=3)
        with patch.object(
            governed._records,
            "commit",
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
        await settle_governance_activity(governed)
        case = governed._governance.latest("communication", request.request_id, approval.principal)
        with patch.object(governed._governance, "schedule_resolution"):
            await submit_case_ballots(governed, case)

        async def fail_after_unrelated_inbox_change(*args, **kwargs):
            with parent_a.inbox_lock:
                parent_a.message_inbox.append(
                    {"type": "unrelated", "reason": "preserve me"}
                )
            raise OSError("approval disk failure")

        with patch.object(
            governed._records,
            "commit",
            side_effect=fail_after_unrelated_inbox_change,
        ):
            with self.assertRaisesRegex(OSError, "approval disk failure"):
                await governed.broker._complete_approval(
                    request.request_id,
                    approval.principal,
                    governed.broker.decision_provider.outcome(governed._governance.cases[case.case_id]),
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
        self.assertTrue(any(mail["payload"].get("request_id") == request.request_id
                            for voter in parent_a.members for mail in voter.agent_inbox))
        await governed.close()

        direct = self.manager(PermissiveCommunicationConfig())
        first = direct.create_agent_team(self.root, parent=self.root, member_count=3)
        second = direct.create_agent_team(self.root, parent=self.root, member_count=3)
        with patch.object(
            direct._records,
            "commit",
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
