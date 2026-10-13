"""Retained topology, ephemeral audit provenance, and publication evidence."""

from sqlalchemy import ForeignKeyConstraint, UniqueConstraint

from .columns import boolean, choice, document, identifier, integer, reference, table, timestamp


team_topology_events = table("team_topology_events",
    identifier("event_id", primary=True), reference("team_id", "teams.team_id"),
    reference("old_parent_agent_id", "agents.agent_id", nullable=True), reference("old_parent_team_id", "teams.team_id", nullable=True),
    reference("new_parent_agent_id", "agents.agent_id", nullable=True), reference("new_parent_team_id", "teams.team_id", nullable=True),
    reference("creator_agent_id", "agents.agent_id", nullable=True), reference("creator_team_id", "teams.team_id", nullable=True),
    reference("acceptance_id", "parent_acceptances.acceptance_id", nullable=True),
    reference("case_id", "governance_cases.case_id", nullable=True),
    choice("transition", "creation attachment migration voluntary_detachment parent_loss"), timestamp("created_at"), append=True,
    checks=("old_parent_agent_id IS NULL OR old_parent_team_id IS NULL", "new_parent_agent_id IS NULL OR new_parent_team_id IS NULL",
            "(creator_agent_id IS NULL) <> (creator_team_id IS NULL)", "transition NOT IN ('voluntary_detachment', 'parent_loss') OR (new_parent_agent_id IS NULL AND new_parent_team_id IS NULL)"))
parent_acceptances = table("parent_acceptances",
    identifier("acceptance_id", primary=True), reference("attaching_team_id", "teams.team_id"),
    reference("parent_agent_id", "agents.agent_id", nullable=True), reference("parent_team_id", "teams.team_id", nullable=True),
    reference("case_id", "governance_cases.case_id", nullable=True), reference("decision_agent_id", "agents.agent_id", nullable=True),
    boolean("approved"), identifier("topology_fingerprint"), timestamp("created_at"), append=True,
    checks=("(parent_agent_id IS NULL) <> (parent_team_id IS NULL)", "(case_id IS NULL) <> (decision_agent_id IS NULL)"))
health_incidents = table("health_incidents",
    identifier("incident_id", primary=True), reference("subject_agent_id", "agents.agent_id", nullable=True),
    reference("subject_team_id", "teams.team_id", nullable=True), identifier("fingerprint"), integer("occurrence_count"),
    timestamp("first_at"), timestamp("latest_at"), document("evidence"), choice("status", "pending claimed acknowledged"),
    checks=("(subject_agent_id IS NULL) <> (subject_team_id IS NULL)", "occurrence_count > 0", "latest_at >= first_at"),
    constraints=(UniqueConstraint("subject_agent_id", "fingerprint"), UniqueConstraint("subject_team_id", "fingerprint")))
audit_runs = table("audit_runs",
    identifier("audit_id", primary=True), reference("subject_agent_id", "agents.agent_id", nullable=True),
    reference("subject_team_id", "teams.team_id", nullable=True), identifier("temporary_team_id"),
    document("template"), document("electorate"), integer("runtime_generation"),
    choice("status", "prepared running completed interrupted unknown"), timestamp("created_at"),
    timestamp("deadline"), integer("token_budget"),
    checks=("(subject_agent_id IS NULL) <> (subject_team_id IS NULL)", "runtime_generation > 0", "token_budget >= 0", "deadline >= created_at"))
audit_participants = table("audit_participants",
    reference("audit_id", "audit_runs.audit_id", primary=True), identifier("scoped_agent_id", primary=True),
    document("identity_snapshot"), identifier("model_alias"), integer("position"), append=True,
    checks=("position >= 0",), constraints=(UniqueConstraint("audit_id", "position"),))


def participant_constraint():
    return ForeignKeyConstraint(["audit_id", "scoped_agent_id"],
                                ["audit_participants.audit_id", "audit_participants.scoped_agent_id"], ondelete="RESTRICT")


audit_model_requests = table("audit_model_requests",
    identifier("request_id", primary=True), identifier("audit_id"), identifier("scoped_agent_id"),
    identifier("invocation_id"), identifier("frame_id"), integer("input_version"), identifier("model_alias"),
    integer("attempt_index"), choice("dispatch_state", "unsent sent confirmed_unsent unknown_sent"),
    choice("outcome", "pending completed failed cancelled uncertain"), timestamp("created_at"),
    timestamp("dispatched_at", nullable=True), timestamp("request_budget"), timestamp("sequence_budget"),
    checks=("input_version >= 0", "attempt_index > 0", "request_budget > 0", "sequence_budget >= request_budget"),
    constraints=(participant_constraint(),))
audit_execution_evidence = table("audit_execution_evidence",
    identifier("execution_id", primary=True), identifier("audit_id"), identifier("scoped_agent_id"),
    identifier("tool_name"), document("effects"), integer("attempt_index"), integer("runtime_generation"),
    choice("status", "queued running completed failed cancelled"), choice("health", "healthy degraded stalled error unknown"),
    choice("attention", "none required acknowledged"), document("sanitized_result"), boolean("outcome_unconfirmed"),
    checks=("attempt_index > 0", "runtime_generation > 0"), constraints=(participant_constraint(),))
audit_chat_evidence = table("audit_chat_evidence",
    identifier("event_id", primary=True), identifier("audit_id"), identifier("scoped_agent_id"), integer("sequence"),
    choice("event_kind", "send edit withdraw"), document("findings"), timestamp("created_at"), append=True,
    checks=("sequence > 0",), constraints=(participant_constraint(), UniqueConstraint("audit_id", "sequence")))
audit_evidence = table("audit_evidence",
    reference("audit_id", "audit_runs.audit_id", primary=True), document("evidence_references"), document("findings"),
    choice("result", "healthy unhealthy unknown"), document("identity_snapshots"), timestamp("created_at"), append=True)
recovery_incidents = table("recovery_incidents",
    identifier("incident_id", primary=True), reference("agent_id", "agents.agent_id"), identifier("checkpoint_id"),
    reference("publication_id", "publication_manifests.publication_id", nullable=True),
    reference("invocation_id", "activity_invocations.invocation_id", nullable=True),
    reference("execution_id", "executions.execution_id", nullable=True), identifier("affected_identity"),
    document("last_confirmed"), boolean("uncertain"), timestamp("created_at"), append=True,
    constraints=(UniqueConstraint("checkpoint_id", "agent_id", "affected_identity"),))
publication_manifests = table("publication_manifests",
    identifier("publication_id", primary=True), identifier("checkpoint_id"), integer("previous_generation"),
    integer("target_generation"), document("staged_files"), identifier("recovery_operation_id"),
    choice("status", "prepared published rolled_back"), timestamp("prepared_at"), timestamp("resolved_at", nullable=True),
    checks=("previous_generation > 0", "target_generation > previous_generation"))
