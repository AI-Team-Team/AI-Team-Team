"""Observer reporting for discussion results."""

from typing import Any


def emit_discussion_log(
    manager: Any,
    team: Any,
    prompt: str,
    rounds: int,
    transcript: str,
    audit_result: Any,
) -> None:
    """Queue the optional synthesized-transcript callback."""
    if not manager.on_log_append:
        return
    log_title = (
        f"Synthesized Debate Transcript | {team.team_id} ({team.preset_name}) - Rounds: {rounds}"
    )
    log_content = (
        f"TEAM_ID: {team.team_id}\n"
        f"PRESET_NAME: {team.preset_name}\n"
        f"PURPOSE: {team.team_purpose}\n"
        f"PROMPT: {prompt}\n"
        "--- SYNTHESIZED TRANSCRIPT BEGIN ---\n"
        f"{transcript}\n"
        "--- SYNTHESIZED TRANSCRIPT END ---\n"
        f"AUDIT STATUS: {audit_result.status.value}\n"
        f"AUDIT REASON: {audit_result.reason}\n"
        f"OPERATIONAL STATUS: {audit_result.operational_status.value}\n"
        f"OPERATIONAL REASON: {audit_result.operational_reason}\n"
    )
    manager._emit_callback(
        "on_log_append",
        team.team_id,
        log_title,
        log_content,
        team.chapter_num,
    )
