"""Communication request and principal approval validation."""

from typing import Any, Dict, List

from ...communication import (
    CommunicationApprovalStatus,
    CommunicationRequestStatus,
    route_fingerprint,
)
from ...exceptions import StateRestoreError
from ...config import _parse_communication_config


def validate_requests_and_approvals(
    requests: List[Any],
    approvals: List[Any],
    request_by_id: Dict[str, Any],
    team_ids: set[str],
    agent_ids: set[str],
    root_agent_id: str,
) -> None:
    approvals_by_request: Dict[str, List[Any]] = {}
    for request in requests:
        if request.sender_team_id not in team_ids or request.recipient_team_id not in team_ids:
            raise StateRestoreError(
                f"Communication request {request.request_id!r} references a missing AgentTeam."
            )
        if request.sender_team_id == request.recipient_team_id:
            raise StateRestoreError(
                f"Communication request {request.request_id!r} is self-addressed."
            )
        if request.initiated_by_agent_id not in agent_ids:
            raise StateRestoreError(
                f"Communication request {request.request_id!r} references a missing initiator Agent."
            )
        try:
            policy = _parse_communication_config(request.policy_snapshot)
        except Exception as exc:
            raise StateRestoreError(
                f"Communication request {request.request_id!r} has an "
                f"invalid policy snapshot: {exc}"
            ) from exc
        if policy.policy == "permissive":
            raise StateRestoreError(
                f"Communication request {request.request_id!r} cannot use the permissive policy."
            )
        if request.direction.value != policy.direction:
            raise StateRestoreError(
                f"Communication request {request.request_id!r} direction "
                "does not match its policy snapshot."
            )
        principal_keys = [principal.key for principal in request.approval_principals]
        if not principal_keys or len(principal_keys) != len(set(principal_keys)):
            raise StateRestoreError(
                f"Communication request {request.request_id!r} has an "
                "empty or duplicated approval route."
            )
        if route_fingerprint(request.approval_principals) != request.route_fingerprint:
            raise StateRestoreError(
                f"Communication request {request.request_id!r} has an invalid route fingerprint."
            )
        for principal in request.approval_principals:
            if principal.kind == "agent_team" and principal.principal_id not in team_ids:
                raise StateRestoreError(
                    f"Communication request {request.request_id!r} references a missing approval AgentTeam."
                )
            if principal.kind == "agent" and principal.principal_id != root_agent_id:
                raise StateRestoreError(
                    f"Communication request {request.request_id!r} references an unauthorized approval Agent."
                )

    for approval in approvals:
        request = request_by_id.get(approval.request_id)
        if request is None or approval.principal not in request.approval_principals:
            raise StateRestoreError(
                f"Communication approval {approval.key!r} has no matching request principal."
            )
        approvals_by_request.setdefault(approval.request_id, []).append(approval)
    for request in requests:
        request_approvals = sorted(
            approvals_by_request.get(request.request_id, []),
            key=lambda item: item.sequence,
        )
        if len(request_approvals) != len(request.approval_principals):
            raise StateRestoreError(
                f"Communication request {request.request_id!r} has incomplete approvals."
            )
        if [item.sequence for item in request_approvals] != list(
            range(len(request.approval_principals))
        ) or any(
            approval.principal != request.approval_principals[index]
            for index, approval in enumerate(request_approvals)
        ):
            raise StateRestoreError(
                f"Communication request {request.request_id!r} has an invalid approval order."
            )
        statuses = {approval.status for approval in request_approvals}
        if request.status in {
            CommunicationRequestStatus.APPROVED,
            CommunicationRequestStatus.STALE,
        } and statuses != {CommunicationApprovalStatus.APPROVED}:
            raise StateRestoreError(
                f"Terminal communication request {request.request_id!r} "
                "lacks unanimous principal approval."
            )
        if request.status is CommunicationRequestStatus.DENIED and (
            CommunicationApprovalStatus.DENIED not in statuses
            or statuses
            & {
                CommunicationApprovalStatus.PENDING,
                CommunicationApprovalStatus.PROCESSING,
            }
        ):
            raise StateRestoreError(
                f"Denied communication request {request.request_id!r} has "
                "an invalid approval state."
            )
        if request.status in {
            CommunicationRequestStatus.PENDING,
            CommunicationRequestStatus.PROCESSING,
        } and statuses & {
            CommunicationApprovalStatus.DENIED,
            CommunicationApprovalStatus.CANCELLED,
        }:
            raise StateRestoreError(
                f"Pending communication request {request.request_id!r} "
                "contains a terminal approval."
            )
        if (
            request.status is CommunicationRequestStatus.PENDING
            and CommunicationApprovalStatus.PROCESSING in statuses
        ):
            raise StateRestoreError(
                f"Pending communication request {request.request_id!r} "
                "contains a processing approval."
            )
        if request.status is CommunicationRequestStatus.PENDING and statuses == {
            CommunicationApprovalStatus.APPROVED
        }:
            raise StateRestoreError(
                f"Pending communication request {request.request_id!r} "
                "already has unanimous approval."
            )
        if (
            request.status is CommunicationRequestStatus.PROCESSING
            and CommunicationApprovalStatus.PROCESSING not in statuses
        ):
            raise StateRestoreError(
                f"Processing communication request {request.request_id!r} "
                "has no processing approval."
            )
        terminal = request.status in {
            CommunicationRequestStatus.APPROVED,
            CommunicationRequestStatus.DENIED,
            CommunicationRequestStatus.STALE,
        }
        if terminal != (request.resolved_at is not None):
            raise StateRestoreError(
                f"Communication request {request.request_id!r} has an invalid resolution timestamp."
            )
        for approval in request_approvals:
            approval_terminal = approval.status in {
                CommunicationApprovalStatus.APPROVED,
                CommunicationApprovalStatus.DENIED,
                CommunicationApprovalStatus.CANCELLED,
            }
            if approval_terminal != (approval.resolved_at is not None):
                raise StateRestoreError(
                    f"Communication approval {approval.key!r} has an invalid resolution timestamp."
                )
