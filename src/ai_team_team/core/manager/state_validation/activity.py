"""Validate personal recovery inputs without changing people or their files."""

from ai_team_team.core.exceptions import StateRestoreError

from ..activity.persisted_context import decode_last_context, restored_activity_scope


def validate_activity_contexts(payload, records):
    teams = {row["team_id"]: row for row in payload.teams}
    memberships = {
        (row.values["agent_id"], row.values["team_id"])
        for row in records
        if row.table_name == "membership_intervals"
    }
    for row in payload.agents:
        owner = row["agent_id"]
        context = decode_last_context(row.get("last_context"), owner)
        scope = restored_activity_scope(context, owner, records)
        if scope.kind != "agent_team":
            continue
        team = teams.get(scope.team_id)
        if team is None or team["team_kind"] != "ordinary":
            raise StateRestoreError(f"Agent {owner!r} activity scope references a missing ordinary team.")
        # A past scope is personal history, not renewed authority. Leaving a
        # team must not invalidate the person's checkpoint; live admission
        # separately requires current active membership.
        if owner not in team["members"] and (owner, scope.team_id) not in memberships:
            raise StateRestoreError(f"Agent {owner!r} activity scope has no membership evidence.")
