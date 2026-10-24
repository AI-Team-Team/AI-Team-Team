"""Communication request creation, notification, and scheduling."""

from __future__ import annotations

import asyncio
import contextvars
from typing import Any, Optional

from ..communication import (
    AgreementDirection,
    ApprovalPrincipal,
    CommunicationApproval,
    CommunicationApprovalStatus,
    CommunicationOperationResult,
    CommunicationRequest,
    CommunicationRequestStatus,
    route_fingerprint,
)
from ..team import AgentTeam
from ..exceptions import RuntimeAdmissionClosedError


class BrokerRequestMixin:
    def _new_request_locked(
        self,
        sender: AgentTeam,
        recipient: AgentTeam,
        initiated_by_agent_id: str,
        rationale: str,
        policy: Any,
        *,
        supersedes_request_id: Optional[str] = None,
    ) -> CommunicationRequest:
        principals = self.approval_path(sender, recipient, policy)
        evidence = self.approval_route_evidence(sender, recipient, policy)
        request = CommunicationRequest(
            sender_team_id=sender.team_id,
            recipient_team_id=recipient.team_id,
            initiated_by_agent_id=initiated_by_agent_id,
            rationale=rationale,
            direction=AgreementDirection(policy.direction),
            policy_snapshot=policy.model_dump(mode="json"),
            approval_principals=principals,
            route_fingerprint=route_fingerprint(principals, evidence),
            route_evidence=evidence,
            supersedes_request_id=supersedes_request_id,
            created_at=self.manager._activity.clock.wall_time(),
        )
        self.communication_requests[request.request_id] = request
        for sequence, principal in enumerate(principals):
            approval = CommunicationApproval(
                request_id=request.request_id,
                principal=principal,
                sequence=sequence,
                created_at=self.manager._activity.clock.wall_time(),
            )
            self.communication_approvals[approval.key] = approval
        return request

    async def request_peer_communication(
        self,
        sender: AgentTeam,
        recipient: AgentTeam,
        initiated_by_agent_id: str,
        rationale: str,
    ) -> CommunicationOperationResult:
        manager = self.manager
        async with self._transaction_lock, manager._topology.transition_lock, manager._activity.lock:
            if manager._closing or manager._restore_in_progress:
                raise RuntimeError("Communication admission is closed.")
            self._validate_endpoints_and_actor(sender, recipient, initiated_by_agent_id)
            if sender is recipient:
                return CommunicationOperationResult(status="DENIED", reason="Peer endpoints must differ.", team_id=recipient.team_id)
            policy = manager.config.communication
            if policy.policy == "permissive" or sender.is_independent and recipient.is_independent:
                return CommunicationOperationResult(status="APPROVED",
                    reason="No channel is required by the effective communication institution.", team_id=recipient.team_id)
            existing = self.active_agreement_for_request(sender.team_id, recipient.team_id, AgreementDirection(policy.direction))
            if existing is not None:
                return CommunicationOperationResult(status="ALREADY_ACTIVE", reason="An applicable channel is active.",
                    agreement_id=existing.agreement_id, team_id=recipient.team_id)
            duplicate = self._equivalent_pending_request(sender.team_id, recipient.team_id,
                AgreementDirection(policy.direction), policy.model_dump(mode="json"))
            if duplicate is not None and not self.route_changed(duplicate):
                # An explicit renewed request may solicit a fresh case after a
                # tie; retaining the same business request does not invent votes.
                self._schedule_initial_approvals(duplicate)
                return CommunicationOperationResult(status="PENDING_APPROVAL", reason="An equivalent request is pending.",
                    request_id=duplicate.request_id, team_id=recipient.team_id)
            with self.stage() as candidate:
                dirty = manager._new_dirty_state()
                if duplicate is not None:
                    stale = duplicate.model_copy(deep=True)
                    self.communication_requests[stale.request_id] = stale
                    request = self.stale_candidate(stale, dirty)
                else:
                    request = self._new_request_locked(sender, recipient, initiated_by_agent_id, rationale, policy)
                dirty["communication_requests"].add(request.request_id)
                dirty["communication_approvals"].add(request.request_id)
                operation_id = f"REQUEST-{request.request_id}"
                try:
                    await manager._records.commit((), dirty=dirty, broker_state=candidate, operation_id=operation_id)
                finally:
                    if operation_id in manager._records.receipts:
                        self._schedule_initial_approvals(request)
                        if duplicate is not None:
                            self.cancel_obsolete_cases(duplicate.request_id)
            manager._emit_callback("on_system_event", "communication_request_created",
                {"request_id": request.request_id, "sender_team_id": sender.team_id, "recipient_team_id": recipient.team_id,
                 "initiated_by_agent_id": initiated_by_agent_id})
            return CommunicationOperationResult(status="PENDING_APPROVAL", reason="Explicit principal choices are pending.",
                request_id=request.request_id, team_id=recipient.team_id)

    def _schedule_initial_approvals(
        self, request: CommunicationRequest
    ) -> None:
        for principal in request.approval_principals:
            self._track_task(f"{request.request_id}:{principal.key}",
                self._process_principal_approval(request.request_id, principal))

    def _track_task(self, key: str, coroutine: Any) -> None:
        existing = self._approval_tasks.get(key)
        if self.manager._closing or existing is not None and not existing.done():
            close = getattr(coroutine, "close", None)
            if close is not None:
                close()
            return
        task = asyncio.create_task(coroutine, name=f"att-approval-{key}", context=contextvars.Context())
        self._approval_tasks[key] = task
        self.manager._institutional_tasks.add(task)

        def completed(done: asyncio.Task[Any]) -> None:
            if self._approval_tasks.get(key) is done:
                self._approval_tasks.pop(key, None)
            self.manager._institutional_tasks.discard(done)
            try:
                done.result()
            except asyncio.CancelledError:
                pass
            except RuntimeAdmissionClosedError:
                self.manager._emit_callback("on_system_event", "communication_approval_admission_deferred",
                    {"operation_key": key, "reason": "runtime_admission_closed"})
            except Exception:
                self.logger.exception("Communication approval task failed.")

        task.add_done_callback(completed)

    def _request_prompt(
        self, request: CommunicationRequest, principal: ApprovalPrincipal
    ) -> str:
        return (
            "Decide whether your governance principal approves an ATT "
            "communication channel.\n\n"
            f"Request ID: {request.request_id}\n"
            f"Sender AgentTeam: {request.sender_team_id}\n"
            f"Recipient AgentTeam: {request.recipient_team_id}\n"
            f"Direction: {request.direction.value}\n"
            f"Rationale: {request.rationale}\n"
            f"Approving principal: {principal.kind}:{principal.principal_id}"
        )
