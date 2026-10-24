"""Read governance records without hiding orphaned or conflicting references."""

from ai_team_team.core.exceptions import StateRestoreError
from ai_team_team.database.models import (
    GovernanceBallotModel,
    GovernanceElectorateModel,
    GovernanceCaseModel,
    MigrationRequestModel,
)
from ai_team_team.database.persistence.governance_schema import choice_schema
from jsonschema import Draft202012Validator


def read_governance_state(session):
    cases = {}
    for row in session.query(GovernanceCaseModel):
        if (row.principal_team_id is None) == (row.principal_agent_id is None):
            raise StateRestoreError("A governance case must have exactly one principal.")
        identity = {
            "case_id": row.case_id,
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
            raise StateRestoreError("A governance case's stored identity is inconsistent.")
        electorate = session.query(GovernanceElectorateModel).filter_by(case_id=row.case_id).order_by(GovernanceElectorateModel.position).all()
        if (row.electorate_revision != row.data.get("electorate_revision")
                or [voter.position for voter in electorate] != list(range(len(electorate)))
                or [voter.voter_agent_id for voter in electorate] != row.data.get("voter_agent_ids")
                or any(voter.created_version < 1 or voter.membership_interval_id != row.data.get("electorate_bindings", {}).get(voter.voter_agent_id)
                    or voter.eligibility != ({"membership_interval_id": voter.membership_interval_id}
                        if voter.membership_interval_id else {"agent_id": voter.voter_agent_id}) for voter in electorate)
                or row.choice_schema != choice_schema(row.data.get("choice_kind"), row.data.get("candidates", []))):
            raise StateRestoreError("A governance case's frozen electorate or choice schema is inconsistent.")
        cases[row.case_id] = {**row.data, "ballots": []}
    for ballot in session.query(GovernanceBallotModel).order_by(
        GovernanceBallotModel.created_at, GovernanceBallotModel.ballot_id
    ):
        if ballot.case_id not in cases:
            raise StateRestoreError("An explicit governance ballot has no originating case.")
        source = cases[ballot.case_id]
        schema = choice_schema(source["choice_kind"], source["candidates"])
        if ballot.created_version < 1 or not Draft202012Validator(schema).is_valid(ballot.choice):
            raise StateRestoreError("An explicit ballot violates its immutable choice schema.")
        cases[ballot.case_id]["ballots"].append(
            {
                "ballot_id": ballot.ballot_id,
                "case_id": ballot.case_id,
                "voter_agent_id": ballot.voter_agent_id,
                "choice": ballot.choice,
                "created_at": ballot.created_at,
            }
        )
    migrations = []
    for row in session.query(MigrationRequestModel):
        if not isinstance(row.data, dict):
            raise StateRestoreError("A migration request must contain structured evidence.")
        identity = {
            "request_id": row.request_id,
            "team_id": row.team_id,
            "target_parent_id": row.target_parent_id,
            "original_parent_id": row.original_parent_id,
        }
        for key in ("target_parent_agent_id", "original_parent_agent_id", "acceptance_id", "detachment_kind"):
            if getattr(row, key) is not None or key in row.data:
                identity[key] = getattr(row, key)
        if row.state_version < 1 or not isinstance(row.path_evidence, dict) or row.path_evidence != row.data.get("path_evidence", {}):
            raise StateRestoreError("A migration request's path evidence is inconsistent.")
        if not isinstance(row.data, dict) or any(
            row.data.get(key) != value for key, value in identity.items()
        ):
            raise StateRestoreError("A migration request's stored references are inconsistent.")
        migrations.append(dict(row.data))
    return list(cases.values()), migrations
