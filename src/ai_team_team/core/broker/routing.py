"""Approval routing, endpoint validation, and agreement lookup."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from ..communication import (
    AgreementDirection,
    ApprovalPrincipal,
    CommunicationAgreement,
    CommunicationApproval,
    CommunicationRequest,
    CommunicationRequestStatus,
)
from ..team import AgentTeam


class BrokerRoutingMixin:
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

