"""Ordered chat facts, historical membership, and personal visibility."""

from sqlalchemy import Index, UniqueConstraint

from .columns import boolean, choice, document, identifier, integer, reference, table, timestamp


direct_relationships = table("direct_relationships",
    identifier("relationship_id", primary=True), reference("agent_a_id", "agents.agent_id"),
    reference("agent_b_id", "agents.agent_id"), boolean("friendship"), boolean("blocked_a"), boolean("blocked_b"),
    boolean("refused_a"), boolean("refused_b"), integer("generation"), integer("allowance_a"), integer("allowance_b"),
    checks=("agent_a_id < agent_b_id", "generation > 0", "allowance_a BETWEEN 0 AND 3", "allowance_b BETWEEN 0 AND 3"),
    constraints=(UniqueConstraint("agent_a_id", "agent_b_id"),))
friendship_requests = table("friendship_requests",
    identifier("request_id", primary=True), reference("relationship_id", "direct_relationships.relationship_id"),
    reference("sender_agent_id", "agents.agent_id"), reference("recipient_agent_id", "agents.agent_id"),
    integer("generation"), choice("status", "pending accepted rejected ignored cancelled stale"),
    timestamp("created_at"), timestamp("responded_at", nullable=True),
    checks=("generation > 0", "sender_agent_id <> recipient_agent_id"))
chat_streams = table("chat_streams",
    identifier("stream_id", primary=True), reference("team_id", "teams.team_id", nullable=True, unique=True),
    reference("relationship_id", "direct_relationships.relationship_id", nullable=True, unique=True), integer("next_position"),
    checks=("(team_id IS NULL) <> (relationship_id IS NULL)", "next_position > 0"))
chat_events = table("chat_events",
    identifier("event_id", primary=True), reference("stream_id", "chat_streams.stream_id"), integer("sequence"),
    choice("event_kind", "join leave send edit withdraw dissolve"),
    reference("actor_agent_id", "agents.agent_id", nullable=True), timestamp("created_at"), append=True,
    checks=("sequence > 0",), constraints=(UniqueConstraint("stream_id", "sequence"),))
membership_intervals = table("membership_intervals",
    identifier("interval_id", primary=True), reference("team_id", "teams.team_id"), reference("agent_id", "agents.agent_id"),
    reference("stream_id", "chat_streams.stream_id"), reference("join_event_id", "chat_events.event_id", unique=True),
    reference("leave_event_id", "chat_events.event_id", nullable=True))
Index("uq_open_membership", membership_intervals.c.team_id, membership_intervals.c.agent_id,
      unique=True, sqlite_where=membership_intervals.c.leave_event_id.is_(None))
chat_messages = table("chat_messages",
    identifier("message_id", primary=True), reference("stream_id", "chat_streams.stream_id"),
    reference("author_agent_id", "agents.agent_id"), reference("publication_event_id", "chat_events.event_id", unique=True),
    reference("invocation_id", "activity_invocations.invocation_id"), identifier("operation_key"),
    timestamp("created_at"), append=True, constraints=(UniqueConstraint("invocation_id", "operation_key"),))
chat_revisions = table("chat_revisions",
    identifier("revision_id", primary=True), reference("message_id", "chat_messages.message_id"),
    reference("event_id", "chat_events.event_id", unique=True), integer("revision_number"),
    document("markdown"), document("title"), timestamp("committed_at"), append=True,
    checks=("revision_number > 0",), constraints=(UniqueConstraint("message_id", "revision_number"),))
chat_withdrawals = table("chat_withdrawals",
    identifier("withdrawal_id", primary=True), reference("message_id", "chat_messages.message_id", unique=True),
    reference("revision_id", "chat_revisions.revision_id"), reference("actor_agent_id", "agents.agent_id"),
    reference("event_id", "chat_events.event_id", unique=True), timestamp("window_seconds"),
    timestamp("committed_at"), append=True, checks=("window_seconds > 0 AND window_seconds <= 600",))
chat_message_projections = table("chat_message_projections",
    reference("message_id", "chat_messages.message_id", primary=True), reference("revision_id", "chat_revisions.revision_id"),
    reference("withdrawal_id", "chat_withdrawals.withdrawal_id", nullable=True))
chat_personal_views = table("chat_personal_views",
    identifier("view_id", primary=True), reference("agent_id", "agents.agent_id"), reference("message_id", "chat_messages.message_id"),
    reference("interval_id", "membership_intervals.interval_id", nullable=True), reference("revision_id", "chat_revisions.revision_id"),
    reference("withdrawal_id", "chat_withdrawals.withdrawal_id", nullable=True), choice("view_kind", "live frozen"),
    integer("departure_cutoff", nullable=True), timestamp("read_at", nullable=True), boolean("unread_override"), boolean("deleted"),
    checks=("(view_kind = 'live' AND departure_cutoff IS NULL) OR (view_kind = 'frozen' AND departure_cutoff IS NOT NULL AND departure_cutoff > 0)",),
    constraints=(UniqueConstraint("agent_id", "message_id", "interval_id"),))
Index("uq_direct_personal_view", chat_personal_views.c.agent_id, chat_personal_views.c.message_id,
      unique=True, sqlite_where=chat_personal_views.c.interval_id.is_(None))
