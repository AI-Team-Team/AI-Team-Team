"""Incremental governance records with append-only ballot enforcement."""

from ai_team_team.core.exceptions import StatePersistenceError
from ai_team_team.database.models import (
    GovernanceBallotModel,
    GovernanceRoundModel,
    MigrationRequestModel,
)


class GovernanceWriteMixin:
    @staticmethod
    def _write_governance(session, rounds, migrations):
        for item in migrations:
            session.merge(
                MigrationRequestModel(
                    request_id=item["request_id"],
                    team_id=item["team_id"],
                    target_parent_id=item["target_parent_id"],
                    original_parent_id=item["original_parent_id"],
                    data=dict(item),
                )
            )
        for item in rounds:
            data = {key: value for key, value in item.items() if key != "ballots"}
            principal = item["principal"]
            current = session.get(GovernanceRoundModel, item["round_id"])
            if current is not None:
                immutable = set(data) - {"status", "reason", "resolved_at"}
                if any(current.data[key] != data[key] for key in immutable):
                    raise StatePersistenceError(
                        "A governance round's identity or electorate cannot be rewritten."
                    )
            session.merge(
                GovernanceRoundModel(
                    round_id=item["round_id"],
                    principal_team_id=principal["principal_id"]
                    if principal["kind"] == "agent_team"
                    else None,
                    principal_agent_id=principal["principal_id"]
                    if principal["kind"] == "agent"
                    else None,
                    data=data,
                )
            )
            session.flush()
            for ballot in item["ballots"]:
                existing = (
                    session.query(GovernanceBallotModel)
                    .filter_by(round_id=item["round_id"], voter_agent_id=ballot["voter_agent_id"])
                    .one_or_none()
                )
                if existing is not None:
                    if (
                        existing.ballot_id != ballot["ballot_id"]
                        or existing.choice != ballot["choice"]
                        or existing.created_at != ballot["created_at"]
                    ):
                        raise StatePersistenceError(
                            "An accepted governance ballot cannot be rewritten."
                        )
                    continue
                session.add(GovernanceBallotModel(**ballot))
