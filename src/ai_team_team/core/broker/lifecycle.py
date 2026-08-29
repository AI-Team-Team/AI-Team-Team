"""Broker restoration, pending-work resumption, and shutdown reset."""

from __future__ import annotations

from typing import Any, Dict, Iterable

from ..communication import (
    CommunicationAgreement,
    CommunicationApproval,
    CommunicationApprovalStatus,
    CommunicationBallot,
    CommunicationRequest,
    CommunicationRequestStatus,
    PeerMessage,
)


class BrokerLifecycleMixin:
    def restore(
        self,
        requests: Iterable[Dict[str, Any]],
        approvals: Iterable[Dict[str, Any]],
        ballots: Iterable[Dict[str, Any]],
        agreements: Iterable[Dict[str, Any]],
        peer_messages: Iterable[Dict[str, Any]],
    ) -> None:
        self.communication_requests = {
            item.request_id: item
            for item in (
                CommunicationRequest.model_validate(row) for row in requests
            )
        }
        self.communication_approvals = {}
        for row in approvals:
            approval = CommunicationApproval.model_validate(row)
            if approval.status is CommunicationApprovalStatus.PROCESSING:
                approval.status = CommunicationApprovalStatus.PENDING
            self.communication_approvals[approval.key] = approval
        self.ballots = {}
        for row in ballots:
            ballot = CommunicationBallot.model_validate(row)
            self.ballots.setdefault(ballot.request_id, []).append(ballot)
        self.agreements = {
            item.agreement_id: item
            for item in (
                CommunicationAgreement.model_validate(row)
                for row in agreements
            )
        }
        self.peer_messages = {
            item.message_id: item
            for item in (PeerMessage.model_validate(row) for row in peer_messages)
        }
        for request in self.communication_requests.values():
            if request.status is CommunicationRequestStatus.PROCESSING:
                request.status = CommunicationRequestStatus.PENDING

    def resume_pending_requests(self) -> None:
        for request in self.communication_requests.values():
            if request.status in {
                CommunicationRequestStatus.PENDING,
                CommunicationRequestStatus.PROCESSING,
            }:
                self._schedule_initial_approvals(request)

    async def reset_processing_for_shutdown(self) -> None:
        """Durably releases Approval claims without waiting on external models."""
        changed_request_ids: set[str] = set()
        async with self._transaction_lock:
            async with self._locked_state():
                for approval in self.communication_approvals.values():
                    if (
                        approval.status
                        is CommunicationApprovalStatus.PROCESSING
                    ):
                        approval.status = CommunicationApprovalStatus.PENDING
                        approval.reason = (
                            "Governance processing was interrupted by manager shutdown."
                        )
                        approval.resolved_at = None
                        changed_request_ids.add(approval.request_id)
                for request_id in changed_request_ids:
                    request = self.communication_requests.get(request_id)
                    if (
                        request is not None
                        and request.status
                        is CommunicationRequestStatus.PROCESSING
                    ):
                        request.status = CommunicationRequestStatus.PENDING
                        request.resolved_at = None
            if changed_request_ids:
                dirty = self.manager._new_dirty_state()
                dirty["communication_requests"].update(changed_request_ids)
                dirty["communication_approvals"].update(changed_request_ids)
                await self.manager._commit_dirty_state(dirty)
