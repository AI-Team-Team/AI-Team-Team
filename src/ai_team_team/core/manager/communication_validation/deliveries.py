"""Peer delivery and AgentTeam inbox reference validation."""

from typing import Any, Dict, List

from ...communication import CommunicationApprovalStatus, CommunicationRequestStatus
from ...exceptions import StateRestoreError


def validate_deliveries_and_inboxes(
    messages: List[Any],
    approvals: List[Any],
    request_by_id: Dict[str, Any],
    agreement_by_id: Dict[str, Any],
    team_ids: set[str],
    agent_ids: set[str],
    inboxes: Dict[str, List[Dict[str, Any]]],
) -> None:
    invocation_ids = [message.invocation_id for message in messages if message.invocation_id]
    if len(invocation_ids) != len(set(invocation_ids)):
        raise StateRestoreError("Peer message invocation IDs are duplicated.")
    for message in messages:
        if message.sender_team_id not in team_ids or message.recipient_team_id not in team_ids:
            raise StateRestoreError("Peer message references a missing AgentTeam.")
        if message.sender_team_id == message.recipient_team_id:
            raise StateRestoreError("Peer message is self-addressed.")
        if message.initiated_by_agent_id not in agent_ids:
            raise StateRestoreError("Peer message references a missing initiating Agent.")
        if message.agreement_id is not None:
            agreement = agreement_by_id.get(message.agreement_id)
            if agreement is None:
                raise StateRestoreError("Peer message references a missing Agreement.")
            forward = (
                message.sender_team_id == agreement.source_team_id
                and message.recipient_team_id == agreement.target_team_id
            )
            reverse = (
                agreement.direction.value == "bidirectional"
                and message.sender_team_id == agreement.target_team_id
                and message.recipient_team_id == agreement.source_team_id
            )
            if not (forward or reverse):
                raise StateRestoreError("Peer message route is not covered by its Agreement.")
        if (message.delivery_state == "consumed") != (message.consumed_at is not None):
            raise StateRestoreError("Peer message has an invalid consumption timestamp.")

    approval_by_team_request = {
        (approval.principal.principal_id, approval.request_id): approval
        for approval in approvals
        if approval.principal.kind == "agent_team"
    }
    approval_notifications: Dict[tuple[str, str], int] = {}
    peer_notifications: Dict[str, List[str]] = {}
    for team_id, inbox in inboxes.items():
        if not isinstance(inbox, list):
            raise StateRestoreError(f"AgentTeam {team_id!r} has an invalid inbox.")
        for item in inbox:
            if not isinstance(item, dict):
                raise StateRestoreError(f"AgentTeam {team_id!r} has a malformed inbox item.")
            if item.get("type") == "communication_approval_request":
                request_id = item.get("request_id")
                key = (team_id, request_id)
                approval = approval_by_team_request.get(key)
                request = request_by_id.get(request_id)
                if (
                    approval is None
                    or request is None
                    or approval.status
                    not in {
                        CommunicationApprovalStatus.PENDING,
                        CommunicationApprovalStatus.PROCESSING,
                    }
                    or request.status
                    not in {
                        CommunicationRequestStatus.PENDING,
                        CommunicationRequestStatus.PROCESSING,
                    }
                ):
                    raise StateRestoreError(
                        "Communication approval inbox item has no active matching Approval."
                    )
                approval_notifications[key] = approval_notifications.get(key, 0) + 1
            elif item.get("type") == "peer_message":
                message_id = item.get("message_id")
                if not isinstance(message_id, str):
                    raise StateRestoreError("Peer inbox item lacks a durable message ID.")
                peer_notifications.setdefault(message_id, []).append(team_id)

    expected_approval_notifications = {
        (approval.principal.principal_id, approval.request_id)
        for approval in approvals
        if approval.principal.kind == "agent_team"
        and approval.status
        in {
            CommunicationApprovalStatus.PENDING,
            CommunicationApprovalStatus.PROCESSING,
        }
        and request_by_id[approval.request_id].status
        in {
            CommunicationRequestStatus.PENDING,
            CommunicationRequestStatus.PROCESSING,
        }
    }
    if set(approval_notifications) != expected_approval_notifications or any(
        count != 1 for count in approval_notifications.values()
    ):
        raise StateRestoreError(
            "Communication approval inbox notifications are incomplete or duplicated."
        )
    for message in messages:
        notification_teams = peer_notifications.pop(message.message_id, [])
        if message.delivery_state == "pending":
            if notification_teams != [message.recipient_team_id]:
                raise StateRestoreError(
                    "Pending peer delivery is missing or duplicated in the recipient inbox."
                )
        elif notification_teams:
            raise StateRestoreError("Consumed peer delivery remains in an AgentTeam inbox.")
    if peer_notifications:
        raise StateRestoreError("AgentTeam inbox references an unknown peer delivery.")
