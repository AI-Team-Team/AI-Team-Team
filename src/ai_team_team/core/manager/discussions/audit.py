"""Content and operational auditing for completed discussion rounds."""

import json
from typing import Any, Iterable, Tuple

from ...response import (
    AgentTurnStatus,
    AuditResult,
    AuditStatus,
    OperationalStatus,
)


async def audit_discussion(
    manager: Any,
    team: Any,
    transcript: str,
    structured_rounds: Iterable[Any],
    skip_audit: bool,
) -> Tuple[AuditResult, bool]:
    """Audit discussion content and derive its structured operational status."""
    incomplete_metadata = [
        {
            "agent_id": turn.agent_id,
            "round_number": turn.round_number,
            "error_kind": turn.error_kind,
            "reason": turn.reason,
            "tool_failures": [failure.model_dump(mode="json") for failure in turn.tool_failures],
        }
        for round_result in structured_rounds
        for turn in round_result.turns
        if turn.status is AgentTurnStatus.INCOMPLETE
    ]
    had_member_errors = bool(incomplete_metadata)
    operational_status = (
        OperationalStatus.DEGRADED if had_member_errors else OperationalStatus.HEALTHY
    )
    operational_reason = (
        "One or more Agent turns were incomplete: "
        + json.dumps(incomplete_metadata, sort_keys=True)
        if incomplete_metadata
        else "All member turns completed."
    )
    if skip_audit:
        return (
            AuditResult(
                status=AuditStatus.HEALTHY,
                reason="Audit skipped.",
                operational_status=operational_status,
                operational_reason=operational_reason,
            ),
            had_member_errors,
        )

    audit_transcript = transcript
    if incomplete_metadata:
        audit_transcript += "\n\n[ATT OPERATIONAL METADATA]\n" + json.dumps(
            incomplete_metadata, sort_keys=True
        )
    audit_result = await manager.supervisor.audit_team_dialog(
        team,
        audit_transcript,
        operational_status=operational_status,
        operational_reason=operational_reason,
    )
    if audit_result.status is AuditStatus.UNHEALTHY:
        await manager.supervisor.report_anomaly(team, audit_result.reason, manager)
    elif audit_result.status is AuditStatus.UNKNOWN:
        manager._emit_callback(
            "on_system_event",
            "audit_unknown",
            {
                "team_id": team.team_id,
                "reason": audit_result.reason,
                "cause": audit_result.cause,
            },
        )
        await manager.supervisor.report_unknown(team, audit_result, manager)
    if audit_result.operational_status is OperationalStatus.DEGRADED:
        await manager._report_operational_degraded(team, audit_result)
    return audit_result, had_member_errors
