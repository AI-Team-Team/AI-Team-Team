"""Admission, provider evidence, addressed notification, and sleep records."""

from sqlalchemy import CheckConstraint, Index, UniqueConstraint

from .columns import SCOPE_CHECK, boolean, choice, document, identifier, integer, reference, scope, table, timestamp


agent_activities = table("agent_activities",
    reference("agent_id", "agents.agent_id", primary=True), choice("intent", "continuing idle sleep"),
    choice("availability", "ready waiting_model waiting_tool resource_blocked unavailable closing"), integer("arrival_generation"),
    integer("presentation_generation"), integer("context_version"),
    reference("admission_id", "activity_admissions.admission_id", nullable=True),
    checks=("arrival_generation >= 0", "presentation_generation >= 0", "context_version >= 0"))
activity_admissions = table("activity_admissions",
    identifier("admission_id", primary=True), reference("agent_id", "agents.agent_id"),
    integer("runtime_generation"), *scope(), choice("disposition", "admitted completed interrupted cancelled"),
    timestamp("accepted_at"), checks=(SCOPE_CHECK, "runtime_generation > 0"))
Index("uq_live_activity_owner", activity_admissions.c.agent_id, unique=True,
      sqlite_where=activity_admissions.c.disposition == "admitted")
activity_invocations = table("activity_invocations",
    identifier("invocation_id", primary=True), reference("admission_id", "activity_admissions.admission_id"),
    reference("agent_id", "agents.agent_id"), integer("runtime_generation"), *scope(),
    integer("context_version"), timestamp("started_at"), timestamp("boundary_at", nullable=True),
    boolean("interrupted"), checks=(SCOPE_CHECK, "runtime_generation > 0", "context_version >= 0"))
notification_frames = table("notification_frames",
    identifier("frame_id", primary=True), reference("invocation_id", "activity_invocations.invocation_id"),
    reference("agent_id", "agents.agent_id"), integer("context_version"), integer("arrival_cutoff"),
    document("summary_references"), append=True, checks=("context_version >= 0", "arrival_cutoff >= 0"))
model_requests = table("model_requests",
    identifier("model_request_id", primary=True), reference("frame_id", "notification_frames.frame_id"),
    reference("agent_id", "agents.agent_id"), identifier("model_alias"), integer("attempt_index"),
    integer("input_version"), choice("dispatch_state", "unsent sent confirmed_unsent unknown_sent"),
    choice("outcome", "pending completed failed cancelled uncertain"), timestamp("created_at"),
    timestamp("dispatched_at", nullable=True), timestamp("earliest_retry_at", nullable=True),
    timestamp("request_budget"), timestamp("sequence_budget"),
    checks=("attempt_index > 0", "input_version >= 0", "request_budget > 0", "sequence_budget >= request_budget"))
memory_index_requests = table("memory_index_requests",
    identifier("request_id", primary=True), reference("segment_id", "agent_memory_segments.segment_id"),
    reference("beneficiary_agent_id", "agents.agent_id"), integer("source_version"), identifier("model_alias"),
    integer("attempt_index"), choice("dispatch_state", "unsent sent confirmed_unsent unknown_sent"),
    choice("outcome", "pending completed failed cancelled uncertain"), identifier("input_digest"),
    timestamp("created_at"), timestamp("dispatched_at", nullable=True),
    checks=("source_version > 0", "attempt_index > 0"))
model_token_claims = table("model_token_claims",
    identifier("claim_id", primary=True),
    reference("model_request_id", "model_requests.model_request_id", nullable=True, unique=True),
    reference("audit_request_id", "audit_model_requests.request_id", nullable=True, unique=True),
    reference("index_request_id", "memory_index_requests.request_id", nullable=True, unique=True),
    identifier("model_alias"), integer("prompt_budget"), integer("output_budget"),
    choice("settlement", "reserved confirmed_unsent known_usage unknown_sent"),
    integer("actual_usage", nullable=True), timestamp("settled_at", nullable=True),
    checks=("(model_request_id IS NOT NULL) + (audit_request_id IS NOT NULL) + (index_request_id IS NOT NULL) = 1",
            "prompt_budget >= 0", "output_budget >= 0", "actual_usage IS NULL OR actual_usage >= 0",
            "(settlement = 'reserved' AND settled_at IS NULL) OR (settlement <> 'reserved' AND settled_at IS NOT NULL)",
            "(settlement = 'known_usage' AND actual_usage IS NOT NULL) OR (settlement <> 'known_usage' AND actual_usage IS NULL)"))
agent_notifications = table("agent_notifications",
    identifier("notification_id", primary=True), reference("agent_id", "agents.agent_id"),
    choice("source_kind", "team_message direct_message personal_mail execution system_event"),
    reference("chat_message_id", "chat_messages.message_id", nullable=True),
    reference("mail_id", "agent_inbox.message_id", nullable=True),
    reference("execution_id", "executions.execution_id", nullable=True),
    reference("system_event_id", "system_memory_events.event_id", nullable=True),
    reference("publication_id", "publication_manifests.publication_id", nullable=True),
    choice("classification", "ordinary membership permission health recovery"),
    identifier("deduplication_key"), integer("arrival_generation"), timestamp("created_at"), append=True,
    constraints=(UniqueConstraint("agent_id", "deduplication_key"),),
    checks=("arrival_generation > 0", "(chat_message_id IS NOT NULL) + (mail_id IS NOT NULL) + (execution_id IS NOT NULL) + (system_event_id IS NOT NULL) = 1",
            "(source_kind IN ('team_message', 'direct_message') AND chat_message_id IS NOT NULL) OR (source_kind = 'personal_mail' AND mail_id IS NOT NULL) OR (source_kind = 'execution' AND execution_id IS NOT NULL) OR (source_kind = 'system_event' AND system_event_id IS NOT NULL)"))
notification_claims = table("notification_claims",
    reference("notification_id", "agent_notifications.notification_id", primary=True),
    reference("model_request_id", "model_requests.model_request_id", primary=True),
    reference("frame_id", "notification_frames.frame_id"),
    choice("status", "reserved dispatched presented uncertain"), timestamp("observed_at"))
chat_reminder_previews = table("chat_reminder_previews",
    reference("notification_id", "agent_notifications.notification_id", primary=True),
    reference("agent_id", "agents.agent_id"), reference("revision_id", "chat_revisions.revision_id"),
    document("preview"), document("visibility"), append=True)
notification_suppression = table("notification_suppression",
    identifier("preference_id", primary=True), reference("agent_id", "agents.agent_id"),
    choice("scope", "all agent agent_team"), reference("source_agent_id", "agents.agent_id", nullable=True),
    reference("source_team_id", "teams.team_id", nullable=True), boolean("permanent"),
    timestamp("remaining_seconds", nullable=True), timestamp("sampled_at"),
    checks=("(scope = 'all' AND source_agent_id IS NULL AND source_team_id IS NULL) OR (scope = 'agent' AND source_agent_id IS NOT NULL AND source_team_id IS NULL) OR (scope = 'agent_team' AND source_team_id IS NOT NULL AND source_agent_id IS NULL)",
            "(permanent = 1 AND remaining_seconds IS NULL) OR (permanent = 0 AND remaining_seconds IS NOT NULL AND remaining_seconds >= 0)"))
sleep_plans = table("sleep_plans",
    identifier("sleep_id", primary=True), reference("agent_id", "agents.agent_id"),
    timestamp("latest_wake_seconds"), timestamp("remaining_seconds"), timestamp("sampled_at"),
    timestamp("minimum_seconds"), timestamp("maximum_seconds"), choice("status", "active expired cancelled"),
    checks=("latest_wake_seconds > 0", "remaining_seconds >= 0", "minimum_seconds > 0", "maximum_seconds >= minimum_seconds",
            "latest_wake_seconds BETWEEN minimum_seconds AND maximum_seconds", "remaining_seconds <= latest_wake_seconds"))
Index("uq_active_sleep_owner", sleep_plans.c.agent_id, unique=True, sqlite_where=sleep_plans.c.status == "active")
sleep_conditions = table("sleep_conditions",
    identifier("condition_id", primary=True), reference("sleep_id", "sleep_plans.sleep_id"),
    choice("source_kind", "agent agent_team execution"),
    reference("source_agent_id", "agents.agent_id", nullable=True), reference("source_team_id", "teams.team_id", nullable=True),
    reference("execution_id", "executions.execution_id", nullable=True), integer("admitted_generation"), boolean("invalidated"),
    checks=("admitted_generation > 0", "(source_kind = 'agent' AND source_agent_id IS NOT NULL AND source_team_id IS NULL AND execution_id IS NULL) OR (source_kind = 'agent_team' AND source_team_id IS NOT NULL AND source_agent_id IS NULL AND execution_id IS NULL) OR (source_kind = 'execution' AND execution_id IS NOT NULL AND source_agent_id IS NULL AND source_team_id IS NULL)"))
