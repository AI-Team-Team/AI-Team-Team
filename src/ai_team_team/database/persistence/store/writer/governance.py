"""Incremental governance records with append-only ballot enforcement."""

from ai_team_team.core.exceptions import StatePersistenceError
from ai_team_team.database.persistence.governance_schema import choice_schema
from ai_team_team.database.models import (
    GovernanceBallotModel,
    CommunicationApprovalModel,
    GovernanceElectorateModel,
    GovernanceCaseModel,
    MigrationRequestModel,
)


class GovernanceWriteMixin:
    @staticmethod
    def _write_governance(session, cases, migrations, state_version=1):
        for item in migrations:
            session.merge(
                MigrationRequestModel(
                    request_id=item["request_id"],
                    team_id=item["team_id"],
                    target_parent_id=item["target_parent_id"],
                    original_parent_id=item["original_parent_id"],
                    target_parent_agent_id=item.get("target_parent_agent_id"),
                    original_parent_agent_id=item.get("original_parent_agent_id"),
                    acceptance_id=item.get("acceptance_id"),
                    detachment_kind=item.get("detachment_kind"),
                    path_evidence=item.get("path_evidence", {}),
                    state_version=max(1, state_version),
                    data=dict(item),
                )
            )
        for item in cases:
            data = {key: value for key, value in item.items() if key != "ballots"}
            principal = item["principal"]
            current = session.get(GovernanceCaseModel, item["case_id"])
            if current is not None:
                immutable = set(data) - {"status", "reason", "resolved_at"}
                if any(current.data[key] != data[key] for key in immutable):
                    raise StatePersistenceError(
                        "A governance case's identity or electorate cannot be rewritten."
                    )
            session.merge(
                GovernanceCaseModel(
                    case_id=item["case_id"],
                    principal_team_id=principal["principal_id"]
                    if principal["kind"] == "agent_team"
                    else None,
                    principal_agent_id=principal["principal_id"]
                    if principal["kind"] == "agent"
                    else None,
                    data=data,
                    electorate_revision=item["electorate_revision"],
                    choice_schema=choice_schema(item["choice_kind"], item["candidates"]),
                    state_version=max(1, state_version),
                )
            )
            session.flush()
            for position, voter in enumerate(item["voter_agent_ids"]):
                if session.get(GovernanceElectorateModel, (item["case_id"], voter)) is None:
                    binding = item["electorate_bindings"].get(voter)
                    session.add(GovernanceElectorateModel(case_id=item["case_id"], voter_agent_id=voter,
                        membership_interval_id=binding, position=position,
                        eligibility={"membership_interval_id": binding} if binding else {"agent_id": voter},
                        created_version=max(1, state_version)))
            session.flush()
            for ballot in item["ballots"]:
                existing = (
                    session.query(GovernanceBallotModel)
                    .filter_by(case_id=item["case_id"], voter_agent_id=ballot["voter_agent_id"])
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
