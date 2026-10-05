"""Read governance records without hiding orphaned or conflicting references."""

from ai_team_team.core.exceptions import StateRestoreError
from ai_team_team.database.models import (
    GovernanceBallotModel,
    GovernanceRoundModel,
    MigrationRequestModel,
)


def read_governance_state(session):
    rounds = {}
    for row in session.query(GovernanceRoundModel):
        if (row.principal_team_id is None) == (row.principal_agent_id is None):
            raise StateRestoreError("A governance round must have exactly one principal.")
        identity = {
            "round_id": row.round_id,
            "principal": {
                "kind": "agent_team" if row.principal_team_id is not None else "agent",
                "principal_id": row.principal_team_id or row.principal_agent_id,
            },
        }
        if (
            not isinstance(row.data, dict)
            or any(row.data.get(key) != value for key, value in identity.items())
            or "ballots" in row.data
        ):
            raise StateRestoreError("A governance round's stored identity is inconsistent.")
        rounds[row.round_id] = {**row.data, "ballots": []}
    for ballot in session.query(GovernanceBallotModel).order_by(
        GovernanceBallotModel.created_at, GovernanceBallotModel.ballot_id
    ):
        if ballot.round_id not in rounds:
            raise StateRestoreError("An explicit governance ballot has no originating round.")
        rounds[ballot.round_id]["ballots"].append(
            {
                "ballot_id": ballot.ballot_id,
                "round_id": ballot.round_id,
                "voter_agent_id": ballot.voter_agent_id,
                "choice": ballot.choice,
                "created_at": ballot.created_at,
            }
        )
    migrations = []
    for row in session.query(MigrationRequestModel):
        identity = {
            "request_id": row.request_id,
            "team_id": row.team_id,
            "target_parent_id": row.target_parent_id,
            "original_parent_id": row.original_parent_id,
        }
        if not isinstance(row.data, dict) or any(
            row.data.get(key) != value for key, value in identity.items()
        ):
            raise StateRestoreError("A migration request's stored references are inconsistent.")
        migrations.append(dict(row.data))
    return list(rounds.values()), migrations
