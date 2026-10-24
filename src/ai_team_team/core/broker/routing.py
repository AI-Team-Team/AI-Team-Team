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

    def approval_path(self, sender: AgentTeam, recipient: AgentTeam, policy=None):
        from ..organization import communication_route

        policy = policy or self.manager.config.communication
        parents = {key: team.organizational_parent for key, team in self.manager.teams.items()}
        return communication_route(sender.team_id, recipient.team_id, parents, policy.policy,
            {key: team._position_revision for key, team in self.manager.teams.items()})[0]

    def approval_route_evidence(self, sender: AgentTeam, recipient: AgentTeam, policy=None):
        from ..organization import communication_route

        policy = policy or self.manager.config.communication
        parents = {key: team.organizational_parent for key, team in self.manager.teams.items()}
        return communication_route(sender.team_id, recipient.team_id, parents, policy.policy,
            {key: team._position_revision for key, team in self.manager.teams.items()})[1]

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
        if sender.team_kind != "ordinary" or recipient.team_kind != "ordinary":
            raise PermissionError("System AgentTeams cannot be peer communication endpoints.")
        if any(getattr(team, "_lifecycle_state", "active") != "active" or getattr(team, "_publication_pending", False)
               for team in (sender, recipient)):
            raise PermissionError("Peer communication requires active published AgentTeam endpoints.")
        actor = self.manager._agents_by_id.get(initiated_by_agent_id)
        current = self.manager._active_tool_agent.get()
        if current is not None and (current is not actor or self.manager._active_team.get() is not sender):
            raise PermissionError("A tool cannot override its current Agent or AgentTeam.")
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
