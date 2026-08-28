"""Communication agreement and active-route validation."""

from typing import Any, Dict, List

from ...communication import CommunicationRequestStatus
from ...exceptions import StateRestoreError


def validate_agreements(
    requests: List[Any],
    agreements: List[Any],
    request_by_id: Dict[str, Any],
    team_ids: set[str],
) -> Dict[str, Any]:
    agreement_by_id = {item.agreement_id: item for item in agreements}
    agreements_by_request: Dict[str, List[Any]] = {}
    for agreement in agreements:
        if agreement.source_team_id not in team_ids or agreement.target_team_id not in team_ids:
            raise StateRestoreError("Communication agreement references a missing AgentTeam.")
        request = request_by_id.get(agreement.created_from_request_id)
        if request is None or request.status is not CommunicationRequestStatus.APPROVED:
            raise StateRestoreError("Communication agreement has no approved source request.")
        agreements_by_request.setdefault(request.request_id, []).append(agreement)
        if (
            agreement.source_team_id != request.sender_team_id
            or agreement.target_team_id != request.recipient_team_id
            or agreement.direction is not request.direction
            or agreement.policy_snapshot != request.policy_snapshot
            or agreement.allowed_message_types != ["peer_message"]
        ):
            raise StateRestoreError("Communication agreement does not match its source request.")
        if agreement.revoked_by_team_id is not None and agreement.revoked_by_team_id not in {
            agreement.source_team_id,
            agreement.target_team_id,
        }:
            raise StateRestoreError(
                "Communication agreement was revoked by a non-endpoint AgentTeam."
            )
        if (
            agreement.superseded_by_agreement_id is not None
            and agreement.superseded_by_agreement_id not in agreement_by_id
        ):
            raise StateRestoreError("Communication agreement references a missing successor.")
        if agreement.active and (
            agreement.revoked_at is not None
            or agreement.revoked_by_team_id is not None
            or agreement.revoke_reason is not None
            or agreement.superseded_by_agreement_id is not None
        ):
            raise StateRestoreError("Active communication agreement contains revocation metadata.")
        if not agreement.active and agreement.revoked_at is None:
            raise StateRestoreError(
                "Inactive communication agreement lacks a revocation timestamp."
            )

    for request in requests:
        source_agreements = agreements_by_request.get(request.request_id, [])
        if request.status is CommunicationRequestStatus.APPROVED:
            if len(source_agreements) != 1:
                raise StateRestoreError(
                    f"Approved communication request {request.request_id!r} "
                    "must create exactly one agreement."
                )
        elif source_agreements:
            raise StateRestoreError(
                f"Non-approved communication request {request.request_id!r} created an agreement."
            )

    active_routes = set()
    for agreement in agreements:
        if not agreement.active:
            continue
        routes = {(agreement.source_team_id, agreement.target_team_id)}
        if agreement.direction.value == "bidirectional":
            routes.add((agreement.target_team_id, agreement.source_team_id))
        if active_routes & routes:
            raise StateRestoreError("Duplicate active communication route.")
        active_routes.update(routes)
    return agreement_by_id
