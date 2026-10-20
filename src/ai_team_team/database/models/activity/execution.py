"""Execution facts, protected payloads, observations, and independent controls."""

from sqlalchemy import UniqueConstraint

from .columns import SCOPE_CHECK, boolean, choice, document, identifier, integer, reference, scope, table, timestamp


executions = table("executions",
    identifier("execution_id", primary=True), reference("agent_id", "agents.agent_id"),
    reference("invocation_id", "activity_invocations.invocation_id", nullable=True), *scope(), identifier("tool_name"), document("effects"),
    integer("runtime_generation"), choice("visibility", "foreground explicit_background detached"),
    choice("status", "queued running completed failed cancelled"), choice("attention", "none required acknowledged"),
    boolean("outcome_unconfirmed"), timestamp("created_at"),
    identifier("call_id", nullable=True), document("contract_snapshot", nullable=True),
    document("metadata", nullable=True), document("source_references", nullable=True),
    timestamp("started_at", nullable=True), timestamp("finished_at", nullable=True),
    checks=(SCOPE_CHECK, "runtime_generation > 0", "status NOT IN ('completed', 'failed', 'cancelled') OR outcome_unconfirmed = 0"))
execution_attempts = table("execution_attempts",
    identifier("attempt_id", primary=True), reference("execution_id", "executions.execution_id"),
    integer("attempt_index"), document("retry_contract"), timestamp("started_at", nullable=True), boolean("dispatched"),
    identifier("external_handle", nullable=True), append=True, checks=("attempt_index > 0", "dispatched = 0 OR started_at IS NOT NULL"),
    constraints=(UniqueConstraint("execution_id", "attempt_index"),))
execution_payloads = table("execution_payloads",
    identifier("payload_id", primary=True), reference("agent_id", "agents.agent_id"),
    reference("execution_id", "executions.execution_id"), choice("content_kind", "input result"),
    document("content"), identifier("digest"), append=True,
    constraints=(UniqueConstraint("execution_id", "content_kind"),))
execution_observations = table("execution_observations",
    identifier("observation_id", primary=True), reference("execution_id", "executions.execution_id"),
    reference("attempt_id", "execution_attempts.attempt_id", nullable=True),
    choice("health", "healthy degraded stalled error unknown"), identifier("evidence_kind"), document("evidence"),
    timestamp("observed_at"), boolean("uncertain"), integer("observation_index", nullable=True), append=True,
    checks=("observation_index IS NULL OR observation_index > 0",),
    constraints=(UniqueConstraint("execution_id", "observation_index"),))
execution_controls = table("execution_controls",
    identifier("control_id", primary=True), reference("execution_id", "executions.execution_id"),
    reference("requester_agent_id", "agents.agent_id"), choice("operation", "stop suspend"),
    choice("acknowledgement", "requested acknowledged unsupported uncertain"),
    timestamp("requested_at"), timestamp("acknowledged_at", nullable=True), document("outcome_race"))
tool_cooldowns = table("tool_cooldowns",
    reference("agent_id", "agents.agent_id", primary=True), identifier("tool_name", primary=True), identifier("fault_id"),
    choice("accounting_mode", "remaining wall_time"), timestamp("remaining_seconds", nullable=True),
    timestamp("deadline", nullable=True), timestamp("sampled_at"),
    checks=("(accounting_mode = 'remaining' AND remaining_seconds IS NOT NULL AND remaining_seconds >= 0 AND deadline IS NULL) OR (accounting_mode = 'wall_time' AND deadline IS NOT NULL AND remaining_seconds IS NULL)",))
model_availability = table("model_availability",
    reference("agent_id", "agents.agent_id", primary=True), identifier("model_alias", primary=True), identifier("sequence_id"),
    choice("status", "available recoverable remediation_required"), identifier("reason"), timestamp("request_budget"),
    timestamp("sequence_budget"), timestamp("earliest_admission_at", nullable=True), document("last_confirmed"),
    checks=("request_budget > 0", "sequence_budget >= request_budget"))
team_position_cooldowns = table("team_position_cooldowns",
    reference("team_id", "teams.team_id", primary=True), reference("event_id", "team_topology_events.event_id"),
    choice("accounting_mode", "remaining wall_time"), timestamp("remaining_seconds", nullable=True),
    timestamp("deadline", nullable=True), timestamp("sampled_at"), timestamp("duration_seconds"),
    checks=("duration_seconds > 0", "(accounting_mode = 'remaining' AND remaining_seconds IS NOT NULL AND remaining_seconds >= 0 AND deadline IS NULL) OR (accounting_mode = 'wall_time' AND deadline IS NOT NULL AND remaining_seconds IS NULL)"))
