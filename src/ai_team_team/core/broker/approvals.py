"""Receipt-published approvals backed only by explicit personal ballots."""

import time

from ..communication import (
    AgreementDirection, CommunicationAgreement, CommunicationApprovalStatus,
    CommunicationRequestStatus, route_fingerprint,
)
from ..config import _parse_communication_config
from ..decision import TeamDecisionProvider


class BrokerApprovalMixin:
    async def _claim_approval(self, request_id, principal):
        request = self.communication_requests.get(request_id)
        approval = self.communication_approvals.get(f"{request_id}:{principal.key}")
        if (request is None or approval is None
                or request.status not in {CommunicationRequestStatus.PENDING, CommunicationRequestStatus.PROCESSING}
                or approval.status not in {CommunicationApprovalStatus.PENDING, CommunicationApprovalStatus.PROCESSING}):
            return None
        # This is a local scheduling claim, not authority or a nested model call.
        return approval

    async def _process_principal_approval(self, request_id, principal):
        if await self._claim_approval(request_id, principal) is None:
            return
        request = self.communication_requests[request_id]
        outcome = await self.decision_provider.decide_principal_boolean(
            principal, request_id, self._request_prompt(request, principal), business_kind="communication"
        )
        if outcome.status != "pending":
            await self._complete_approval(request_id, principal, outcome)

    def _create_agreement_locked(self, request):
        existing = self.active_agreement_for_request(
            request.sender_team_id, request.recipient_team_id, request.direction
        )
        if existing is not None:
            return existing, set()
        agreement = CommunicationAgreement(
            source_team_id=request.sender_team_id, target_team_id=request.recipient_team_id,
            direction=request.direction, created_from_request_id=request.request_id,
            policy_snapshot=dict(request.policy_snapshot),
        )
        changed = {agreement.agreement_id}
        if agreement.direction is AgreementDirection.BIDIRECTIONAL:
            pair = {agreement.source_team_id, agreement.target_team_id}
            for key, prior in tuple(self.agreements.items()):
                if prior.active and {prior.source_team_id, prior.target_team_id} == pair:
                    replacement = prior.model_copy(deep=True)
                    replacement.active = False
                    replacement.revoked_at = time.time()
                    replacement.revoke_reason = "Superseded by a bidirectional agreement."
                    replacement.superseded_by_agreement_id = agreement.agreement_id
                    self.agreements[key] = replacement
                    changed.add(key)
        self.agreements[agreement.agreement_id] = agreement
        return agreement, changed

    def route_changed(self, request):
        sender = self.manager.teams.get(request.sender_team_id)
        recipient = self.manager.teams.get(request.recipient_team_id)
        if any(team is None or getattr(team, "_lifecycle_state", "active") != "active"
               for team in (sender, recipient)):
            return True
        policy = _parse_communication_config(request.policy_snapshot)
        return route_fingerprint(self.approval_path(sender, recipient, policy),
            self.approval_route_evidence(sender, recipient, policy)) != request.route_fingerprint

    def stale_candidate(self, request, dirty):
        """Never reuse a changed route's ballots, even if it later changes back."""
        request.status = CommunicationRequestStatus.STALE
        request.decision_reason = "The relevant organizational route changed."
        request.resolved_at = time.time()
        for prior in self.approvals_for_request(request.request_id):
            if prior.status in {CommunicationApprovalStatus.PENDING, CommunicationApprovalStatus.PROCESSING}:
                approval = prior.model_copy(deep=True)
                approval.status = CommunicationApprovalStatus.CANCELLED
                approval.reason = "The originating route became stale."
                approval.resolved_at = request.resolved_at
                self.communication_approvals[approval.key] = approval
        dirty["communication_requests"].add(request.request_id)
        dirty["communication_approvals"].add(request.request_id)
        sender = self.manager.teams.get(request.sender_team_id)
        recipient = self.manager.teams.get(request.recipient_team_id)
        if any(team is None or getattr(team, "_lifecycle_state", "active") != "active"
               for team in (sender, recipient)):
            return None
        successor = self._new_request_locked(sender, recipient, request.initiated_by_agent_id,
            request.rationale, _parse_communication_config(request.policy_snapshot),
            supersedes_request_id=request.request_id)
        request.superseded_by_request_id = successor.request_id
        if not successor.approval_principals:
            successor.status = CommunicationRequestStatus.APPROVED
            successor.decision_reason = "Both endpoints are now explicitly independent; no authority or channel is required."
            successor.resolved_at = time.time()
        dirty["communication_requests"].add(successor.request_id)
        dirty["communication_approvals"].add(successor.request_id)
        return successor

    def schedule_route_review(self):
        for request in tuple(self.communication_requests.values()):
            if request.status in {CommunicationRequestStatus.PENDING, CommunicationRequestStatus.PROCESSING}:
                self._track_task(f"route:{request.request_id}", self.review_route(request.request_id))

    async def review_route(self, request_id):
        manager = self.manager
        async with self._transaction_lock, manager._governance.lock, manager._topology.transition_lock, manager._activity.lock:
            original = self.communication_requests.get(request_id)
            if (original is None or original.status not in {
                    CommunicationRequestStatus.PENDING, CommunicationRequestStatus.PROCESSING}
                    or not self.route_changed(original)):
                return
            operation_id = f"STALE-{request_id}"
            successor = None
            with self.stage() as candidate:
                request = original.model_copy(deep=True)
                self.communication_requests[request_id] = request
                dirty = manager._new_dirty_state()
                successor = self.stale_candidate(request, dirty)
                try:
                    await manager._records.commit((), dirty=dirty, broker_state=candidate, operation_id=operation_id)
                finally:
                    if operation_id in manager._records.receipts:
                        self.cancel_obsolete_cases(request_id)
                        if successor is not None:
                            self._schedule_initial_approvals(successor)

    def cancel_obsolete_cases(self, request_id):
        for case in tuple(self.manager._governance.cases.values()):
            if case.business_kind == "communication" and case.business_id == request_id and case.status == "PENDING":
                self.manager._governance.track(f"expire:{case.case_id}",
                    self.manager._governance.expire(case.case_id, "The originating request is resolved or stale."))

    async def _complete_approval(self, request_id, principal, outcome):
        manager = self.manager
        async with self._transaction_lock, manager._governance.lock, manager._topology.transition_lock, manager._activity.lock:
            original = self.communication_requests.get(request_id)
            approval = self.communication_approvals.get(f"{request_id}:{principal.key}")
            if original is None or approval is None or original.status not in {
                    CommunicationRequestStatus.PENDING, CommunicationRequestStatus.PROCESSING}:
                return
            case = manager._governance.latest("communication", request_id, principal)
            if (case is None or case.case_id != outcome.case_id or not manager._governance.electorate_valid(case)):
                return
            outcome = TeamDecisionProvider.outcome(case)
            if outcome.status == "pending":
                return
            operation_id = f"APPROVAL-{case.case_id}"
            successor, agreement = None, None
            with self.stage() as candidate:
                request = original.model_copy(deep=True)
                self.communication_requests[request_id] = request
                dirty = manager._new_dirty_state()
                dirty["communication_requests"].add(request_id)
                dirty["communication_approvals"].add(request_id)
                if self.route_changed(request):
                    successor = self.stale_candidate(request, dirty)
                else:
                    decided = approval.model_copy(deep=True)
                    decided.case_id = case.case_id
                    decided.status = (CommunicationApprovalStatus.APPROVED if outcome.status == "approved"
                        else CommunicationApprovalStatus.DENIED)
                    decided.reason, decided.resolved_at = outcome.reason, time.time()
                    self.communication_approvals[decided.key] = decided
                    self.ballots[request_id] = [
                        ballot for ballot in self.ballots.get(request_id, ()) if ballot.principal != principal
                    ] + list(outcome.ballots)
                    if outcome.status == "denied":
                        request.status = CommunicationRequestStatus.DENIED
                        request.decision_reason, request.resolved_at = outcome.reason, time.time()
                        for other in self.approvals_for_request(request_id):
                            if other.status in {CommunicationApprovalStatus.PENDING, CommunicationApprovalStatus.PROCESSING}:
                                item = other.model_copy(deep=True)
                                item.status, item.reason, item.resolved_at = (
                                    CommunicationApprovalStatus.CANCELLED, "Another principal explicitly denied.", time.time())
                                self.communication_approvals[item.key] = item
                    else:
                        approvals = self.approvals_for_request(request_id)
                        for item in approvals:
                            voted = manager._governance.latest("communication", request_id, item.principal)
                            if item.status is CommunicationApprovalStatus.APPROVED and (
                                    voted is None or voted.status != "APPROVED" or not manager._governance.electorate_valid(voted)):
                                item = item.model_copy(deep=True)
                                item.status, item.reason, item.resolved_at = CommunicationApprovalStatus.PENDING, "A new electorate case is required.", None
                                item.case_id = None
                                self.ballots[request_id] = [ballot for ballot in self.ballots.get(request_id, ())
                                    if ballot.principal != item.principal]
                                self.communication_approvals[item.key] = item
                        if all(item.status is CommunicationApprovalStatus.APPROVED for item in self.approvals_for_request(request_id)):
                            request.status = CommunicationRequestStatus.APPROVED
                            request.decision_reason, request.resolved_at = "All required principals explicitly approved.", time.time()
                            agreement, changed = self._create_agreement_locked(request)
                            dirty["communication_agreements"].update(changed)
                try:
                    await manager._records.commit((), dirty=dirty, broker_state=candidate, operation_id=operation_id)
                finally:
                    if operation_id in manager._records.receipts:
                        if request.status not in {CommunicationRequestStatus.PENDING, CommunicationRequestStatus.PROCESSING}:
                            self.cancel_obsolete_cases(request_id)
                        if successor is not None:
                            self._schedule_initial_approvals(successor)
            manager._emit_callback("on_system_event", "communication_approval_updated",
                {"request_id": request_id, "principal": principal.model_dump(mode="json"), "status": outcome.status})
            if agreement is not None:
                manager._emit_callback("on_system_event", "communication_agreement_created",
                    {"request_id": request_id, "agreement_id": agreement.agreement_id})
