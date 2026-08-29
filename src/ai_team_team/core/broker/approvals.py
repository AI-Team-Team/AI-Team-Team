"""Communication approval claims, decisions, and atomic completion."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional, Sequence

from ..communication import (
    AgreementDirection,
    ApprovalPrincipal,
    CommunicationAgreement,
    CommunicationApproval,
    CommunicationApprovalStatus,
    CommunicationBallot,
    CommunicationRequest,
    CommunicationRequestStatus,
    route_fingerprint,
)
from ..config import _parse_communication_config
from ..decision import DecisionOutcome
from ..team import AgentTeam


class BrokerApprovalMixin:
    async def _claim_approval(
        self, request_id: str, principal: ApprovalPrincipal
    ) -> Optional[CommunicationApproval]:
        async with self._locked_state():
            request = self.communication_requests.get(request_id)
            key = f"{request_id}:{principal.key}"
            approval = self.communication_approvals.get(key)
            if (
                request is None
                or approval is None
                or request.status
                not in {
                    CommunicationRequestStatus.PENDING,
                    CommunicationRequestStatus.PROCESSING,
                }
                or approval.status is not CommunicationApprovalStatus.PENDING
            ):
                return None
            approval.status = CommunicationApprovalStatus.PROCESSING
            request.status = CommunicationRequestStatus.PROCESSING
        self.manager._auto_save(
            communication_requests={request_id},
            communication_approvals={request_id},
        )
        return approval

    async def _process_agent_approval(
        self, request_id: str, principal: ApprovalPrincipal
    ) -> None:
        approval = await self._claim_approval(request_id, principal)
        if approval is None:
            return
        request = self.communication_requests[request_id]
        try:
            outcome = await self.decision_provider.decide_agent_boolean(
                principal, self._request_prompt(request, principal)
            )
        except asyncio.CancelledError:
            await asyncio.shield(
                self._complete_approval(
                    request_id,
                    principal,
                    DecisionOutcome(
                        "pending", "Agent governance decision was cancelled."
                    ),
                )
            )
            raise
        except Exception as exc:
            outcome = DecisionOutcome(
                "pending", f"Agent governance decision failed: {exc}"
            )
        await self._complete_approval(request_id, principal, outcome)

    async def process_team_approvals_from_transcript(
        self,
        team: AgentTeam,
        request_ids: Sequence[str],
        transcript: str,
        members: Sequence[Any],
    ) -> None:
        principal = ApprovalPrincipal(
            kind="agent_team", principal_id=team.team_id
        )
        for request_id in request_ids:
            approval = await self._claim_approval(request_id, principal)
            if approval is None:
                continue
            request = self.communication_requests[request_id]
            try:
                outcome = await self.decision_provider.ballot_team_boolean(
                    principal,
                    request_id,
                    self._request_prompt(request, principal),
                    transcript,
                    members,
                )
            except asyncio.CancelledError:
                await asyncio.shield(
                    self._complete_approval(
                        request_id,
                        principal,
                        DecisionOutcome(
                            "pending",
                            "AgentTeam governance decision was cancelled.",
                        ),
                    )
                )
                raise
            except Exception as exc:
                outcome = DecisionOutcome(
                    "pending", f"AgentTeam governance decision failed: {exc}"
                )
            await self._complete_approval(request_id, principal, outcome)

    def _remove_request_notifications(self, request_id: str) -> set[str]:
        changed = set()
        for team in self.manager.teams.values():
            with team.inbox_lock:
                retained = [
                    message
                    for message in team.message_inbox
                    if not (
                        message.get("type")
                        == "communication_approval_request"
                        and message.get("request_id") == request_id
                    )
                ]
                if len(retained) != len(team.message_inbox):
                    team.message_inbox = retained
                    changed.add(team.team_id)
        return changed

    def _remove_principal_notification(
        self, request_id: str, principal: ApprovalPrincipal
    ) -> set[str]:
        if principal.kind != "agent_team":
            return set()
        team = self.manager.teams.get(principal.principal_id)
        if team is None:
            return set()
        with team.inbox_lock:
            retained = [
                message
                for message in team.message_inbox
                if not (
                    message.get("type")
                    == "communication_approval_request"
                    and message.get("request_id") == request_id
                )
            ]
            if len(retained) == len(team.message_inbox):
                return set()
            team.message_inbox = retained
        return {team.team_id}

    def _create_agreement_locked(
        self, request: CommunicationRequest
    ) -> CommunicationAgreement:
        agreement = CommunicationAgreement(
            source_team_id=request.sender_team_id,
            target_team_id=request.recipient_team_id,
            direction=request.direction,
            created_from_request_id=request.request_id,
            policy_snapshot=dict(request.policy_snapshot),
        )
        if agreement.direction is AgreementDirection.BIDIRECTIONAL:
            endpoints = {
                agreement.source_team_id,
                agreement.target_team_id,
            }
            for existing in self.agreements.values():
                if (
                    existing.active
                    and {
                        existing.source_team_id,
                        existing.target_team_id,
                    }
                    == endpoints
                ):
                    existing.active = False
                    existing.revoked_at = time.time()
                    existing.revoke_reason = (
                        "Superseded by a bidirectional agreement."
                    )
                    existing.superseded_by_agreement_id = agreement.agreement_id
        self.agreements[agreement.agreement_id] = agreement
        return agreement

    async def _complete_approval(
        self,
        request_id: str,
        principal: ApprovalPrincipal,
        outcome: DecisionOutcome,
    ) -> None:
        async with self._transaction_lock:
            await self._complete_approval_transaction(
                request_id, principal, outcome
            )

    async def _complete_approval_transaction(
        self,
        request_id: str,
        principal: ApprovalPrincipal,
        outcome: DecisionOutcome,
    ) -> None:
        successor: Optional[CommunicationRequest] = None
        new_agreement: Optional[CommunicationAgreement] = None
        changed_agreements: set[str] = set()
        request_before: Optional[CommunicationRequest] = None
        approvals_before: Dict[str, CommunicationApproval] = {}
        ballots_before: List[CommunicationBallot] = []
        agreements_before: Dict[str, CommunicationAgreement] = {}
        request_notifications_before: Dict[
            str, List[Dict[str, Any]]
        ] = {}
        async with self._locked_state():
            request = self.communication_requests.get(request_id)
            approval = self.communication_approvals.get(
                f"{request_id}:{principal.key}"
            )
            if request is None or approval is None:
                return
            if (
                approval.status is not CommunicationApprovalStatus.PROCESSING
                or request.status
                not in {
                    CommunicationRequestStatus.PENDING,
                    CommunicationRequestStatus.PROCESSING,
                }
            ):
                return
            request_before = request.model_copy(deep=True)
            approvals_before = {
                item.key: item.model_copy(deep=True)
                for item in self.approvals_for_request(request_id)
            }
            ballots_before = [
                item.model_copy(deep=True)
                for item in self.ballots.get(request_id, [])
            ]
            agreements_before = {
                key: value.model_copy(deep=True)
                for key, value in self.agreements.items()
            }
            for team in self.manager.teams.values():
                with team.inbox_lock:
                    notifications = [
                        dict(message)
                        for message in team.message_inbox
                        if message.get("type")
                        == "communication_approval_request"
                        and message.get("request_id") == request_id
                    ]
                if notifications:
                    request_notifications_before[team.team_id] = notifications
            retained_ballots = [
                ballot
                for ballot in self.ballots.get(request_id, [])
                if ballot.principal != principal
            ]
            self.ballots[request_id] = retained_ballots + list(
                outcome.ballots
            )
            approval.reason = outcome.reason
            if outcome.status == "pending":
                approval.status = CommunicationApprovalStatus.PENDING
                request.status = CommunicationRequestStatus.PENDING
            elif outcome.status == "denied":
                approval.status = CommunicationApprovalStatus.DENIED
                approval.resolved_at = time.time()
                request.status = CommunicationRequestStatus.DENIED
                request.decision_reason = outcome.reason
                request.resolved_at = time.time()
                for other in self.approvals_for_request(request_id):
                    if other.status in {
                        CommunicationApprovalStatus.PENDING,
                        CommunicationApprovalStatus.PROCESSING,
                    }:
                        other.status = CommunicationApprovalStatus.CANCELLED
                        other.reason = "The request was denied by another principal."
                        other.resolved_at = time.time()
            else:
                approval.status = CommunicationApprovalStatus.APPROVED
                approval.resolved_at = time.time()
                approvals = self.approvals_for_request(request_id)
                if all(
                    item.status is CommunicationApprovalStatus.APPROVED
                    for item in approvals
                ):
                    policy = _parse_communication_config(
                        request.policy_snapshot
                    )
                    sender = self.manager.teams.get(request.sender_team_id)
                    recipient = self.manager.teams.get(
                        request.recipient_team_id
                    )
                    current_path = (
                        self.approval_path(sender, recipient, policy)
                        if sender is not None and recipient is not None
                        else []
                    )
                    if (
                        sender is None
                        or recipient is None
                        or route_fingerprint(current_path)
                        != request.route_fingerprint
                    ):
                        request.status = CommunicationRequestStatus.STALE
                        request.decision_reason = (
                            "The relevant topology route changed during approval."
                        )
                        request.resolved_at = time.time()
                        if sender is not None and recipient is not None:
                            successor = self._new_request_locked(
                                sender,
                                recipient,
                                request.initiated_by_agent_id,
                                request.rationale,
                                policy,
                                supersedes_request_id=request.request_id,
                            )
                            request.superseded_by_request_id = (
                                successor.request_id
                            )
                    else:
                        request.status = CommunicationRequestStatus.APPROVED
                        request.decision_reason = "All required principals approved."
                        request.resolved_at = time.time()
                        before = {
                            agreement.agreement_id
                            for agreement in self.agreements.values()
                            if agreement.active
                        }
                        new_agreement = self._create_agreement_locked(request)
                        changed_agreements = before | {new_agreement.agreement_id}
                else:
                    request.status = CommunicationRequestStatus.PENDING

            terminal = request.status in {
                CommunicationRequestStatus.APPROVED,
                CommunicationRequestStatus.DENIED,
                CommunicationRequestStatus.STALE,
            }
            changed_inboxes = (
                self._remove_request_notifications(request_id)
                if terminal
                else self._remove_principal_notification(
                    request_id, principal
                )
                if outcome.status == "approved"
                else set()
            )
            if successor is not None:
                changed_inboxes.update(
                    self._enqueue_request_notifications(successor)
                )

        dirty = self.manager._new_dirty_state()
        dirty["communication_requests"].add(request_id)
        dirty["communication_approvals"].add(request_id)
        dirty["communication_agreements"].update(changed_agreements)
        dirty["inboxes"].update(changed_inboxes)
        if successor is not None:
            dirty["communication_requests"].add(successor.request_id)
            dirty["communication_approvals"].add(successor.request_id)
        try:
            await self.manager._commit_dirty_state(dirty)
        except Exception:
            async with self._locked_state():
                if request_before is not None:
                    self.communication_requests[request_id] = request_before
                if successor is not None:
                    self.communication_requests.pop(successor.request_id, None)
                for item in list(self.approvals_for_request(request_id)):
                    self.communication_approvals.pop(item.key, None)
                self.communication_approvals.update(approvals_before)
                restored_request = self.communication_requests.get(request_id)
                restored_approval = self.communication_approvals.get(
                    f"{request_id}:{principal.key}"
                )
                if (
                    restored_request is not None
                    and restored_request.status
                    is CommunicationRequestStatus.PROCESSING
                ):
                    restored_request.status = CommunicationRequestStatus.PENDING
                if (
                    restored_approval is not None
                    and restored_approval.status
                    is CommunicationApprovalStatus.PROCESSING
                ):
                    restored_approval.status = CommunicationApprovalStatus.PENDING
                if successor is not None:
                    for item in list(
                        self.approvals_for_request(successor.request_id)
                    ):
                        self.communication_approvals.pop(item.key, None)
                self.ballots[request_id] = ballots_before
                self.agreements = agreements_before
                rollback_request_ids = {request_id}
                if successor is not None:
                    rollback_request_ids.add(successor.request_id)
                for team in self.manager.teams.values():
                    with team.inbox_lock:
                        team.message_inbox = [
                            message
                            for message in team.message_inbox
                            if not (
                                message.get("type")
                                == "communication_approval_request"
                                and message.get("request_id")
                                in rollback_request_ids
                            )
                        ]
                        team.message_inbox.extend(
                            request_notifications_before.get(
                                team.team_id, []
                            )
                        )
            raise
        self.manager._emit_callback(
            "on_system_event",
            "communication_approval_updated",
            {
                "request_id": request_id,
                "principal": principal.model_dump(mode="json"),
                "status": outcome.status,
                "reason": outcome.reason,
            },
        )
        if successor is not None:
            self._schedule_initial_approvals(successor)
        if new_agreement is not None:
            self.manager._emit_callback(
                "on_system_event",
                "communication_agreement_created",
                {
                    "agreement_id": new_agreement.agreement_id,
                    "request_id": request_id,
                    "source_team_id": new_agreement.source_team_id,
                    "target_team_id": new_agreement.target_team_id,
                    "direction": new_agreement.direction.value,
                },
            )
