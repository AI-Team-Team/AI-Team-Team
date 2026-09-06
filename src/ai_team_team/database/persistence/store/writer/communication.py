"""Communication request, approval, Agreement, and delivery writes."""

from typing import Any, Dict, Iterable

from ai_team_team.database.models import (
    CommunicationAgreementModel,
    CommunicationApprovalModel,
    CommunicationBallotModel,
    CommunicationRequestModel,
    PeerMessageModel,
)


class CommunicationWriteMixin:
    @staticmethod
    def _write_communication_requests(session: Any, requests: Iterable[Dict[str, Any]]) -> None:
        for request in requests:
            session.merge(
                CommunicationRequestModel(
                    request_id=request["request_id"],
                    sender_team_id=request["sender_team_id"],
                    recipient_team_id=request["recipient_team_id"],
                    initiated_by_agent_id=request.get("initiated_by_agent_id"),
                    rationale=request["rationale"],
                    direction=request["direction"],
                    policy_snapshot=request["policy_snapshot"],
                    approval_principals=request["approval_principals"],
                    route_fingerprint=request["route_fingerprint"],
                    status=request["status"],
                    decision_reason=request.get("decision_reason", ""),
                    created_at=request["created_at"],
                    resolved_at=request.get("resolved_at"),
                    superseded_by_request_id=request.get("superseded_by_request_id"),
                    supersedes_request_id=request.get("supersedes_request_id"),
                )
            )

    @staticmethod
    def _write_communication_approvals(
        session: Any,
        approvals: Iterable[Dict[str, Any]],
        ballots: Iterable[Dict[str, Any]],
    ) -> None:
        request_ids = {approval["request_id"] for approval in approvals}
        for request_id in request_ids:
            session.query(CommunicationBallotModel).filter_by(request_id=request_id).delete(
                synchronize_session=False
            )
            session.query(CommunicationApprovalModel).filter_by(request_id=request_id).delete(
                synchronize_session=False
            )
        for approval in approvals:
            principal = approval["principal"]
            session.add(
                CommunicationApprovalModel(
                    request_id=approval["request_id"],
                    principal_kind=principal["kind"],
                    principal_id=principal["principal_id"],
                    sequence=approval["sequence"],
                    status=approval["status"],
                    reason=approval.get("reason", ""),
                    created_at=approval["created_at"],
                    resolved_at=approval.get("resolved_at"),
                )
            )
        session.flush()
        for ballot in ballots:
            if ballot["request_id"] not in request_ids:
                continue
            principal = ballot["principal"]
            session.add(
                CommunicationBallotModel(
                    request_id=ballot["request_id"],
                    principal_kind=principal["kind"],
                    principal_id=principal["principal_id"],
                    voter_agent_id=ballot["voter_agent_id"],
                    approved=int(ballot["approved"]),
                    reason=ballot.get("reason", ""),
                    created_at=ballot["created_at"],
                )
            )

    @staticmethod
    def _write_communication_agreements(session: Any, agreements: Iterable[Dict[str, Any]]) -> None:
        for agreement in agreements:
            session.merge(
                CommunicationAgreementModel(
                    agreement_id=agreement["agreement_id"],
                    source_team_id=agreement["source_team_id"],
                    target_team_id=agreement["target_team_id"],
                    direction=agreement["direction"],
                    allowed_message_types=agreement["allowed_message_types"],
                    created_from_request_id=agreement["created_from_request_id"],
                    policy_snapshot=agreement["policy_snapshot"],
                    active=int(agreement["active"]),
                    created_at=agreement["created_at"],
                    revoked_at=agreement.get("revoked_at"),
                    revoked_by_team_id=agreement.get("revoked_by_team_id"),
                    revoke_reason=agreement.get("revoke_reason"),
                    superseded_by_agreement_id=agreement.get("superseded_by_agreement_id"),
                )
            )

    @staticmethod
    def _write_peer_messages(session: Any, messages: Iterable[Dict[str, Any]]) -> None:
        for message in messages:
            session.merge(
                PeerMessageModel(
                    message_id=message["message_id"],
                    sender_team_id=message["sender_team_id"],
                    recipient_team_id=message["recipient_team_id"],
                    initiated_by_agent_id=message.get("initiated_by_agent_id"),
                    agreement_id=message.get("agreement_id"),
                    content=message["content"],
                    delivery_state=message["delivery_state"],
                    created_at=message["created_at"],
                    consumed_at=message.get("consumed_at"),
                    invocation_id=message.get("invocation_id"),
                )
            )
