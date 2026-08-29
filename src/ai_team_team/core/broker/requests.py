"""Communication request creation, notification, and scheduling."""

from __future__ import annotations

import asyncio
from typing import Any, List, Optional

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
        request = CommunicationRequest(
            sender_team_id=sender.team_id,
            recipient_team_id=recipient.team_id,
            initiated_by_agent_id=initiated_by_agent_id,
            rationale=rationale,
            direction=AgreementDirection(policy.direction),
            policy_snapshot=policy.model_dump(mode="json"),
            approval_principals=principals,
            route_fingerprint=route_fingerprint(principals),
            supersedes_request_id=supersedes_request_id,
        )
        self.communication_requests[request.request_id] = request
        for sequence, principal in enumerate(principals):
            approval = CommunicationApproval(
                request_id=request.request_id,
                principal=principal,
                sequence=sequence,
            )
            self.communication_approvals[approval.key] = approval
        return request

    def _enqueue_request_notifications(
        self, request: CommunicationRequest
    ) -> set[str]:
        changed_inboxes: set[str] = set()
        for principal in request.approval_principals:
            if principal.kind != "agent_team":
                continue
            team = self.manager.teams.get(principal.principal_id)
            if team is None:
                continue
            with team.inbox_lock:
                if not any(
                    message.get("type") == "communication_approval_request"
                    and message.get("request_id") == request.request_id
                    for message in team.message_inbox
                ):
                    team.message_inbox.append(
                        {
                            "type": "communication_approval_request",
                            "request_id": request.request_id,
                            "from": request.sender_team_id,
                            "recipient_team_id": request.recipient_team_id,
                            "reason": request.rationale,
                            "state": "pending",
                        }
                    )
                    changed_inboxes.add(team.team_id)
        return changed_inboxes

    async def request_peer_communication(
        self,
        sender: AgentTeam,
        recipient: AgentTeam,
        initiated_by_agent_id: str,
        rationale: str,
    ) -> CommunicationOperationResult:
        async with self._transaction_lock:
            return await self._request_peer_communication_transaction(
                sender,
                recipient,
                initiated_by_agent_id,
                rationale,
            )

    async def _request_peer_communication_transaction(
        self,
        sender: AgentTeam,
        recipient: AgentTeam,
        initiated_by_agent_id: str,
        rationale: str,
    ) -> CommunicationOperationResult:
        self._validate_endpoints_and_actor(
            sender, recipient, initiated_by_agent_id
        )
        if sender is recipient:
            return CommunicationOperationResult(
                status="DENIED",
                reason="An AgentTeam cannot request a peer channel to itself.",
                team_id=recipient.team_id,
            )
        policy = self.manager.config.communication
        if policy.policy == "permissive":
            return CommunicationOperationResult(
                status="APPROVED",
                reason="Permissive communication does not require an agreement.",
                team_id=recipient.team_id,
            )
        policy_snapshot = policy.model_dump(mode="json")
        direction = AgreementDirection(policy.direction)
        async with self._locked_state():
            agreement = self.active_agreement_for_request(
                sender.team_id, recipient.team_id, direction
            )
            if agreement is not None:
                return CommunicationOperationResult(
                    status="ALREADY_ACTIVE",
                    reason=(
                        "An active communication agreement already permits "
                        "this route."
                    ),
                    agreement_id=agreement.agreement_id,
                    team_id=recipient.team_id,
                )
            duplicate = self._equivalent_pending_request(
                sender.team_id,
                recipient.team_id,
                direction,
                policy_snapshot,
            )
            if duplicate is not None:
                return CommunicationOperationResult(
                    status="PENDING_APPROVAL",
                    reason="An equivalent communication request is already pending.",
                    request_id=duplicate.request_id,
                    team_id=recipient.team_id,
                )
            request = self._new_request_locked(
                sender,
                recipient,
                initiated_by_agent_id,
                rationale,
                policy,
            )
            changed_inboxes = self._enqueue_request_notifications(request)

        dirty = self.manager._new_dirty_state()
        dirty["communication_requests"].add(request.request_id)
        dirty["communication_approvals"].add(request.request_id)
        dirty["inboxes"].update(changed_inboxes)
        try:
            await self.manager._commit_dirty_state(dirty)
        except Exception:
            async with self._locked_state():
                self.communication_requests.pop(request.request_id, None)
                for approval in list(
                    self.approvals_for_request(request.request_id)
                ):
                    self.communication_approvals.pop(approval.key, None)
                self.ballots.pop(request.request_id, None)
                self._remove_request_notifications(request.request_id)
            raise
        self.manager._emit_callback(
            "on_system_event",
            "communication_request_created",
            {
                "request_id": request.request_id,
                "sender_team_id": sender.team_id,
                "recipient_team_id": recipient.team_id,
                "initiated_by_agent_id": initiated_by_agent_id,
                "approval_principals": [
                    principal.model_dump(mode="json")
                    for principal in request.approval_principals
                ],
            },
        )
        self._schedule_initial_approvals(request)
        return CommunicationOperationResult(
            status="PENDING_APPROVAL",
            reason="The communication channel request is pending approval.",
            request_id=request.request_id,
            team_id=recipient.team_id,
        )

    def _schedule_initial_approvals(
        self, request: CommunicationRequest
    ) -> None:
        delivery = request.policy_snapshot.get("request_delivery", "queue")
        for principal in request.approval_principals:
            if principal.kind == "agent":
                self._schedule_agent_approval(request.request_id, principal)
            elif delivery == "wake":
                self._schedule_team_wakeup(request.request_id, principal)

    def _track_task(self, key: str, coroutine: Any) -> None:
        existing = self._approval_tasks.get(key)
        if existing is not None and not existing.done():
            close = getattr(coroutine, "close", None)
            if close is not None:
                close()
            return
        task = asyncio.create_task(coroutine, name=f"att-approval-{key}")
        self._approval_tasks[key] = task
        self.manager._emergency_tasks.add(task)

        def completed(done: asyncio.Task[Any]) -> None:
            self._approval_tasks.pop(key, None)
            self.manager._emergency_tasks.discard(done)
            try:
                done.result()
            except asyncio.CancelledError:
                pass
            except Exception:
                self.logger.exception("Communication approval task failed.")

        task.add_done_callback(completed)

    def _schedule_agent_approval(
        self, request_id: str, principal: ApprovalPrincipal
    ) -> None:
        self._track_task(
            f"{request_id}:{principal.key}",
            self._process_agent_approval(request_id, principal),
        )

    def _schedule_team_wakeup(
        self, request_id: str, principal: ApprovalPrincipal
    ) -> None:
        async def wake() -> None:
            request = self.communication_requests.get(request_id)
            team = self.manager.teams.get(principal.principal_id)
            if request is None or team is None:
                return
            prompt = self._request_prompt(request, principal)
            await self.manager.execute_team_discussion(team, prompt, rounds=1)

        self._track_task(f"{request_id}:{principal.key}", wake())

    def queued_request_ids_for_team(self, team_id: str) -> List[str]:
        result = []
        for approval in self.communication_approvals.values():
            if (
                approval.principal.kind == "agent_team"
                and approval.principal.principal_id == team_id
                and approval.status
                in {
                    CommunicationApprovalStatus.PENDING,
                    CommunicationApprovalStatus.PROCESSING,
                }
            ):
                request = self.communication_requests.get(approval.request_id)
                if request is not None and request.status in {
                    CommunicationRequestStatus.PENDING,
                    CommunicationRequestStatus.PROCESSING,
                }:
                    result.append(request.request_id)
        return sorted(set(result))

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

