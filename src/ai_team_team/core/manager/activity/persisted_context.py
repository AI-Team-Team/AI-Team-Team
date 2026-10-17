"""Shared decoding of personal checkpoint metadata before restore publication."""

import json

from pydantic import TypeAdapter, ValidationError

from ai_team_team.core.activity.contracts import OperationScope, PersonalScope
from ai_team_team.core.exceptions import StateRestoreError


def decode_last_context(raw, agent_id):
    if raw is None:
        return None
    try:
        context = json.loads(raw)
    except (ValueError, TypeError) as error:
        raise StateRestoreError(f"Agent {agent_id!r} has invalid last_context JSON.") from error
    if not isinstance(context, dict):
        raise StateRestoreError(f"Agent {agent_id!r} last_context must be an object.")
    return context


def restored_activity_scope(context, agent_id, records):
    """Use the explicit checkpoint, falling back only when its scope is absent."""
    if context is not None and "activity_scope" in context:
        requested = context["activity_scope"]
    else:
        invocations = [
            row.values
            for row in records
            if row.table_name == "activity_invocations" and row.values["agent_id"] == agent_id
        ]
        if not invocations:
            return PersonalScope()
        latest = max(invocations, key=lambda row: (row["context_version"], row["started_at"]))
        requested = {"kind": latest["scope_kind"]}
        if latest["scope_kind"] == "agent_team":
            requested["team_id"] = latest["scope_team_id"]
    try:
        return TypeAdapter(OperationScope).validate_python(requested)
    except ValidationError as error:
        raise StateRestoreError(f"Agent {agent_id!r} has an invalid persisted activity scope.") from error
