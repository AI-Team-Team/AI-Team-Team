"""Schema-6 communication governance state validation orchestration."""

from typing import Any, Dict, List, Tuple

from ...communication import (
    CommunicationAgreement,
    CommunicationApproval,
    CommunicationBallot,
    CommunicationRequest,
    PeerMessage,
)
from ...exceptions import StateRestoreError
from .agreements import validate_agreements
from .deliveries import validate_deliveries_and_inboxes
from .requests import validate_requests_and_approvals
from .successors import validate_successors_and_ballots


def _parse_communication_rows(
    request_rows: List[Dict[str, Any]],
    approval_rows: List[Dict[str, Any]],
    ballot_rows: List[Dict[str, Any]],
    agreement_rows: List[Dict[str, Any]],
    peer_message_rows: List[Dict[str, Any]],
) -> Tuple[List[Any], List[Any], List[Any], List[Any], List[Any]]:
    try:
        requests = [CommunicationRequest.model_validate(row) for row in request_rows]
        approvals = [CommunicationApproval.model_validate(row) for row in approval_rows]
        ballots = [CommunicationBallot.model_validate(row) for row in ballot_rows]
        agreements = [CommunicationAgreement.model_validate(row) for row in agreement_rows]
        messages = [PeerMessage.model_validate(row) for row in peer_message_rows]
    except Exception as exc:
        raise StateRestoreError(f"Invalid communication state payload: {exc}") from exc

    request_ids = [request.request_id for request in requests]
    if len(request_ids) != len(set(request_ids)):
        raise StateRestoreError("Communication request IDs are duplicated.")
    approval_keys = [approval.key for approval in approvals]
    if len(approval_keys) != len(set(approval_keys)):
        raise StateRestoreError("Communication approvals are duplicated.")
    agreement_ids = [agreement.agreement_id for agreement in agreements]
    if len(agreement_ids) != len(set(agreement_ids)):
        raise StateRestoreError("Communication agreement IDs are duplicated.")
    message_ids = [message.message_id for message in messages]
    if len(message_ids) != len(set(message_ids)):
        raise StateRestoreError("Peer message IDs are duplicated.")
    return requests, approvals, ballots, agreements, messages


class CommunicationValidationMixin:
    """Coordinates focused validators for persisted communication state."""

    def _validate_communication_state(
        self,
        request_rows: List[Dict[str, Any]],
        approval_rows: List[Dict[str, Any]],
        ballot_rows: List[Dict[str, Any]],
        agreement_rows: List[Dict[str, Any]],
        peer_message_rows: List[Dict[str, Any]],
        team_ids: set[str],
        agent_ids: set[str],
        root_agent_id: str,
        inboxes: Dict[str, List[Dict[str, Any]]],
    ) -> None:
        requests, approvals, ballots, agreements, messages = _parse_communication_rows(
            request_rows,
            approval_rows,
            ballot_rows,
            agreement_rows,
            peer_message_rows,
        )
        request_by_id = {request.request_id: request for request in requests}
        validate_requests_and_approvals(
            requests,
            approvals,
            request_by_id,
            team_ids,
            agent_ids,
            root_agent_id,
        )
        validate_successors_and_ballots(
            requests,
            ballots,
            approvals,
            request_by_id,
            agent_ids,
        )
        agreement_by_id = validate_agreements(
            requests,
            agreements,
            request_by_id,
            team_ids,
        )
        validate_deliveries_and_inboxes(
            messages,
            approvals,
            request_by_id,
            agreement_by_id,
            team_ids,
            agent_ids,
            inboxes,
        )
