"""Communication successor-chain and ballot validation."""

from typing import Any, Dict, List

from ...communication import CommunicationRequestStatus
from ...exceptions import StateRestoreError


def validate_successors_and_ballots(
    requests: List[Any],
    ballots: List[Any],
    approvals: List[Any],
    request_by_id: Dict[str, Any],
    agent_ids: set[str],
) -> None:
    for request in requests:
        successor_id = request.superseded_by_request_id
        predecessor_id = request.supersedes_request_id
        if request.status is CommunicationRequestStatus.STALE:
            if successor_id is None:
                raise StateRestoreError(
                    f"Stale communication request {request.request_id!r} has no successor."
                )
        elif successor_id is not None:
            raise StateRestoreError(
                f"Non-stale communication request {request.request_id!r} references a successor."
            )
        if successor_id is not None:
            successor = request_by_id.get(successor_id)
            if successor is None or successor.supersedes_request_id != request.request_id:
                raise StateRestoreError(
                    f"Communication request {request.request_id!r} has an "
                    "invalid successor reference."
                )
        if predecessor_id is not None:
            predecessor = request_by_id.get(predecessor_id)
            if predecessor is None or predecessor.superseded_by_request_id != request.request_id:
                raise StateRestoreError(
                    f"Communication request {request.request_id!r} has an "
                    "invalid predecessor reference."
                )
        seen = set()
        current = request
        while current.superseded_by_request_id is not None:
            if current.request_id in seen:
                raise StateRestoreError("Communication request successor chain contains a cycle.")
            seen.add(current.request_id)
            successor = request_by_id.get(current.superseded_by_request_id)
            if successor is None:
                raise StateRestoreError(
                    f"Communication request {current.request_id!r} references a missing successor."
                )
            current = successor

    ballot_keys = [
        (
            ballot.request_id,
            ballot.principal.key,
            ballot.voter_agent_id,
        )
        for ballot in ballots
    ]
    if len(ballot_keys) != len(set(ballot_keys)):
        raise StateRestoreError("Communication ballots are duplicated.")
    for ballot in ballots:
        if ballot.request_id not in request_by_id or ballot.voter_agent_id not in agent_ids:
            raise StateRestoreError("Communication ballot has a missing reference.")
        if ballot.principal.kind != "agent_team":
            raise StateRestoreError("Only an AgentTeam approval may contain member ballots.")
        if not any(
            approval.request_id == ballot.request_id and approval.principal == ballot.principal
            for approval in approvals
        ):
            raise StateRestoreError("Communication ballot has no matching approval.")
