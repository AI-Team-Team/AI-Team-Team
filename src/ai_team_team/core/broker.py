"""Configuration-owned AgentTeam communication requests and agreements."""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .communication import (
    AgreementDirection,
    ApprovalPrincipal,
    CommunicationAgreement,
    CommunicationApproval,
    CommunicationApprovalStatus,
    CommunicationBallot,
    CommunicationOperationResult,
    CommunicationRequest,
    CommunicationRequestStatus,
    PeerMessage,
    route_fingerprint,
)
from .config import _parse_communication_config
from .decision import DecisionOutcome, TeamDecisionProvider
from .team import AgentTeam


class NegotiationBroker:
    """Persists and executes ATT-configured communication governance."""

    def __init__(self, manager: Any):
        self.manager = manager
        self.logger = logging.getLogger("ATT.Communication")
        self.communication_requests: Dict[str, CommunicationRequest] = {}
        self.communication_approvals: Dict[
            str, CommunicationApproval
        ] = {}
        self.ballots: Dict[str, List[CommunicationBallot]] = {}
        self.agreements: Dict[str, CommunicationAgreement] = {}
        self.peer_messages: Dict[str, PeerMessage] = {}
        self._state_lock = asyncio.Lock()
        self._transaction_lock = asyncio.Lock()
        self._approval_tasks: Dict[str, asyncio.Task[Any]] = {}
        self._decision_provider: Optional[TeamDecisionProvider] = None

    @asynccontextmanager
    async def _locked_state(self):
        """Serializes mutations against both peers and state snapshots."""
        async with self._state_lock:
            with self.manager._snapshot_lock:
                yield

    @property
    def decision_provider(self) -> TeamDecisionProvider:
        if self._decision_provider is None:
            self._decision_provider = TeamDecisionProvider(self.manager)
        return self._decision_provider

    def approvals_for_request(
        self, request_id: str
    ) -> List[CommunicationApproval]:
        return sorted(
            (
                approval
                for approval in self.communication_approvals.values()
                if approval.request_id == request_id
            ),
            key=lambda approval: approval.sequence,
        )

    def _parent_principal(self, team: AgentTeam) -> ApprovalPrincipal:
        parent = team.parent_team or self.manager.find_parent_team(team)
        if parent is not None:
            return ApprovalPrincipal(
                kind="agent_team", principal_id=parent.team_id
            )
        return ApprovalPrincipal(
            kind="agent", principal_id=self.manager.root_ai.agent_id
        )

    @staticmethod
    def _deduplicate(
        principals: Iterable[ApprovalPrincipal],
    ) -> List[ApprovalPrincipal]:
        result: List[ApprovalPrincipal] = []
        seen = set()
        for principal in principals:
            if principal.key in seen:
                continue
            seen.add(principal.key)
            result.append(principal)
        return result

    def approval_path(
        self,
        sender: AgentTeam,
        recipient: AgentTeam,
        policy: Optional[Any] = None,
    ) -> List[ApprovalPrincipal]:
        policy = policy or self.manager.config.communication
        if policy.policy == "permissive":
            return []
        if policy.policy == "parent_approval":
            return self._deduplicate(
                [
                    self._parent_principal(sender),
                    self._parent_principal(recipient),
                ]
            )

        sender_chain: List[AgentTeam] = []
        current: Optional[AgentTeam] = sender
        while current is not None:
            sender_chain.append(current)
            current = current.parent_team
        recipient_chain: List[AgentTeam] = []
        current = recipient
        while current is not None:
            recipient_chain.append(current)
            current = current.parent_team

        recipient_index = {
            team.team_id: index
            for index, team in enumerate(recipient_chain)
        }
        lca_sender_index = None
        lca_recipient_index = None
        for index, team in enumerate(sender_chain):
            if team.team_id in recipient_index:
                lca_sender_index = index
                lca_recipient_index = recipient_index[team.team_id]
                break

        route: List[ApprovalPrincipal] = []
        if lca_sender_index is None:
            route.extend(
                ApprovalPrincipal(kind="agent_team", principal_id=team.team_id)
                for team in sender_chain[1:]
            )
            route.append(
                ApprovalPrincipal(
                    kind="agent", principal_id=self.manager.root_ai.agent_id
                )
            )
            route.extend(
                ApprovalPrincipal(kind="agent_team", principal_id=team.team_id)
                for team in reversed(recipient_chain)
            )
        else:
            route.extend(
                ApprovalPrincipal(kind="agent_team", principal_id=team.team_id)
                for team in sender_chain[1 : lca_sender_index + 1]
            )
            route.extend(
                ApprovalPrincipal(kind="agent_team", principal_id=team.team_id)
                for team in reversed(
                    recipient_chain[:lca_recipient_index]
                )
            )
        return self._deduplicate(route)

    def active_agreement(
        self, sender_team_id: str, recipient_team_id: str
    ) -> Optional[CommunicationAgreement]:
        matches = [
            agreement
            for agreement in self.agreements.values()
            if agreement.permits(sender_team_id, recipient_team_id)
        ]
        if not matches:
            return None
        return max(matches, key=lambda agreement: agreement.created_at)

    def active_agreement_for_request(
        self,
        sender_team_id: str,
        recipient_team_id: str,
        direction: AgreementDirection,
    ) -> Optional[CommunicationAgreement]:
        """Finds a channel that fully satisfies the requested direction."""
        matches = []
        endpoint_pair = {sender_team_id, recipient_team_id}
        for agreement in self.agreements.values():
            if not agreement.active:
                continue
            if direction is AgreementDirection.BIDIRECTIONAL:
                if (
                    agreement.direction is AgreementDirection.BIDIRECTIONAL
                    and {
                        agreement.source_team_id,
                        agreement.target_team_id,
                    }
                    == endpoint_pair
                ):
                    matches.append(agreement)
            elif agreement.permits(sender_team_id, recipient_team_id):
                matches.append(agreement)
        if not matches:
            return None
        return max(matches, key=lambda agreement: agreement.created_at)

    def _validate_endpoints_and_actor(
        self,
        sender: AgentTeam,
        recipient: AgentTeam,
        initiated_by_agent_id: str,
    ) -> None:
        if self.manager.teams.get(sender.team_id) is not sender:
            raise ValueError("The sender AgentTeam is not registered.")
        if self.manager.teams.get(recipient.team_id) is not recipient:
            raise ValueError("The recipient AgentTeam is not registered.")
        actor = self.manager._agents_by_id.get(initiated_by_agent_id)
        if (
            actor is None
            or actor.lifecycle_state != "active"
            or all(
                member.agent_id != initiated_by_agent_id
                for member in sender.members
            )
        ):
            raise PermissionError(
                "The initiating Agent is not an active sender AgentTeam member."
            )

    def _equivalent_pending_request(
        self,
        sender_team_id: str,
        recipient_team_id: str,
        direction: AgreementDirection,
        policy_snapshot: Dict[str, Any],
    ) -> Optional[CommunicationRequest]:
        requested_pair = {sender_team_id, recipient_team_id}
        for request in self.communication_requests.values():
            if request.status not in {
                CommunicationRequestStatus.PENDING,
                CommunicationRequestStatus.PROCESSING,
            }:
                continue
            pair = {request.sender_team_id, request.recipient_team_id}
            same_endpoints = (
                pair == requested_pair
                if direction is AgreementDirection.BIDIRECTIONAL
                else request.sender_team_id == sender_team_id
                and request.recipient_team_id == recipient_team_id
            )
            if (
                same_endpoints
                and request.direction is direction
                and request.policy_snapshot == policy_snapshot
            ):
                return request
        return None

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

    async def send_peer_message(
        self,
        sender: AgentTeam,
        recipient: AgentTeam,
        initiated_by_agent_id: str,
        content: str,
        *,
        invocation_id: Optional[str] = None,
    ) -> CommunicationOperationResult:
        async with self._transaction_lock:
            return await self._send_peer_message_transaction(
                sender,
                recipient,
                initiated_by_agent_id,
                content,
                invocation_id=invocation_id,
            )

    async def _send_peer_message_transaction(
        self,
        sender: AgentTeam,
        recipient: AgentTeam,
        initiated_by_agent_id: str,
        content: str,
        *,
        invocation_id: Optional[str] = None,
    ) -> CommunicationOperationResult:
        self._validate_endpoints_and_actor(
            sender, recipient, initiated_by_agent_id
        )
        if sender is recipient:
            return CommunicationOperationResult(
                status="NO_AGREEMENT",
                reason="Peer communication requires a different AgentTeam.",
                team_id=recipient.team_id,
            )
        policy = self.manager.config.communication
        async with self._locked_state():
            agreement = None
            if policy.policy != "permissive":
                agreement = self.active_agreement(
                    sender.team_id, recipient.team_id
                )
                if agreement is None:
                    return CommunicationOperationResult(
                        status="NO_AGREEMENT",
                        reason=(
                            "No active communication channel permits this "
                            "route. Call request_peer_communication() first."
                        ),
                        team_id=recipient.team_id,
                    )
            if invocation_id:
                existing = next(
                    (
                        message
                        for message in self.peer_messages.values()
                        if message.invocation_id == invocation_id
                    ),
                    None,
                )
                if existing is not None:
                    if (
                        existing.sender_team_id != sender.team_id
                        or existing.recipient_team_id != recipient.team_id
                        or existing.initiated_by_agent_id
                        != initiated_by_agent_id
                        or existing.content != content
                    ):
                        raise ValueError(
                            "The tool invocation ID is already bound to a "
                            "different peer message."
                        )
                    return CommunicationOperationResult(
                        status="DELIVERED",
                        reason="The peer message was already delivered.",
                        message_id=existing.message_id,
                        agreement_id=existing.agreement_id,
                        team_id=existing.recipient_team_id,
                    )
            peer_message = PeerMessage(
                sender_team_id=sender.team_id,
                recipient_team_id=recipient.team_id,
                initiated_by_agent_id=initiated_by_agent_id,
                agreement_id=(agreement.agreement_id if agreement else None),
                content=content,
                invocation_id=invocation_id,
            )
            self.peer_messages[peer_message.message_id] = peer_message
            with recipient.inbox_lock:
                recipient.message_inbox.append(
                    peer_message.to_inbox_message()
                )

        dirty = self.manager._new_dirty_state()
        dirty["peer_messages"].add(peer_message.message_id)
        dirty["inboxes"].add(recipient.team_id)
        try:
            await self.manager._commit_dirty_state(dirty)
        except Exception:
            async with self._locked_state():
                self.peer_messages.pop(peer_message.message_id, None)
                with recipient.inbox_lock:
                    recipient.message_inbox = [
                        item
                        for item in recipient.message_inbox
                        if item.get("message_id") != peer_message.message_id
                    ]
            raise
        self.manager._emit_callback(
            "on_system_event",
            "peer_message_delivered",
            {
                "message_id": peer_message.message_id,
                "sender_team_id": sender.team_id,
                "recipient_team_id": recipient.team_id,
                "agreement_id": peer_message.agreement_id,
            },
        )
        return CommunicationOperationResult(
            status="DELIVERED",
            reason="The peer message was durably delivered.",
            message_id=peer_message.message_id,
            agreement_id=peer_message.agreement_id,
            team_id=recipient.team_id,
        )

    async def revoke_agreement(
        self, agreement_id: str, actor_team_id: str, reason: str
    ) -> CommunicationOperationResult:
        async with self._transaction_lock:
            return await self._revoke_agreement_transaction(
                agreement_id, actor_team_id, reason
            )

    async def _revoke_agreement_transaction(
        self, agreement_id: str, actor_team_id: str, reason: str
    ) -> CommunicationOperationResult:
        async with self._locked_state():
            agreement = self.agreements.get(agreement_id)
            if agreement is None:
                return CommunicationOperationResult(
                    status="FORBIDDEN", reason="Unknown communication agreement."
                )
            if actor_team_id not in {
                agreement.source_team_id,
                agreement.target_team_id,
            }:
                return CommunicationOperationResult(
                    status="FORBIDDEN",
                    reason="Only an endpoint AgentTeam may revoke this agreement.",
                    agreement_id=agreement_id,
                )
            if not agreement.active:
                return CommunicationOperationResult(
                    status="ALREADY_REVOKED",
                    reason="The agreement is already inactive.",
                    agreement_id=agreement_id,
                )
            agreement_before = agreement.model_copy(deep=True)
            agreement.active = False
            agreement.revoked_at = time.time()
            agreement.revoked_by_team_id = actor_team_id
            agreement.revoke_reason = reason

        dirty = self.manager._new_dirty_state()
        dirty["communication_agreements"].add(agreement_id)
        try:
            await self.manager._commit_dirty_state(dirty)
        except Exception:
            async with self._locked_state():
                self.agreements[agreement_id] = agreement_before
            raise
        self.manager._emit_callback(
            "on_system_event",
            "communication_agreement_revoked",
            {
                "agreement_id": agreement_id,
                "revoked_by_team_id": actor_team_id,
            },
        )
        return CommunicationOperationResult(
            status="REVOKED",
            reason="The communication agreement was revoked.",
            agreement_id=agreement_id,
        )

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
