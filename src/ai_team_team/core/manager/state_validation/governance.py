"""Fail-closed references, explicit ballots, cases, and personal email validation."""

import math
from collections import Counter, defaultdict

from ...exceptions import StateRestoreError
from ...governance import (
    BooleanGovernanceChoice,
    GovernanceCase,
    MigrationRequest,
    ModelGovernanceChoice,
)
from ..governance.submissions import GovernanceSubmissionMixin


def validate_governance(payload, agent_ids, team_ids, root_id):
    try:
        cases = [
            GovernanceCase.model_validate(row, strict=True) for row in payload.governance_cases
        ]
        migrations = [
            MigrationRequest.model_validate(row, strict=True) for row in payload.migration_requests
        ]
        if len({item.case_id for item in cases}) != len(cases) or len(
            {item.request_id for item in migrations}
        ) != len(migrations):
            raise ValueError("Governance identifiers are duplicated.")
        migration_map = {item.request_id: item for item in migrations}
        communication_map = {item["request_id"]: item for item in payload.communication_requests}
        case_map = {item.case_id: item for item in cases}
        for item in migrations:
            from ...organization import validate_migration_evidence
            validate_migration_evidence(item, agent_ids, team_ids)
            if (
                item.team_id not in team_ids
                or item.target_parent_id is not None and item.target_parent_id not in team_ids
                or item.target_parent_agent_id is not None and item.target_parent_agent_id not in agent_ids
                or item.original_parent_agent_id is not None and item.original_parent_agent_id not in agent_ids
                or item.target_parent_agent_id is not None and item.target_parent_id is not None
                or item.original_parent_agent_id is not None and item.original_parent_id is not None
                or item.team_id == item.target_parent_id
                or item.original_parent_id is not None
                and item.original_parent_id not in team_ids
            ):
                raise ValueError("A migration request has missing or invalid AgentTeam references.")
            if len({principal.key for principal in item.principals}) != len(item.principals):
                raise ValueError("Migration principals are duplicated.")
            for principal in item.principals:
                _principal(principal, team_ids, agent_ids)
            if item.operation in {"voluntary_detachment", "parent_loss"}:
                if item.target_parent_id or item.target_parent_agent_id or item.principals:
                    raise ValueError("Detachment cannot retain a proposed parent or approval requirement.")
            elif not item.target_parent_id and not item.target_parent_agent_id:
                raise ValueError("An attachment or migration requires an explicit target.")
            elif not any(principal.principal_id == (item.target_parent_id or item.target_parent_agent_id)
                    and principal.kind == ("agent_team" if item.target_parent_id else "agent") for principal in item.principals):
                raise ValueError("The prospective parent must explicitly accept its child.")
            if (item.status == "PENDING") != (item.resolved_at is None):
                raise ValueError("A migration resolution timestamp is inconsistent.")
        ballot_ids = set()
        sequences = defaultdict(list)
        for item in cases:
            _principal(item.principal, team_ids, agent_ids)
            sequences[(item.business_kind, item.business_id, item.principal.key)].append(
                item.electorate_revision
            )
            if (
                len(set(item.voter_agent_ids)) != len(item.voter_agent_ids)
                or set(item.voter_agent_ids) - agent_ids
            ):
                raise ValueError(
                    "A governance electorate is duplicated or references missing Agents."
                )
            if item.principal.kind == "agent" and item.voter_agent_ids != [item.principal.principal_id]:
                raise ValueError("An Agent principal must vote using its own exact identity.")
            if (item.principal.kind == "agent_team" and set(item.electorate_bindings) != set(item.voter_agent_ids)
                    or item.principal.kind == "agent" and item.electorate_bindings):
                raise ValueError("A case's electorate bindings disagree with its designated principal.")
            expected = "model" if item.business_kind == "failover" else "boolean"
            if item.choice_kind != expected:
                raise ValueError("The choice schema disagrees with the governance purpose.")
            if item.business_kind == "communication":
                request = communication_map.get(item.business_id)
                if (
                    request is None
                    or item.principal.model_dump(mode="json") not in request["approval_principals"]
                ):
                    raise ValueError(
                        "A communication case has no designated originating authority."
                    )
            elif item.business_kind == "migration":
                request = migration_map.get(item.business_id)
                if request is None or item.principal not in request.principals:
                    raise ValueError("A migration case has no designated originating authority.")
            elif (
                not item.business_id.startswith("FAILOVER-")
                or item.expires_at is None
                or not math.isfinite(item.expires_at)
                or item.expires_at <= item.created_at
            ):
                raise ValueError(
                    "A failover case lacks its bounded execution identity or deadline."
                )
            if expected == "model":
                if not item.candidates or len(set(item.candidates)) != len(item.candidates):
                    raise ValueError("Model-selection candidates are missing or duplicated.")
            elif item.candidates or item.expires_at is not None:
                raise ValueError(
                    "Boolean approvals cannot contain failover candidates or deadlines."
                )
            voter_ids = [ballot.voter_agent_id for ballot in item.ballots]
            if len(set(voter_ids)) != len(voter_ids) or set(voter_ids) - set(item.voter_agent_ids):
                raise ValueError("A case contains duplicate or ineligible ballots.")
            for ballot in item.ballots:
                if ballot.case_id != item.case_id or ballot.ballot_id in ballot_ids:
                    raise ValueError(
                        "A ballot references the wrong case or duplicates another ballot."
                    )
                ballot_ids.add(ballot.ballot_id)
                choice_model = (
                    BooleanGovernanceChoice if expected == "boolean" else ModelGovernanceChoice
                )
                choice_model.model_validate(ballot.choice, strict=True)
                if expected == "model" and ballot.choice["model_alias"] not in item.candidates:
                    raise ValueError("A model ballot selects an ineligible alias.")
            if (item.status == "PENDING") != (item.resolved_at is None):
                raise ValueError("A case's resolution timestamp is inconsistent.")
            if (
                item.status in {"APPROVED", "DENIED", "TIED"}
                or item.status == "PENDING"
                and len(item.ballots) == len(item.voter_agent_ids)
            ):
                if len(item.ballots) != len(item.voter_agent_ids):
                    raise ValueError(
                        "A decision was formed without every required explicit ballot."
                    )
                check = item.model_copy(deep=True)
                GovernanceSubmissionMixin.tally(check)
                if check.status != item.status:
                    raise ValueError("A stored decision disagrees with its complete tally.")
        if any(
            sorted(numbers) != list(range(1, len(numbers) + 1)) for numbers in sequences.values()
        ):
            raise ValueError("Governance case numbers are duplicated or discontinuous.")
        _validate_authoritative_outcomes(payload, cases, migrations)
        mail_counts = Counter()
        for agent_id, messages in payload.agent_inboxes.items():
            for message in messages:
                if message["message_type"] != "governance_choice_request":
                    continue
                data = message["payload"]
                item = case_map.get(data.get("case_id"))
                if (
                    item is None
                    or agent_id not in item.voter_agent_ids
                    or data
                    != {
                        "case_id": item.case_id,
                        "request_id": item.business_id,
                        "electorate_revision": item.electorate_revision,
                        "business_kind": item.business_kind,
                        "principal": item.principal.model_dump(mode="json"),
                    }
                ):
                    raise ValueError(
                        "A personal governance email has invalid ownership or case references."
                    )
                mail_counts[(item.case_id, agent_id)] += 1
        if mail_counts != Counter(
            {(item.case_id, voter_id): 1 for item in cases for voter_id in item.voter_agent_ids}
        ):
            raise ValueError("Personal governance emails are missing or duplicated.")
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise StateRestoreError(f"Invalid personal governance state: {exc}") from exc


def _principal(principal, team_ids, agent_ids):
    if (
        principal.kind == "agent_team"
        and principal.principal_id not in team_ids
        or principal.kind == "agent"
        and principal.principal_id not in agent_ids
    ):
        raise ValueError("An explicitly designated governance principal is missing.")


def _validate_authoritative_outcomes(payload, cases, migrations):
    case_map = {item.case_id: item for item in cases}
    latest = {}
    for item in cases:
        key = (item.business_kind, item.business_id, item.principal.key)
        previous = latest.get(key)
        if previous is None or item.electorate_revision > previous.electorate_revision:
            latest[key] = item
    for approval in payload.communication_approvals:
        if approval["status"] not in {"APPROVED", "DENIED"}:
            continue
        principal = approval["principal"]
        key = f"{principal['kind']}:{principal['principal_id']}"
        item = case_map.get(approval.get("case_id"))
        if (item is None or item.status != approval["status"] or item.business_kind != "communication"
                or item.business_id != approval["request_id"] or item.principal.key != key):
            raise ValueError("A communication decision lacks its matching explicit voting case.")
        projected = {
            (ballot["voter_agent_id"], ballot["approved"], ballot["reason"], ballot["created_at"])
            for ballot in payload.communication_ballots
            if ballot["request_id"] == approval["request_id"] and ballot["principal"] == principal
        }
        expected = (
            {
                (
                    ballot.voter_agent_id,
                    ballot.choice["approved"],
                    ballot.choice["reason"],
                    ballot.created_at,
                )
                for ballot in item.ballots
            }
            if item.principal.kind == "agent_team"
            else set()
        )
        if projected != expected:
            raise ValueError("Communication ballot projections disagree with the accepted choices.")
    for request in migrations:
        if not request.principals or request.status not in {"EXECUTED", "DENIED"}:
            continue
        decisions = [
            latest.get(("migration", request.request_id, principal.key))
            for principal in request.principals
        ]
        if request.status == "EXECUTED" and not all(
            item is not None and item.status == "APPROVED" for item in decisions
        ):
            raise ValueError("Executed migration lacks a complete set of explicit approvals.")
        if request.status == "DENIED" and not any(
            item is not None and item.status == "DENIED" for item in decisions
        ):
            raise ValueError("Denied migration lacks an explicit designated denial.")
