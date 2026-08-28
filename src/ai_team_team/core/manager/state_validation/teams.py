"""Team, proposal, and topology validation for restored state."""

import json
from typing import Dict, Optional, Set

from ...exceptions import StateRestoreError
from .payload import StateValidationPayload


def validate_teams(
    payload: StateValidationPayload,
    agent_id_set: Set[str],
    active_agent_ids: Set[str],
) -> Set[str]:
    """Validate teams and return the complete team identifier set."""
    team_ids = [row.get("team_id") for row in payload.teams]
    if None in team_ids or len(team_ids) != len(set(team_ids)):
        raise StateRestoreError("Team identifiers are missing or duplicated.")
    team_id_set = set(team_ids)

    for row in payload.agents:
        messages = row.get("messages", [])
        if not isinstance(messages, list):
            raise StateRestoreError(f"Agent {row.get('agent_id')!r} has invalid message history.")
        for message in messages:
            if not isinstance(message, dict):
                raise StateRestoreError(f"Agent {row.get('agent_id')!r} has a malformed message.")
            message_team_id = message.get("team_id")
            if message_team_id is not None and message_team_id not in team_id_set:
                raise StateRestoreError(
                    f"Agent {row.get('agent_id')!r} message references "
                    f"missing team {message_team_id!r}."
                )

    parent_map: Dict[str, Optional[str]] = {}
    for row in payload.teams:
        team_id = row["team_id"]
        try:
            json.loads(row.get("status_map") or "{}")
        except Exception as exc:
            raise StateRestoreError(f"Team {team_id!r} contains invalid JSON metadata.") from exc
        missing_members = sorted(set(row.get("members", [])) - active_agent_ids)
        if missing_members:
            raise StateRestoreError(
                f"Team {team_id!r} references missing members: " + ", ".join(missing_members)
            )
        if len(row.get("members", [])) != len(set(row.get("members", []))):
            raise StateRestoreError(f"Team {team_id!r} contains duplicate members.")
        parent_id = row.get("parent_team_id")
        if parent_id is not None and parent_id not in team_id_set:
            raise StateRestoreError(f"Team {team_id!r} references missing parent {parent_id!r}.")
        parent_map[team_id] = parent_id
        _validate_team_creator(row, active_agent_ids, team_id_set)
        for proposal in row.get("proposals", []):
            _validate_proposal(proposal, team_id, agent_id_set)

    _validate_acyclic_topology(team_id_set, parent_map)
    return team_id_set


def _validate_team_creator(row: dict, active_agent_ids: Set[str], team_id_set: Set[str]) -> None:
    team_id = row["team_id"]
    creator_type = row.get("creator_type")
    creator_id = row.get("creator_id")
    if creator_type == "agent":
        valid_creator = creator_id in active_agent_ids
    elif creator_type == "team":
        valid_creator = creator_id in team_id_set and creator_id != team_id
    else:
        valid_creator = False
    if not valid_creator:
        raise StateRestoreError(
            f"Team {team_id!r} has invalid creator reference {creator_type!r}:{creator_id!r}."
        )


def _validate_proposal(proposal: dict, team_id: str, agent_id_set: Set[str]) -> None:
    proposal_id = proposal.get("proposal_id")
    if proposal.get("action") not in {"add", "remove"}:
        raise StateRestoreError(
            f"Proposal {proposal_id!r} has invalid action {proposal.get('action')!r}."
        )
    if proposal.get("status") not in {
        "active",
        "approved",
        "rejected",
        "retracted",
    }:
        raise StateRestoreError(
            f"Proposal {proposal_id!r} has invalid status {proposal.get('status')!r}."
        )
    if not isinstance(proposal.get("proposed_details", {}), dict):
        raise StateRestoreError(f"Proposal {proposal_id!r} has invalid details.")
    initiator_type = proposal.get("initiator_type")
    initiator_id = proposal.get("initiator_agent_id")
    initiator_name = proposal.get("initiator_name")
    if initiator_type not in {"individual", "AT"}:
        raise StateRestoreError(
            f"Proposal {proposal_id!r} has invalid initiator type {initiator_type!r}."
        )
    if initiator_type == "individual" and initiator_id not in agent_id_set:
        raise StateRestoreError(
            f"Proposal {proposal_id!r} references missing initiator agent {initiator_id!r}."
        )
    if initiator_type == "AT" and initiator_name not in {"AT", team_id}:
        raise StateRestoreError(
            f"Proposal {proposal_id!r} references invalid team initiator {initiator_name!r}."
        )
    votes = proposal.get("votes", {})
    if not isinstance(votes, dict):
        raise StateRestoreError(f"Proposal {proposal_id!r} has invalid votes.")
    unknown_voters = sorted(set(votes) - agent_id_set)
    if unknown_voters:
        raise StateRestoreError(
            f"Proposal {proposal_id!r} references missing voter IDs: " + ", ".join(unknown_voters)
        )
    for voter_id, ballot in votes.items():
        if (
            not isinstance(ballot, dict)
            or ballot.get("vote") not in {"Agree", "Disagree", "Abstain"}
            or not isinstance(ballot.get("public"), bool)
            or not isinstance(ballot.get("rationale", ""), str)
        ):
            raise StateRestoreError(
                f"Proposal {proposal_id!r} has an invalid ballot for voter {voter_id!r}."
            )


def _validate_acyclic_topology(team_id_set: Set[str], parent_map: Dict[str, Optional[str]]) -> None:
    for team_id in team_id_set:
        seen = set()
        current: Optional[str] = team_id
        while current is not None:
            if current in seen:
                raise StateRestoreError(f"Team topology contains a cycle at {current!r}.")
            seen.add(current)
            current = parent_map[current]
