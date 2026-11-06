-- ATT schema 16: declared relational tables and indexes.
-- Inspect this reference alongside Relational_Constraints.md and Request_and_Token_States.md.
-- ATT initializes new stores under its writer lease and schema preflight.
-- Application/ORM defaults and derived optional FTS5 structures are not SQLite server defaults.

-- manager_config
CREATE TABLE manager_config (
	config_key VARCHAR NOT NULL, 
	config_value VARCHAR, 
	PRIMARY KEY (config_key)
);

-- agents
CREATE TABLE agents (
	agent_id VARCHAR NOT NULL, 
	name VARCHAR NOT NULL, 
	role VARCHAR, 
	role_description VARCHAR, 
	system_instructions VARCHAR, 
	model_alias VARCHAR, 
	last_context VARCHAR, 
	lifecycle_state VARCHAR NOT NULL, 
	state_version INTEGER NOT NULL, 
	presentation_preferences JSON NOT NULL, 
	PRIMARY KEY (agent_id), 
	CHECK (lifecycle_state IN ('active', 'retained', 'archived', 'dead') AND state_version > 0), 
	UNIQUE (name)
);

-- agent_messages
CREATE TABLE agent_messages (
	id INTEGER NOT NULL, 
	agent_id VARCHAR NOT NULL, 
	role VARCHAR NOT NULL, 
	content VARCHAR, 
	created_at FLOAT NOT NULL, 
	tool_calls JSON, 
	tool_call_id VARCHAR, 
	name VARCHAR, 
	team_id VARCHAR, 
	invocation_id VARCHAR, 
	source_chat_message_id VARCHAR, 
	source_execution_id VARCHAR, 
	source_metadata JSON NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(agent_id) REFERENCES agents (agent_id) ON DELETE CASCADE, 
	FOREIGN KEY(invocation_id) REFERENCES activity_invocations (invocation_id) ON DELETE RESTRICT, 
	FOREIGN KEY(source_chat_message_id) REFERENCES chat_messages (message_id) ON DELETE RESTRICT, 
	FOREIGN KEY(source_execution_id) REFERENCES executions (execution_id) ON DELETE RESTRICT
);

-- agent_inbox
CREATE TABLE agent_inbox (
	message_id VARCHAR NOT NULL, 
	agent_id VARCHAR NOT NULL, 
	message_type VARCHAR NOT NULL, 
	payload JSON NOT NULL, 
	created_at FLOAT NOT NULL, 
	read_at FLOAT, 
	PRIMARY KEY (message_id), 
	FOREIGN KEY(agent_id) REFERENCES agents (agent_id) ON DELETE CASCADE
);

-- teams
CREATE TABLE teams (
	team_id VARCHAR NOT NULL, 
	team_kind VARCHAR NOT NULL, 
	preset_name VARCHAR, 
	team_purpose VARCHAR, 
	team_progress VARCHAR, 
	chapter_num INTEGER, 
	parent_team_id VARCHAR, 
	parent_agent_id VARCHAR, 
	position_revision INTEGER NOT NULL, 
	lifecycle_state VARCHAR NOT NULL, 
	state_version INTEGER NOT NULL, 
	creator_agent_id VARCHAR, 
	creator_team_id VARCHAR, 
	status_map VARCHAR, 
	system_instructions VARCHAR, 
	PRIMARY KEY (team_id), 
	CHECK (parent_agent_id IS NULL OR parent_team_id IS NULL), 
	CHECK (position_revision > 0), 
	CHECK (lifecycle_state IN ('active', 'dissolved') AND state_version > 0), 
	CONSTRAINT ck_persisted_team_kind CHECK (team_kind = 'ordinary'), 
	CONSTRAINT ck_team_exact_creator CHECK ((creator_agent_id IS NOT NULL AND creator_team_id IS NULL) OR (creator_agent_id IS NULL AND creator_team_id IS NOT NULL)), 
	FOREIGN KEY(parent_team_id) REFERENCES teams (team_id) ON DELETE RESTRICT, 
	FOREIGN KEY(parent_agent_id) REFERENCES agents (agent_id) ON DELETE RESTRICT, 
	FOREIGN KEY(creator_agent_id) REFERENCES agents (agent_id) ON DELETE RESTRICT, 
	FOREIGN KEY(creator_team_id) REFERENCES teams (team_id) ON DELETE RESTRICT
);

-- team_members
CREATE TABLE team_members (
	team_id VARCHAR NOT NULL, 
	agent_id VARCHAR NOT NULL, 
	interval_id VARCHAR NOT NULL, 
	PRIMARY KEY (team_id, agent_id), 
	FOREIGN KEY(team_id) REFERENCES teams (team_id) ON DELETE CASCADE, 
	FOREIGN KEY(agent_id) REFERENCES agents (agent_id) ON DELETE CASCADE, 
	UNIQUE (interval_id), 
	FOREIGN KEY(interval_id) REFERENCES membership_intervals (interval_id) ON DELETE RESTRICT
);

-- team_inbox
CREATE TABLE team_inbox (
	id INTEGER NOT NULL, 
	team_id VARCHAR NOT NULL, 
	sender VARCHAR, 
	msg_type VARCHAR, 
	payload VARCHAR, 
	created_at FLOAT NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(team_id) REFERENCES teams (team_id) ON DELETE CASCADE
);

-- team_proposals
CREATE TABLE team_proposals (
	proposal_id VARCHAR NOT NULL, 
	team_id VARCHAR NOT NULL, 
	action VARCHAR, 
	target VARCHAR, 
	initiator_type VARCHAR, 
	initiator_name VARCHAR, 
	initiator_agent_id VARCHAR, 
	rationale VARCHAR, 
	proposed_details VARCHAR, 
	votes VARCHAR, 
	status VARCHAR, 
	PRIMARY KEY (proposal_id), 
	FOREIGN KEY(team_id) REFERENCES teams (team_id) ON DELETE CASCADE, 
	FOREIGN KEY(initiator_agent_id) REFERENCES agents (agent_id) ON DELETE SET NULL
);

-- libraries
CREATE TABLE libraries (
	lib_id VARCHAR NOT NULL, 
	name VARCHAR, 
	library_kind VARCHAR NOT NULL, 
	owner_team_id VARCHAR, 
	owner_agent_id VARCHAR, 
	lifecycle_state VARCHAR NOT NULL, 
	description VARCHAR, 
	is_public_visible INTEGER NOT NULL, 
	PRIMARY KEY (lib_id), 
	CONSTRAINT ck_library_exact_owner CHECK ((library_kind = 'team' AND owner_team_id IS NOT NULL AND owner_agent_id IS NULL) OR (library_kind = 'agent_private' AND owner_team_id IS NULL AND owner_agent_id IS NOT NULL)), 
	FOREIGN KEY(owner_team_id) REFERENCES teams (team_id) ON DELETE CASCADE, 
	UNIQUE (owner_agent_id), 
	FOREIGN KEY(owner_agent_id) REFERENCES agents (agent_id) ON DELETE CASCADE
);

-- library_permissions
CREATE TABLE library_permissions (
	lib_id VARCHAR NOT NULL, 
	path VARCHAR NOT NULL, 
	team_id VARCHAR NOT NULL, 
	permission VARCHAR, 
	PRIMARY KEY (lib_id, path, team_id)
);

-- doc_lib_files
CREATE TABLE doc_lib_files (
	lib_id VARCHAR NOT NULL, 
	path VARCHAR NOT NULL, 
	content VARCHAR, 
	PRIMARY KEY (lib_id, path), 
	FOREIGN KEY(lib_id) REFERENCES libraries (lib_id) ON DELETE CASCADE
);

-- doc_lib_links
CREATE TABLE doc_lib_links (
	source_lib_id VARCHAR NOT NULL, 
	source_path VARCHAR NOT NULL, 
	target_lib_id VARCHAR NOT NULL, 
	target_path VARCHAR NOT NULL, 
	PRIMARY KEY (source_lib_id, source_path), 
	FOREIGN KEY(source_lib_id) REFERENCES libraries (lib_id) ON DELETE CASCADE, 
	FOREIGN KEY(target_lib_id) REFERENCES libraries (lib_id) ON DELETE CASCADE
);

-- team_formation_requests
CREATE TABLE team_formation_requests (
	request_id VARCHAR NOT NULL, 
	initiator_agent_id VARCHAR NOT NULL, 
	creator_kind VARCHAR NOT NULL, 
	creator_agent_id VARCHAR, 
	creator_team_id VARCHAR, 
	parent_team_id VARCHAR, 
	task VARCHAR, 
	parent_agent_id VARCHAR, 
	member_count INTEGER NOT NULL, 
	roles_and_presets JSON, 
	preset_name VARCHAR NOT NULL, 
	system_instructions VARCHAR NOT NULL, 
	team_purpose VARCHAR NOT NULL, 
	roles_and_models JSON, 
	member_configs JSON, 
	invitee_agent_ids JSON NOT NULL, 
	initial_docs JSON, 
	is_public_visible INTEGER NOT NULL, 
	initiator_joins INTEGER NOT NULL, 
	unanimous_acceptance_action VARCHAR NOT NULL, 
	late_join_policy VARCHAR NOT NULL, 
	proposal_revision INTEGER NOT NULL, 
	content_fingerprint VARCHAR NOT NULL, 
	revision_fingerprint VARCHAR NOT NULL, 
	status VARCHAR NOT NULL, 
	created_team_id VARCHAR, 
	decision_reason VARCHAR NOT NULL, 
	created_at FLOAT NOT NULL, 
	updated_at FLOAT NOT NULL, 
	resolved_at FLOAT, 
	PRIMARY KEY (request_id), 
	CONSTRAINT ck_team_formation_exact_creator CHECK ((creator_kind = 'agent' AND creator_agent_id IS NOT NULL AND creator_team_id IS NULL) OR (creator_kind = 'agent_team' AND creator_agent_id IS NULL AND creator_team_id IS NOT NULL)), 
	CONSTRAINT ck_team_formation_status CHECK (status IN ('collecting_responses', 'ready_for_confirmation', 'created', 'abandoned')), 
	CHECK (parent_agent_id IS NULL OR parent_team_id IS NULL), 
	CONSTRAINT ck_team_formation_public_visible_boolean CHECK (is_public_visible IN (0, 1)), 
	CONSTRAINT ck_team_formation_initiator_joins_boolean CHECK (initiator_joins IN (0, 1)), 
	CONSTRAINT ck_team_formation_positive_counts CHECK (member_count >= 1 AND proposal_revision >= 1), 
	CONSTRAINT uq_team_formation_created_team UNIQUE (created_team_id), 
	FOREIGN KEY(initiator_agent_id) REFERENCES agents (agent_id) ON DELETE RESTRICT, 
	FOREIGN KEY(creator_agent_id) REFERENCES agents (agent_id) ON DELETE RESTRICT, 
	FOREIGN KEY(creator_team_id) REFERENCES teams (team_id) ON DELETE RESTRICT, 
	FOREIGN KEY(parent_team_id) REFERENCES teams (team_id) ON DELETE RESTRICT, 
	FOREIGN KEY(parent_agent_id) REFERENCES agents (agent_id) ON DELETE RESTRICT, 
	FOREIGN KEY(created_team_id) REFERENCES teams (team_id) ON DELETE RESTRICT
);

-- team_formation_invitations
CREATE TABLE team_formation_invitations (
	request_id VARCHAR NOT NULL, 
	agent_id VARCHAR NOT NULL, 
	proposal_revision INTEGER NOT NULL, 
	attitude VARCHAR NOT NULL, 
	responded_at FLOAT, 
	joined_at FLOAT, 
	late_join_pending INTEGER NOT NULL, 
	late_join_requested_at FLOAT, 
	late_join_decision VARCHAR, 
	PRIMARY KEY (request_id, agent_id), 
	CONSTRAINT ck_team_formation_invitation_attitude CHECK (attitude IN ('accepted', 'declined', 'explicitly_ignored', 'no_response')), 
	CONSTRAINT ck_team_formation_late_join_pending_boolean CHECK (late_join_pending IN (0, 1)), 
	FOREIGN KEY(request_id) REFERENCES team_formation_requests (request_id) ON DELETE CASCADE, 
	FOREIGN KEY(agent_id) REFERENCES agents (agent_id) ON DELETE RESTRICT
);

-- team_formation_revisions
CREATE TABLE team_formation_revisions (
	revision_id VARCHAR NOT NULL, 
	request_id VARCHAR NOT NULL, 
	proposal_revision INTEGER NOT NULL, 
	content_fingerprint VARCHAR NOT NULL, 
	revision_fingerprint VARCHAR NOT NULL, 
	proposal_snapshot JSON NOT NULL, 
	revised_by_agent_id VARCHAR NOT NULL, 
	source_draft_id VARCHAR, 
	created_at FLOAT NOT NULL, 
	PRIMARY KEY (revision_id), 
	CONSTRAINT uq_team_formation_revision_number UNIQUE (request_id, proposal_revision), 
	CONSTRAINT uq_team_formation_revision_source_draft UNIQUE (source_draft_id), 
	CONSTRAINT ck_team_formation_revision_positive CHECK (proposal_revision >= 1), 
	FOREIGN KEY(request_id) REFERENCES team_formation_requests (request_id) ON DELETE CASCADE, 
	FOREIGN KEY(revised_by_agent_id) REFERENCES agents (agent_id) ON DELETE RESTRICT
);

-- team_formation_invitation_decisions
CREATE TABLE team_formation_invitation_decisions (
	decision_id VARCHAR NOT NULL, 
	request_id VARCHAR NOT NULL, 
	proposal_revision INTEGER NOT NULL, 
	agent_id VARCHAR NOT NULL, 
	attitude VARCHAR NOT NULL, 
	created_at FLOAT NOT NULL, 
	PRIMARY KEY (decision_id), 
	CONSTRAINT ck_team_formation_decision_revision_positive CHECK (proposal_revision >= 1), 
	CONSTRAINT ck_team_formation_decision_attitude CHECK (attitude IN ('accepted', 'declined', 'explicitly_ignored', 'no_response')), 
	FOREIGN KEY(request_id) REFERENCES team_formation_requests (request_id) ON DELETE CASCADE, 
	FOREIGN KEY(agent_id) REFERENCES agents (agent_id) ON DELETE RESTRICT
);

-- team_formation_drafts
CREATE TABLE team_formation_drafts (
	draft_id VARCHAR NOT NULL, 
	initiator_agent_id VARCHAR NOT NULL, 
	creator_kind VARCHAR NOT NULL, 
	creator_agent_id VARCHAR, 
	creator_team_id VARCHAR, 
	parent_team_id VARCHAR, 
	parent_agent_id VARCHAR, 
	request_id VARCHAR, 
	base_revision INTEGER, 
	base_revision_fingerprint VARCHAR, 
	objective VARCHAR NOT NULL, 
	status VARCHAR NOT NULL, 
	participant_agent_ids JSON NOT NULL, 
	source_message_id VARCHAR, 
	initiator_invocation_id VARCHAR, 
	candidate JSON, 
	reason VARCHAR NOT NULL, 
	created_at FLOAT NOT NULL, 
	updated_at FLOAT NOT NULL, 
	PRIMARY KEY (draft_id), 
	CONSTRAINT ck_team_formation_draft_creator CHECK ((creator_kind = 'agent' AND creator_agent_id IS NOT NULL AND creator_team_id IS NULL) OR (creator_kind = 'agent_team' AND creator_agent_id IS NULL AND creator_team_id IS NOT NULL)), 
	CONSTRAINT ck_team_formation_draft_exact_base CHECK ((request_id IS NULL AND base_revision IS NULL AND base_revision_fingerprint IS NULL) OR (request_id IS NOT NULL AND base_revision IS NOT NULL AND base_revision_fingerprint IS NOT NULL)), 
	CONSTRAINT ck_team_formation_draft_status CHECK (status IN ('ready', 'stale', 'published')), 
	CONSTRAINT ck_team_formation_draft_revision_positive CHECK (base_revision IS NULL OR base_revision >= 1), 
	FOREIGN KEY(initiator_agent_id) REFERENCES agents (agent_id) ON DELETE RESTRICT, 
	FOREIGN KEY(creator_agent_id) REFERENCES agents (agent_id) ON DELETE RESTRICT, 
	FOREIGN KEY(creator_team_id) REFERENCES teams (team_id) ON DELETE RESTRICT, 
	FOREIGN KEY(parent_team_id) REFERENCES teams (team_id) ON DELETE RESTRICT, 
	FOREIGN KEY(parent_agent_id) REFERENCES agents (agent_id) ON DELETE RESTRICT, 
	FOREIGN KEY(request_id) REFERENCES team_formation_requests (request_id) ON DELETE CASCADE, 
	FOREIGN KEY(source_message_id) REFERENCES chat_messages (message_id) ON DELETE RESTRICT, 
	FOREIGN KEY(initiator_invocation_id) REFERENCES activity_invocations (invocation_id) ON DELETE RESTRICT
);

-- communication_requests
CREATE TABLE communication_requests (
	request_id VARCHAR NOT NULL, 
	sender_team_id VARCHAR NOT NULL, 
	recipient_team_id VARCHAR NOT NULL, 
	initiated_by_agent_id VARCHAR, 
	rationale VARCHAR NOT NULL, 
	direction VARCHAR NOT NULL, 
	policy_snapshot JSON NOT NULL, 
	approval_principals JSON NOT NULL, 
	route_fingerprint VARCHAR NOT NULL, 
	route_evidence JSON NOT NULL, 
	status VARCHAR NOT NULL, 
	decision_reason VARCHAR NOT NULL, 
	created_at FLOAT NOT NULL, 
	resolved_at FLOAT, 
	superseded_by_request_id VARCHAR, 
	supersedes_request_id VARCHAR, 
	PRIMARY KEY (request_id), 
	CONSTRAINT ck_communication_request_distinct_teams CHECK (sender_team_id <> recipient_team_id), 
	CONSTRAINT ck_communication_request_direction CHECK (direction IN ('one_way', 'bidirectional')), 
	FOREIGN KEY(sender_team_id) REFERENCES teams (team_id) ON DELETE RESTRICT, 
	FOREIGN KEY(recipient_team_id) REFERENCES teams (team_id) ON DELETE RESTRICT, 
	FOREIGN KEY(initiated_by_agent_id) REFERENCES agents (agent_id) ON DELETE SET NULL
);

-- communication_approvals
CREATE TABLE communication_approvals (
	request_id VARCHAR NOT NULL, 
	principal_kind VARCHAR NOT NULL, 
	principal_id VARCHAR NOT NULL, 
	sequence INTEGER NOT NULL, 
	status VARCHAR NOT NULL, 
	reason VARCHAR NOT NULL, 
	created_at FLOAT NOT NULL, 
	resolved_at FLOAT, 
	case_id VARCHAR, 
	PRIMARY KEY (request_id, principal_kind, principal_id), 
	CONSTRAINT ck_communication_approval_principal_kind CHECK (principal_kind IN ('agent_team', 'agent')), 
	FOREIGN KEY(request_id) REFERENCES communication_requests (request_id) ON DELETE CASCADE, 
	FOREIGN KEY(case_id) REFERENCES governance_cases (case_id) ON DELETE RESTRICT
);

-- communication_agreements
CREATE TABLE communication_agreements (
	agreement_id VARCHAR NOT NULL, 
	source_team_id VARCHAR NOT NULL, 
	target_team_id VARCHAR NOT NULL, 
	direction VARCHAR NOT NULL, 
	allowed_message_types JSON NOT NULL, 
	created_from_request_id VARCHAR NOT NULL, 
	policy_snapshot JSON NOT NULL, 
	active INTEGER NOT NULL, 
	created_at FLOAT NOT NULL, 
	revoked_at FLOAT, 
	revoked_by_team_id VARCHAR, 
	revoke_reason VARCHAR, 
	superseded_by_agreement_id VARCHAR, 
	PRIMARY KEY (agreement_id), 
	CONSTRAINT ck_communication_agreement_distinct_teams CHECK (source_team_id <> target_team_id), 
	CONSTRAINT ck_communication_agreement_direction CHECK (direction IN ('one_way', 'bidirectional')), 
	FOREIGN KEY(source_team_id) REFERENCES teams (team_id) ON DELETE RESTRICT, 
	FOREIGN KEY(target_team_id) REFERENCES teams (team_id) ON DELETE RESTRICT, 
	FOREIGN KEY(created_from_request_id) REFERENCES communication_requests (request_id) ON DELETE RESTRICT, 
	FOREIGN KEY(revoked_by_team_id) REFERENCES teams (team_id) ON DELETE RESTRICT
);

-- peer_messages
CREATE TABLE peer_messages (
	message_id VARCHAR NOT NULL, 
	sender_team_id VARCHAR NOT NULL, 
	recipient_team_id VARCHAR NOT NULL, 
	initiated_by_agent_id VARCHAR, 
	agreement_id VARCHAR, 
	content VARCHAR NOT NULL, 
	delivery_state VARCHAR NOT NULL, 
	created_at FLOAT NOT NULL, 
	consumed_at FLOAT, 
	invocation_id VARCHAR, 
	PRIMARY KEY (message_id), 
	FOREIGN KEY(sender_team_id) REFERENCES teams (team_id) ON DELETE RESTRICT, 
	FOREIGN KEY(recipient_team_id) REFERENCES teams (team_id) ON DELETE RESTRICT, 
	FOREIGN KEY(initiated_by_agent_id) REFERENCES agents (agent_id) ON DELETE SET NULL, 
	FOREIGN KEY(agreement_id) REFERENCES communication_agreements (agreement_id) ON DELETE SET NULL, 
	UNIQUE (invocation_id)
);

-- governance_cases
CREATE TABLE governance_cases (
	case_id VARCHAR NOT NULL, 
	principal_team_id VARCHAR, 
	principal_agent_id VARCHAR, 
	data JSON NOT NULL, 
	electorate_revision INTEGER NOT NULL, 
	choice_schema JSON NOT NULL, 
	state_version INTEGER NOT NULL, 
	PRIMARY KEY (case_id), 
	CONSTRAINT ck_governance_principal_owner CHECK ((principal_team_id IS NULL) <> (principal_agent_id IS NULL)), 
	CHECK (electorate_revision > 0 AND state_version > 0), 
	CHECK (length(trim(case_id)) > 0), 
	FOREIGN KEY(principal_team_id) REFERENCES teams (team_id) ON DELETE RESTRICT, 
	FOREIGN KEY(principal_agent_id) REFERENCES agents (agent_id) ON DELETE RESTRICT
);

-- governance_electorates
CREATE TABLE governance_electorates (
	case_id VARCHAR NOT NULL, 
	voter_agent_id VARCHAR NOT NULL, 
	position INTEGER NOT NULL, 
	eligibility JSON NOT NULL, 
	membership_interval_id VARCHAR, 
	created_version INTEGER NOT NULL, 
	PRIMARY KEY (case_id, voter_agent_id), 
	CHECK (position >= 0 AND created_version > 0), 
	UNIQUE (case_id, position), 
	FOREIGN KEY(case_id) REFERENCES governance_cases (case_id) ON DELETE RESTRICT, 
	FOREIGN KEY(voter_agent_id) REFERENCES agents (agent_id) ON DELETE RESTRICT, 
	FOREIGN KEY(membership_interval_id) REFERENCES membership_intervals (interval_id) ON DELETE RESTRICT
);

-- governance_ballots
CREATE TABLE governance_ballots (
	ballot_id VARCHAR NOT NULL, 
	case_id VARCHAR NOT NULL, 
	voter_agent_id VARCHAR NOT NULL, 
	choice JSON NOT NULL, 
	created_at FLOAT NOT NULL, 
	created_version INTEGER NOT NULL, 
	PRIMARY KEY (ballot_id), 
	CONSTRAINT uq_governance_voter_case UNIQUE (case_id, voter_agent_id), 
	FOREIGN KEY(case_id, voter_agent_id) REFERENCES governance_electorates (case_id, voter_agent_id) ON DELETE RESTRICT, 
	CHECK (created_version > 0), 
	CHECK (length(trim(ballot_id)) > 0 AND created_at >= -1e308 AND created_at <= 1e308), 
	FOREIGN KEY(voter_agent_id) REFERENCES agents (agent_id) ON DELETE RESTRICT
);

-- migration_requests
CREATE TABLE migration_requests (
	request_id VARCHAR NOT NULL, 
	team_id VARCHAR NOT NULL, 
	target_parent_team_id VARCHAR, 
	target_parent_agent_id VARCHAR, 
	original_parent_team_id VARCHAR, 
	original_parent_agent_id VARCHAR, 
	acceptance_id VARCHAR, 
	detachment_kind VARCHAR, 
	path_evidence JSON NOT NULL, 
	state_version INTEGER NOT NULL, 
	data JSON NOT NULL, 
	PRIMARY KEY (request_id), 
	CHECK (target_parent_team_id IS NULL OR target_parent_agent_id IS NULL), 
	CHECK (original_parent_team_id IS NULL OR original_parent_agent_id IS NULL), 
	CHECK (detachment_kind IS NULL OR detachment_kind IN ('voluntary_departure', 'parent_loss')), 
	CHECK (detachment_kind IS NULL OR (target_parent_team_id IS NULL AND target_parent_agent_id IS NULL)), 
	CHECK (state_version > 0), 
	FOREIGN KEY(team_id) REFERENCES teams (team_id) ON DELETE RESTRICT, 
	FOREIGN KEY(target_parent_team_id) REFERENCES teams (team_id) ON DELETE RESTRICT, 
	FOREIGN KEY(target_parent_agent_id) REFERENCES agents (agent_id) ON DELETE RESTRICT, 
	FOREIGN KEY(original_parent_team_id) REFERENCES teams (team_id) ON DELETE RESTRICT, 
	FOREIGN KEY(original_parent_agent_id) REFERENCES agents (agent_id) ON DELETE RESTRICT, 
	FOREIGN KEY(acceptance_id) REFERENCES parent_acceptances (acceptance_id) ON DELETE RESTRICT
);

-- team_topology_events
CREATE TABLE team_topology_events (
	event_id VARCHAR NOT NULL, 
	team_id VARCHAR NOT NULL, 
	old_parent_agent_id VARCHAR, 
	old_parent_team_id VARCHAR, 
	new_parent_agent_id VARCHAR, 
	new_parent_team_id VARCHAR, 
	creator_agent_id VARCHAR, 
	creator_team_id VARCHAR, 
	acceptance_id VARCHAR, 
	case_id VARCHAR, 
	transition VARCHAR NOT NULL CHECK (transition IN ('creation', 'attachment', 'migration', 'voluntary_detachment', 'parent_loss')), 
	created_at FLOAT NOT NULL, 
	position_revision INTEGER NOT NULL, 
	notice_recipients JSON, 
	created_version INTEGER NOT NULL, 
	PRIMARY KEY (event_id), 
	UNIQUE (team_id, position_revision), 
	CHECK (position_revision > 0), 
	CHECK (old_parent_agent_id IS NULL OR old_parent_team_id IS NULL), 
	CHECK (new_parent_agent_id IS NULL OR new_parent_team_id IS NULL), 
	CHECK ((creator_agent_id IS NULL) <> (creator_team_id IS NULL)), 
	CHECK (transition NOT IN ('voluntary_detachment', 'parent_loss') OR (new_parent_agent_id IS NULL AND new_parent_team_id IS NULL)), 
	CHECK (created_version > 0), 
	FOREIGN KEY(team_id) REFERENCES teams (team_id) ON DELETE RESTRICT, 
	FOREIGN KEY(old_parent_agent_id) REFERENCES agents (agent_id) ON DELETE RESTRICT, 
	FOREIGN KEY(old_parent_team_id) REFERENCES teams (team_id) ON DELETE RESTRICT, 
	FOREIGN KEY(new_parent_agent_id) REFERENCES agents (agent_id) ON DELETE RESTRICT, 
	FOREIGN KEY(new_parent_team_id) REFERENCES teams (team_id) ON DELETE RESTRICT, 
	FOREIGN KEY(creator_agent_id) REFERENCES agents (agent_id) ON DELETE RESTRICT, 
	FOREIGN KEY(creator_team_id) REFERENCES teams (team_id) ON DELETE RESTRICT, 
	FOREIGN KEY(acceptance_id) REFERENCES parent_acceptances (acceptance_id) ON DELETE RESTRICT, 
	FOREIGN KEY(case_id) REFERENCES governance_cases (case_id) ON DELETE RESTRICT, 
	CHECK (event_id IS NULL OR length(trim(event_id)) > 0), 
	CHECK (team_id IS NULL OR length(trim(team_id)) > 0), 
	CHECK (old_parent_agent_id IS NULL OR length(trim(old_parent_agent_id)) > 0), 
	CHECK (old_parent_team_id IS NULL OR length(trim(old_parent_team_id)) > 0), 
	CHECK (new_parent_agent_id IS NULL OR length(trim(new_parent_agent_id)) > 0), 
	CHECK (new_parent_team_id IS NULL OR length(trim(new_parent_team_id)) > 0), 
	CHECK (creator_agent_id IS NULL OR length(trim(creator_agent_id)) > 0), 
	CHECK (creator_team_id IS NULL OR length(trim(creator_team_id)) > 0), 
	CHECK (acceptance_id IS NULL OR length(trim(acceptance_id)) > 0), 
	CHECK (case_id IS NULL OR length(trim(case_id)) > 0), 
	CHECK (transition IS NULL OR length(trim(transition)) > 0), 
	CHECK (created_at IS NULL OR created_at BETWEEN -1.0e308 AND 1.0e308)
);

-- parent_acceptances
CREATE TABLE parent_acceptances (
	acceptance_id VARCHAR NOT NULL, 
	attaching_team_id VARCHAR NOT NULL, 
	parent_agent_id VARCHAR, 
	parent_team_id VARCHAR, 
	case_id VARCHAR, 
	decision_agent_id VARCHAR, 
	approved INTEGER NOT NULL CHECK (approved IN (0, 1)), 
	topology_fingerprint VARCHAR NOT NULL, 
	created_at FLOAT NOT NULL, 
	created_version INTEGER NOT NULL, 
	PRIMARY KEY (acceptance_id), 
	CHECK ((parent_agent_id IS NULL) <> (parent_team_id IS NULL)), 
	CHECK ((case_id IS NULL) <> (decision_agent_id IS NULL)), 
	CHECK (created_version > 0), 
	FOREIGN KEY(attaching_team_id) REFERENCES teams (team_id) ON DELETE RESTRICT, 
	FOREIGN KEY(parent_agent_id) REFERENCES agents (agent_id) ON DELETE RESTRICT, 
	FOREIGN KEY(parent_team_id) REFERENCES teams (team_id) ON DELETE RESTRICT, 
	FOREIGN KEY(case_id) REFERENCES governance_cases (case_id) ON DELETE RESTRICT, 
	FOREIGN KEY(decision_agent_id) REFERENCES agents (agent_id) ON DELETE RESTRICT, 
	CHECK (acceptance_id IS NULL OR length(trim(acceptance_id)) > 0), 
	CHECK (attaching_team_id IS NULL OR length(trim(attaching_team_id)) > 0), 
	CHECK (parent_agent_id IS NULL OR length(trim(parent_agent_id)) > 0), 
	CHECK (parent_team_id IS NULL OR length(trim(parent_team_id)) > 0), 
	CHECK (case_id IS NULL OR length(trim(case_id)) > 0), 
	CHECK (decision_agent_id IS NULL OR length(trim(decision_agent_id)) > 0), 
	CHECK (topology_fingerprint IS NULL OR length(trim(topology_fingerprint)) > 0), 
	CHECK (created_at IS NULL OR created_at BETWEEN -1.0e308 AND 1.0e308)
);

-- team_position_cooldowns
CREATE TABLE team_position_cooldowns (
	team_id VARCHAR NOT NULL, 
	event_id VARCHAR NOT NULL, 
	accounting_mode VARCHAR NOT NULL CHECK (accounting_mode IN ('remaining', 'wall_time')), 
	remaining_seconds FLOAT, 
	deadline FLOAT, 
	sampled_at FLOAT NOT NULL, 
	duration_seconds FLOAT NOT NULL, 
	state_version INTEGER NOT NULL, 
	PRIMARY KEY (team_id), 
	CHECK (duration_seconds > 0), 
	CHECK ((accounting_mode = 'remaining' AND remaining_seconds IS NOT NULL AND remaining_seconds >= 0 AND deadline IS NULL) OR (accounting_mode = 'wall_time' AND deadline IS NOT NULL AND remaining_seconds IS NULL)), 
	CHECK (state_version > 0), 
	FOREIGN KEY(team_id) REFERENCES teams (team_id) ON DELETE RESTRICT, 
	FOREIGN KEY(event_id) REFERENCES team_topology_events (event_id) ON DELETE RESTRICT, 
	CHECK (team_id IS NULL OR length(trim(team_id)) > 0), 
	CHECK (event_id IS NULL OR length(trim(event_id)) > 0), 
	CHECK (accounting_mode IS NULL OR length(trim(accounting_mode)) > 0), 
	CHECK (remaining_seconds IS NULL OR remaining_seconds BETWEEN -1.0e308 AND 1.0e308), 
	CHECK (deadline IS NULL OR deadline BETWEEN -1.0e308 AND 1.0e308), 
	CHECK (sampled_at IS NULL OR sampled_at BETWEEN -1.0e308 AND 1.0e308), 
	CHECK (duration_seconds IS NULL OR duration_seconds BETWEEN -1.0e308 AND 1.0e308)
);

-- resource_decisions
CREATE TABLE resource_decisions (
	attempt_id VARCHAR NOT NULL, 
	agent_id VARCHAR NOT NULL, 
	decision_case_id VARCHAR, 
	scope_team_id VARCHAR, 
	exhausted_alias VARCHAR NOT NULL, 
	scope_position_revision INTEGER NOT NULL, 
	principal_agent_id VARCHAR, 
	principal_team_id VARCHAR, 
	candidates JSON NOT NULL, 
	required_tokens INTEGER NOT NULL, 
	created_at FLOAT NOT NULL, 
	deadline FLOAT NOT NULL, 
	status VARCHAR NOT NULL CHECK (status IN ('pending', 'applied', 'denied', 'expired', 'cancelled', 'interrupted', 'superseded')), 
	selected_alias VARCHAR, 
	resolved_at FLOAT, 
	state_version INTEGER NOT NULL, 
	PRIMARY KEY (attempt_id), 
	CHECK ((principal_agent_id IS NULL) <> (principal_team_id IS NULL)), 
	CHECK (scope_position_revision > 0), 
	CHECK (required_tokens > 0), 
	CHECK (deadline > created_at), 
	CHECK ((status = 'pending') = (resolved_at IS NULL)), 
	CHECK ((status = 'applied') = (selected_alias IS NOT NULL)), 
	CHECK (state_version > 0), 
	FOREIGN KEY(agent_id) REFERENCES agents (agent_id) ON DELETE RESTRICT, 
	FOREIGN KEY(decision_case_id) REFERENCES governance_cases (case_id) ON DELETE RESTRICT, 
	FOREIGN KEY(scope_team_id) REFERENCES teams (team_id) ON DELETE RESTRICT, 
	FOREIGN KEY(principal_agent_id) REFERENCES agents (agent_id) ON DELETE RESTRICT, 
	FOREIGN KEY(principal_team_id) REFERENCES teams (team_id) ON DELETE RESTRICT, 
	CHECK (attempt_id IS NULL OR length(trim(attempt_id)) > 0), 
	CHECK (agent_id IS NULL OR length(trim(agent_id)) > 0), 
	CHECK (decision_case_id IS NULL OR length(trim(decision_case_id)) > 0), 
	CHECK (scope_team_id IS NULL OR length(trim(scope_team_id)) > 0), 
	CHECK (exhausted_alias IS NULL OR length(trim(exhausted_alias)) > 0), 
	CHECK (principal_agent_id IS NULL OR length(trim(principal_agent_id)) > 0), 
	CHECK (principal_team_id IS NULL OR length(trim(principal_team_id)) > 0), 
	CHECK (created_at IS NULL OR created_at BETWEEN -1.0e308 AND 1.0e308), 
	CHECK (deadline IS NULL OR deadline BETWEEN -1.0e308 AND 1.0e308), 
	CHECK (status IS NULL OR length(trim(status)) > 0), 
	CHECK (selected_alias IS NULL OR length(trim(selected_alias)) > 0), 
	CHECK (resolved_at IS NULL OR resolved_at BETWEEN -1.0e308 AND 1.0e308)
);

-- agent_activities
CREATE TABLE agent_activities (
	agent_id VARCHAR NOT NULL, 
	intent VARCHAR NOT NULL CHECK (intent IN ('continuing', 'idle', 'sleep')), 
	availability VARCHAR NOT NULL CHECK (availability IN ('ready', 'waiting_model', 'waiting_tool', 'resource_blocked', 'unavailable', 'closing')), 
	arrival_generation INTEGER NOT NULL, 
	presentation_generation INTEGER NOT NULL, 
	context_version INTEGER NOT NULL, 
	admission_id VARCHAR, 
	state_version INTEGER NOT NULL, 
	PRIMARY KEY (agent_id), 
	CHECK (arrival_generation >= 0), 
	CHECK (presentation_generation >= 0), 
	CHECK (context_version >= 0), 
	CHECK (state_version > 0), 
	FOREIGN KEY(agent_id) REFERENCES agents (agent_id) ON DELETE RESTRICT, 
	FOREIGN KEY(admission_id) REFERENCES activity_admissions (admission_id) ON DELETE RESTRICT, 
	CHECK (agent_id IS NULL OR length(trim(agent_id)) > 0), 
	CHECK (intent IS NULL OR length(trim(intent)) > 0), 
	CHECK (availability IS NULL OR length(trim(availability)) > 0), 
	CHECK (admission_id IS NULL OR length(trim(admission_id)) > 0)
);

-- activity_admissions
CREATE TABLE activity_admissions (
	admission_id VARCHAR NOT NULL, 
	agent_id VARCHAR NOT NULL, 
	runtime_generation INTEGER NOT NULL, 
	scope_kind VARCHAR NOT NULL CHECK (scope_kind IN ('personal', 'agent_team')), 
	scope_team_id VARCHAR, 
	disposition VARCHAR NOT NULL CHECK (disposition IN ('admitted', 'completed', 'interrupted', 'cancelled')), 
	accepted_at FLOAT NOT NULL, 
	state_version INTEGER NOT NULL, 
	PRIMARY KEY (admission_id), 
	CHECK ((scope_kind = 'personal' AND scope_team_id IS NULL) OR (scope_kind = 'agent_team' AND scope_team_id IS NOT NULL)), 
	CHECK (runtime_generation > 0), 
	CHECK (state_version > 0), 
	FOREIGN KEY(agent_id) REFERENCES agents (agent_id) ON DELETE RESTRICT, 
	FOREIGN KEY(scope_team_id) REFERENCES teams (team_id) ON DELETE RESTRICT, 
	CHECK (admission_id IS NULL OR length(trim(admission_id)) > 0), 
	CHECK (agent_id IS NULL OR length(trim(agent_id)) > 0), 
	CHECK (scope_kind IS NULL OR length(trim(scope_kind)) > 0), 
	CHECK (scope_team_id IS NULL OR length(trim(scope_team_id)) > 0), 
	CHECK (disposition IS NULL OR length(trim(disposition)) > 0), 
	CHECK (accepted_at IS NULL OR accepted_at BETWEEN -1.0e308 AND 1.0e308)
);

-- activity_invocations
CREATE TABLE activity_invocations (
	invocation_id VARCHAR NOT NULL, 
	admission_id VARCHAR NOT NULL, 
	agent_id VARCHAR NOT NULL, 
	runtime_generation INTEGER NOT NULL, 
	scope_kind VARCHAR NOT NULL CHECK (scope_kind IN ('personal', 'agent_team')), 
	scope_team_id VARCHAR, 
	context_version INTEGER NOT NULL, 
	started_at FLOAT NOT NULL, 
	boundary_at FLOAT, 
	interrupted INTEGER NOT NULL CHECK (interrupted IN (0, 1)), 
	state_version INTEGER NOT NULL, 
	PRIMARY KEY (invocation_id), 
	CHECK ((scope_kind = 'personal' AND scope_team_id IS NULL) OR (scope_kind = 'agent_team' AND scope_team_id IS NOT NULL)), 
	CHECK (runtime_generation > 0), 
	CHECK (context_version >= 0), 
	CHECK (state_version > 0), 
	FOREIGN KEY(admission_id) REFERENCES activity_admissions (admission_id) ON DELETE RESTRICT, 
	FOREIGN KEY(agent_id) REFERENCES agents (agent_id) ON DELETE RESTRICT, 
	FOREIGN KEY(scope_team_id) REFERENCES teams (team_id) ON DELETE RESTRICT, 
	CHECK (invocation_id IS NULL OR length(trim(invocation_id)) > 0), 
	CHECK (admission_id IS NULL OR length(trim(admission_id)) > 0), 
	CHECK (agent_id IS NULL OR length(trim(agent_id)) > 0), 
	CHECK (scope_kind IS NULL OR length(trim(scope_kind)) > 0), 
	CHECK (scope_team_id IS NULL OR length(trim(scope_team_id)) > 0), 
	CHECK (started_at IS NULL OR started_at BETWEEN -1.0e308 AND 1.0e308), 
	CHECK (boundary_at IS NULL OR boundary_at BETWEEN -1.0e308 AND 1.0e308)
);

-- notification_frames
CREATE TABLE notification_frames (
	frame_id VARCHAR NOT NULL, 
	invocation_id VARCHAR NOT NULL, 
	agent_id VARCHAR NOT NULL, 
	context_version INTEGER NOT NULL, 
	arrival_cutoff INTEGER NOT NULL, 
	summary_references JSON NOT NULL, 
	created_version INTEGER NOT NULL, 
	PRIMARY KEY (frame_id), 
	CHECK (context_version >= 0), 
	CHECK (arrival_cutoff >= 0), 
	CHECK (created_version > 0), 
	FOREIGN KEY(invocation_id) REFERENCES activity_invocations (invocation_id) ON DELETE RESTRICT, 
	FOREIGN KEY(agent_id) REFERENCES agents (agent_id) ON DELETE RESTRICT, 
	CHECK (frame_id IS NULL OR length(trim(frame_id)) > 0), 
	CHECK (invocation_id IS NULL OR length(trim(invocation_id)) > 0), 
	CHECK (agent_id IS NULL OR length(trim(agent_id)) > 0)
);

-- model_requests
CREATE TABLE model_requests (
	model_request_id VARCHAR NOT NULL, 
	frame_id VARCHAR NOT NULL, 
	agent_id VARCHAR NOT NULL, 
	model_alias VARCHAR NOT NULL, 
	attempt_index INTEGER NOT NULL, 
	input_version INTEGER NOT NULL, 
	dispatch_state VARCHAR NOT NULL CHECK (dispatch_state IN ('unsent', 'sent', 'confirmed_unsent', 'unknown_sent')), 
	outcome VARCHAR NOT NULL CHECK (outcome IN ('pending', 'completed', 'failed', 'cancelled', 'uncertain')), 
	created_at FLOAT NOT NULL, 
	dispatched_at FLOAT, 
	earliest_retry_at FLOAT, 
	request_budget FLOAT NOT NULL, 
	sequence_budget FLOAT NOT NULL, 
	state_version INTEGER NOT NULL, 
	PRIMARY KEY (model_request_id), 
	CHECK (attempt_index > 0), 
	CHECK (input_version >= 0), 
	CHECK (request_budget > 0), 
	CHECK (sequence_budget >= request_budget), 
	CHECK (state_version > 0), 
	FOREIGN KEY(frame_id) REFERENCES notification_frames (frame_id) ON DELETE RESTRICT, 
	FOREIGN KEY(agent_id) REFERENCES agents (agent_id) ON DELETE RESTRICT, 
	CHECK (model_request_id IS NULL OR length(trim(model_request_id)) > 0), 
	CHECK (frame_id IS NULL OR length(trim(frame_id)) > 0), 
	CHECK (agent_id IS NULL OR length(trim(agent_id)) > 0), 
	CHECK (model_alias IS NULL OR length(trim(model_alias)) > 0), 
	CHECK (dispatch_state IS NULL OR length(trim(dispatch_state)) > 0), 
	CHECK (outcome IS NULL OR length(trim(outcome)) > 0), 
	CHECK (created_at IS NULL OR created_at BETWEEN -1.0e308 AND 1.0e308), 
	CHECK (dispatched_at IS NULL OR dispatched_at BETWEEN -1.0e308 AND 1.0e308), 
	CHECK (earliest_retry_at IS NULL OR earliest_retry_at BETWEEN -1.0e308 AND 1.0e308), 
	CHECK (request_budget IS NULL OR request_budget BETWEEN -1.0e308 AND 1.0e308), 
	CHECK (sequence_budget IS NULL OR sequence_budget BETWEEN -1.0e308 AND 1.0e308)
);

-- memory_index_requests
CREATE TABLE memory_index_requests (
	request_id VARCHAR NOT NULL, 
	segment_id VARCHAR NOT NULL, 
	beneficiary_agent_id VARCHAR NOT NULL, 
	source_version INTEGER NOT NULL, 
	model_alias VARCHAR NOT NULL, 
	attempt_index INTEGER NOT NULL, 
	dispatch_state VARCHAR NOT NULL CHECK (dispatch_state IN ('unsent', 'sent', 'confirmed_unsent', 'unknown_sent')), 
	outcome VARCHAR NOT NULL CHECK (outcome IN ('pending', 'completed', 'failed', 'cancelled', 'uncertain')), 
	input_digest VARCHAR NOT NULL, 
	created_at FLOAT NOT NULL, 
	dispatched_at FLOAT, 
	state_version INTEGER NOT NULL, 
	PRIMARY KEY (request_id), 
	CHECK (source_version > 0), 
	CHECK (attempt_index > 0), 
	CHECK (state_version > 0), 
	FOREIGN KEY(segment_id) REFERENCES agent_memory_segments (segment_id) ON DELETE RESTRICT, 
	FOREIGN KEY(beneficiary_agent_id) REFERENCES agents (agent_id) ON DELETE RESTRICT, 
	CHECK (request_id IS NULL OR length(trim(request_id)) > 0), 
	CHECK (segment_id IS NULL OR length(trim(segment_id)) > 0), 
	CHECK (beneficiary_agent_id IS NULL OR length(trim(beneficiary_agent_id)) > 0), 
	CHECK (model_alias IS NULL OR length(trim(model_alias)) > 0), 
	CHECK (dispatch_state IS NULL OR length(trim(dispatch_state)) > 0), 
	CHECK (outcome IS NULL OR length(trim(outcome)) > 0), 
	CHECK (input_digest IS NULL OR length(trim(input_digest)) > 0), 
	CHECK (created_at IS NULL OR created_at BETWEEN -1.0e308 AND 1.0e308), 
	CHECK (dispatched_at IS NULL OR dispatched_at BETWEEN -1.0e308 AND 1.0e308)
);

-- model_token_claims
CREATE TABLE model_token_claims (
	claim_id VARCHAR NOT NULL, 
	model_request_id VARCHAR, 
	audit_request_id VARCHAR, 
	index_request_id VARCHAR, 
	model_alias VARCHAR NOT NULL, 
	prompt_budget INTEGER NOT NULL, 
	output_budget INTEGER NOT NULL, 
	settlement VARCHAR NOT NULL CHECK (settlement IN ('reserved', 'confirmed_unsent', 'known_usage', 'unknown_sent')), 
	actual_usage INTEGER, 
	settled_at FLOAT, 
	state_version INTEGER NOT NULL, 
	PRIMARY KEY (claim_id), 
	CHECK ((model_request_id IS NOT NULL) + (audit_request_id IS NOT NULL) + (index_request_id IS NOT NULL) = 1), 
	CHECK (prompt_budget >= 0), 
	CHECK (output_budget >= 0), 
	CHECK (actual_usage IS NULL OR actual_usage >= 0), 
	CHECK ((settlement = 'reserved' AND settled_at IS NULL) OR (settlement <> 'reserved' AND settled_at IS NOT NULL)), 
	CHECK ((settlement = 'known_usage' AND actual_usage IS NOT NULL) OR (settlement <> 'known_usage' AND actual_usage IS NULL)), 
	CHECK (state_version > 0), 
	UNIQUE (model_request_id), 
	FOREIGN KEY(model_request_id) REFERENCES model_requests (model_request_id) ON DELETE RESTRICT, 
	UNIQUE (audit_request_id), 
	FOREIGN KEY(audit_request_id) REFERENCES audit_model_requests (request_id) ON DELETE RESTRICT, 
	UNIQUE (index_request_id), 
	FOREIGN KEY(index_request_id) REFERENCES memory_index_requests (request_id) ON DELETE RESTRICT, 
	CHECK (claim_id IS NULL OR length(trim(claim_id)) > 0), 
	CHECK (model_request_id IS NULL OR length(trim(model_request_id)) > 0), 
	CHECK (audit_request_id IS NULL OR length(trim(audit_request_id)) > 0), 
	CHECK (index_request_id IS NULL OR length(trim(index_request_id)) > 0), 
	CHECK (model_alias IS NULL OR length(trim(model_alias)) > 0), 
	CHECK (settlement IS NULL OR length(trim(settlement)) > 0), 
	CHECK (settled_at IS NULL OR settled_at BETWEEN -1.0e308 AND 1.0e308)
);

-- model_availability
CREATE TABLE model_availability (
	agent_id VARCHAR NOT NULL, 
	model_alias VARCHAR NOT NULL, 
	sequence_id VARCHAR NOT NULL, 
	status VARCHAR NOT NULL CHECK (status IN ('available', 'recoverable', 'remediation_required')), 
	reason VARCHAR NOT NULL, 
	request_budget FLOAT NOT NULL, 
	sequence_budget FLOAT NOT NULL, 
	earliest_admission_at FLOAT, 
	last_confirmed JSON NOT NULL, 
	state_version INTEGER NOT NULL, 
	PRIMARY KEY (agent_id, model_alias), 
	CHECK (request_budget > 0), 
	CHECK (sequence_budget >= request_budget), 
	CHECK (state_version > 0), 
	FOREIGN KEY(agent_id) REFERENCES agents (agent_id) ON DELETE RESTRICT, 
	CHECK (agent_id IS NULL OR length(trim(agent_id)) > 0), 
	CHECK (model_alias IS NULL OR length(trim(model_alias)) > 0), 
	CHECK (sequence_id IS NULL OR length(trim(sequence_id)) > 0), 
	CHECK (status IS NULL OR length(trim(status)) > 0), 
	CHECK (reason IS NULL OR length(trim(reason)) > 0), 
	CHECK (request_budget IS NULL OR request_budget BETWEEN -1.0e308 AND 1.0e308), 
	CHECK (sequence_budget IS NULL OR sequence_budget BETWEEN -1.0e308 AND 1.0e308), 
	CHECK (earliest_admission_at IS NULL OR earliest_admission_at BETWEEN -1.0e308 AND 1.0e308)
);

-- agent_notifications
CREATE TABLE agent_notifications (
	notification_id VARCHAR NOT NULL, 
	agent_id VARCHAR NOT NULL, 
	source_kind VARCHAR NOT NULL CHECK (source_kind IN ('team_message', 'direct_message', 'personal_mail', 'execution', 'system_event')), 
	chat_message_id VARCHAR, 
	mail_id VARCHAR, 
	execution_id VARCHAR, 
	system_event_id VARCHAR, 
	publication_id VARCHAR, 
	classification VARCHAR NOT NULL CHECK (classification IN ('ordinary', 'membership', 'permission', 'health', 'recovery')), 
	deduplication_key VARCHAR NOT NULL, 
	arrival_generation INTEGER NOT NULL, 
	created_at FLOAT NOT NULL, 
	created_version INTEGER NOT NULL, 
	PRIMARY KEY (notification_id), 
	UNIQUE (agent_id, deduplication_key), 
	CHECK (arrival_generation > 0), 
	CHECK ((chat_message_id IS NOT NULL) + (mail_id IS NOT NULL) + (execution_id IS NOT NULL) + (system_event_id IS NOT NULL) = 1), 
	CHECK ((source_kind IN ('team_message', 'direct_message') AND chat_message_id IS NOT NULL) OR (source_kind = 'personal_mail' AND mail_id IS NOT NULL) OR (source_kind = 'execution' AND execution_id IS NOT NULL) OR (source_kind = 'system_event' AND system_event_id IS NOT NULL)), 
	CHECK (created_version > 0), 
	FOREIGN KEY(agent_id) REFERENCES agents (agent_id) ON DELETE RESTRICT, 
	FOREIGN KEY(chat_message_id) REFERENCES chat_messages (message_id) ON DELETE RESTRICT, 
	FOREIGN KEY(mail_id) REFERENCES agent_inbox (message_id) ON DELETE RESTRICT, 
	FOREIGN KEY(execution_id) REFERENCES executions (execution_id) ON DELETE RESTRICT, 
	FOREIGN KEY(system_event_id) REFERENCES system_memory_events (event_id) ON DELETE RESTRICT, 
	FOREIGN KEY(publication_id) REFERENCES publication_manifests (publication_id) ON DELETE RESTRICT, 
	CHECK (notification_id IS NULL OR length(trim(notification_id)) > 0), 
	CHECK (agent_id IS NULL OR length(trim(agent_id)) > 0), 
	CHECK (source_kind IS NULL OR length(trim(source_kind)) > 0), 
	CHECK (chat_message_id IS NULL OR length(trim(chat_message_id)) > 0), 
	CHECK (mail_id IS NULL OR length(trim(mail_id)) > 0), 
	CHECK (execution_id IS NULL OR length(trim(execution_id)) > 0), 
	CHECK (system_event_id IS NULL OR length(trim(system_event_id)) > 0), 
	CHECK (publication_id IS NULL OR length(trim(publication_id)) > 0), 
	CHECK (classification IS NULL OR length(trim(classification)) > 0), 
	CHECK (deduplication_key IS NULL OR length(trim(deduplication_key)) > 0), 
	CHECK (created_at IS NULL OR created_at BETWEEN -1.0e308 AND 1.0e308)
);

-- notification_claims
CREATE TABLE notification_claims (
	notification_id VARCHAR NOT NULL, 
	model_request_id VARCHAR NOT NULL, 
	frame_id VARCHAR NOT NULL, 
	status VARCHAR NOT NULL CHECK (status IN ('reserved', 'dispatched', 'presented', 'uncertain')), 
	observed_at FLOAT NOT NULL, 
	state_version INTEGER NOT NULL, 
	PRIMARY KEY (notification_id, model_request_id), 
	CHECK (state_version > 0), 
	FOREIGN KEY(notification_id) REFERENCES agent_notifications (notification_id) ON DELETE RESTRICT, 
	FOREIGN KEY(model_request_id) REFERENCES model_requests (model_request_id) ON DELETE RESTRICT, 
	FOREIGN KEY(frame_id) REFERENCES notification_frames (frame_id) ON DELETE RESTRICT, 
	CHECK (notification_id IS NULL OR length(trim(notification_id)) > 0), 
	CHECK (model_request_id IS NULL OR length(trim(model_request_id)) > 0), 
	CHECK (frame_id IS NULL OR length(trim(frame_id)) > 0), 
	CHECK (status IS NULL OR length(trim(status)) > 0), 
	CHECK (observed_at IS NULL OR observed_at BETWEEN -1.0e308 AND 1.0e308)
);

-- chat_reminder_previews
CREATE TABLE chat_reminder_previews (
	notification_id VARCHAR NOT NULL, 
	agent_id VARCHAR NOT NULL, 
	revision_id VARCHAR NOT NULL, 
	preview JSON NOT NULL, 
	visibility JSON NOT NULL, 
	created_version INTEGER NOT NULL, 
	PRIMARY KEY (notification_id), 
	CHECK (created_version > 0), 
	FOREIGN KEY(notification_id) REFERENCES agent_notifications (notification_id) ON DELETE RESTRICT, 
	FOREIGN KEY(agent_id) REFERENCES agents (agent_id) ON DELETE RESTRICT, 
	FOREIGN KEY(revision_id) REFERENCES chat_revisions (revision_id) ON DELETE RESTRICT, 
	CHECK (notification_id IS NULL OR length(trim(notification_id)) > 0), 
	CHECK (agent_id IS NULL OR length(trim(agent_id)) > 0), 
	CHECK (revision_id IS NULL OR length(trim(revision_id)) > 0)
);

-- notification_suppression
CREATE TABLE notification_suppression (
	preference_id VARCHAR NOT NULL, 
	agent_id VARCHAR NOT NULL, 
	scope VARCHAR NOT NULL CHECK (scope IN ('all', 'agent', 'agent_team')), 
	source_agent_id VARCHAR, 
	source_team_id VARCHAR, 
	permanent INTEGER NOT NULL CHECK (permanent IN (0, 1)), 
	remaining_seconds FLOAT, 
	sampled_at FLOAT NOT NULL, 
	status VARCHAR NOT NULL CHECK (status IN ('active', 'expired', 'removed')), 
	duration_seconds FLOAT, 
	minimum_seconds FLOAT, 
	maximum_seconds FLOAT, 
	state_version INTEGER NOT NULL, 
	PRIMARY KEY (preference_id), 
	CHECK ((scope = 'all' AND source_agent_id IS NULL AND source_team_id IS NULL) OR (scope = 'agent' AND source_agent_id IS NOT NULL AND source_team_id IS NULL) OR (scope = 'agent_team' AND source_team_id IS NOT NULL AND source_agent_id IS NULL)), 
	CHECK ((permanent = 1 AND remaining_seconds IS NULL AND duration_seconds IS NULL AND minimum_seconds IS NULL AND maximum_seconds IS NULL) OR (permanent = 0 AND remaining_seconds IS NOT NULL AND remaining_seconds >= 0 AND duration_seconds IS NOT NULL AND minimum_seconds IS NOT NULL AND maximum_seconds IS NOT NULL AND duration_seconds BETWEEN minimum_seconds AND maximum_seconds AND minimum_seconds > 0 AND maximum_seconds >= minimum_seconds AND remaining_seconds <= duration_seconds)), 
	CHECK (permanent = 0 OR status <> 'expired'), 
	CHECK (state_version > 0), 
	FOREIGN KEY(agent_id) REFERENCES agents (agent_id) ON DELETE RESTRICT, 
	FOREIGN KEY(source_agent_id) REFERENCES agents (agent_id) ON DELETE RESTRICT, 
	FOREIGN KEY(source_team_id) REFERENCES teams (team_id) ON DELETE RESTRICT, 
	CHECK (preference_id IS NULL OR length(trim(preference_id)) > 0), 
	CHECK (agent_id IS NULL OR length(trim(agent_id)) > 0), 
	CHECK (scope IS NULL OR length(trim(scope)) > 0), 
	CHECK (source_agent_id IS NULL OR length(trim(source_agent_id)) > 0), 
	CHECK (source_team_id IS NULL OR length(trim(source_team_id)) > 0), 
	CHECK (remaining_seconds IS NULL OR remaining_seconds BETWEEN -1.0e308 AND 1.0e308), 
	CHECK (sampled_at IS NULL OR sampled_at BETWEEN -1.0e308 AND 1.0e308), 
	CHECK (status IS NULL OR length(trim(status)) > 0), 
	CHECK (duration_seconds IS NULL OR duration_seconds BETWEEN -1.0e308 AND 1.0e308), 
	CHECK (minimum_seconds IS NULL OR minimum_seconds BETWEEN -1.0e308 AND 1.0e308), 
	CHECK (maximum_seconds IS NULL OR maximum_seconds BETWEEN -1.0e308 AND 1.0e308)
);

-- notification_summary_items
CREATE TABLE notification_summary_items (
	summary_id VARCHAR NOT NULL, 
	notification_id VARCHAR NOT NULL, 
	created_version INTEGER NOT NULL, 
	PRIMARY KEY (summary_id, notification_id), 
	CHECK (summary_id <> notification_id), 
	CHECK (created_version > 0), 
	FOREIGN KEY(summary_id) REFERENCES agent_notifications (notification_id) ON DELETE RESTRICT, 
	UNIQUE (notification_id), 
	FOREIGN KEY(notification_id) REFERENCES agent_notifications (notification_id) ON DELETE RESTRICT, 
	CHECK (summary_id IS NULL OR length(trim(summary_id)) > 0), 
	CHECK (notification_id IS NULL OR length(trim(notification_id)) > 0)
);

-- sleep_plans
CREATE TABLE sleep_plans (
	sleep_id VARCHAR NOT NULL, 
	agent_id VARCHAR NOT NULL, 
	latest_wake_seconds FLOAT NOT NULL, 
	remaining_seconds FLOAT NOT NULL, 
	sampled_at FLOAT NOT NULL, 
	minimum_seconds FLOAT NOT NULL, 
	maximum_seconds FLOAT NOT NULL, 
	status VARCHAR NOT NULL CHECK (status IN ('active', 'expired', 'cancelled')), 
	state_version INTEGER NOT NULL, 
	PRIMARY KEY (sleep_id), 
	CHECK (latest_wake_seconds > 0), 
	CHECK (remaining_seconds >= 0), 
	CHECK (minimum_seconds > 0), 
	CHECK (maximum_seconds >= minimum_seconds), 
	CHECK (latest_wake_seconds BETWEEN minimum_seconds AND maximum_seconds), 
	CHECK (remaining_seconds <= latest_wake_seconds), 
	CHECK (state_version > 0), 
	FOREIGN KEY(agent_id) REFERENCES agents (agent_id) ON DELETE RESTRICT, 
	CHECK (sleep_id IS NULL OR length(trim(sleep_id)) > 0), 
	CHECK (agent_id IS NULL OR length(trim(agent_id)) > 0), 
	CHECK (latest_wake_seconds IS NULL OR latest_wake_seconds BETWEEN -1.0e308 AND 1.0e308), 
	CHECK (remaining_seconds IS NULL OR remaining_seconds BETWEEN -1.0e308 AND 1.0e308), 
	CHECK (sampled_at IS NULL OR sampled_at BETWEEN -1.0e308 AND 1.0e308), 
	CHECK (minimum_seconds IS NULL OR minimum_seconds BETWEEN -1.0e308 AND 1.0e308), 
	CHECK (maximum_seconds IS NULL OR maximum_seconds BETWEEN -1.0e308 AND 1.0e308), 
	CHECK (status IS NULL OR length(trim(status)) > 0)
);

-- sleep_conditions
CREATE TABLE sleep_conditions (
	condition_id VARCHAR NOT NULL, 
	sleep_id VARCHAR NOT NULL, 
	source_kind VARCHAR NOT NULL CHECK (source_kind IN ('agent', 'agent_team', 'execution')), 
	source_agent_id VARCHAR, 
	source_team_id VARCHAR, 
	execution_id VARCHAR, 
	admitted_generation INTEGER NOT NULL, 
	invalidated INTEGER NOT NULL CHECK (invalidated IN (0, 1)), 
	state_version INTEGER NOT NULL, 
	PRIMARY KEY (condition_id), 
	CHECK (admitted_generation > 0), 
	CHECK ((source_kind = 'agent' AND source_agent_id IS NOT NULL AND source_team_id IS NULL AND execution_id IS NULL) OR (source_kind = 'agent_team' AND source_team_id IS NOT NULL AND source_agent_id IS NULL AND execution_id IS NULL) OR (source_kind = 'execution' AND execution_id IS NOT NULL AND source_agent_id IS NULL AND source_team_id IS NULL)), 
	CHECK (state_version > 0), 
	FOREIGN KEY(sleep_id) REFERENCES sleep_plans (sleep_id) ON DELETE RESTRICT, 
	FOREIGN KEY(source_agent_id) REFERENCES agents (agent_id) ON DELETE RESTRICT, 
	FOREIGN KEY(source_team_id) REFERENCES teams (team_id) ON DELETE RESTRICT, 
	FOREIGN KEY(execution_id) REFERENCES executions (execution_id) ON DELETE RESTRICT, 
	CHECK (condition_id IS NULL OR length(trim(condition_id)) > 0), 
	CHECK (sleep_id IS NULL OR length(trim(sleep_id)) > 0), 
	CHECK (source_kind IS NULL OR length(trim(source_kind)) > 0), 
	CHECK (source_agent_id IS NULL OR length(trim(source_agent_id)) > 0), 
	CHECK (source_team_id IS NULL OR length(trim(source_team_id)) > 0), 
	CHECK (execution_id IS NULL OR length(trim(execution_id)) > 0)
);

-- direct_relationships
CREATE TABLE direct_relationships (
	relationship_id VARCHAR NOT NULL, 
	agent_a_id VARCHAR NOT NULL, 
	agent_b_id VARCHAR NOT NULL, 
	friendship INTEGER NOT NULL CHECK (friendship IN (0, 1)), 
	blocked_a INTEGER NOT NULL CHECK (blocked_a IN (0, 1)), 
	blocked_b INTEGER NOT NULL CHECK (blocked_b IN (0, 1)), 
	refused_a INTEGER NOT NULL CHECK (refused_a IN (0, 1)), 
	refused_b INTEGER NOT NULL CHECK (refused_b IN (0, 1)), 
	generation INTEGER NOT NULL, 
	allowance_a INTEGER NOT NULL, 
	allowance_b INTEGER NOT NULL, 
	state_version INTEGER NOT NULL, 
	PRIMARY KEY (relationship_id), 
	UNIQUE (agent_a_id, agent_b_id), 
	CHECK (agent_a_id < agent_b_id), 
	CHECK (generation > 0), 
	CHECK (allowance_a BETWEEN 0 AND 3), 
	CHECK (allowance_b BETWEEN 0 AND 3), 
	CHECK (state_version > 0), 
	FOREIGN KEY(agent_a_id) REFERENCES agents (agent_id) ON DELETE RESTRICT, 
	FOREIGN KEY(agent_b_id) REFERENCES agents (agent_id) ON DELETE RESTRICT, 
	CHECK (relationship_id IS NULL OR length(trim(relationship_id)) > 0), 
	CHECK (agent_a_id IS NULL OR length(trim(agent_a_id)) > 0), 
	CHECK (agent_b_id IS NULL OR length(trim(agent_b_id)) > 0)
);

-- friendship_requests
CREATE TABLE friendship_requests (
	request_id VARCHAR NOT NULL, 
	relationship_id VARCHAR NOT NULL, 
	sender_agent_id VARCHAR NOT NULL, 
	recipient_agent_id VARCHAR NOT NULL, 
	generation INTEGER NOT NULL, 
	status VARCHAR NOT NULL CHECK (status IN ('pending', 'accepted', 'rejected', 'ignored', 'cancelled', 'stale')), 
	created_at FLOAT NOT NULL, 
	responded_at FLOAT, 
	state_version INTEGER NOT NULL, 
	PRIMARY KEY (request_id), 
	CHECK (generation > 0), 
	CHECK (sender_agent_id <> recipient_agent_id), 
	CHECK (state_version > 0), 
	FOREIGN KEY(relationship_id) REFERENCES direct_relationships (relationship_id) ON DELETE RESTRICT, 
	FOREIGN KEY(sender_agent_id) REFERENCES agents (agent_id) ON DELETE RESTRICT, 
	FOREIGN KEY(recipient_agent_id) REFERENCES agents (agent_id) ON DELETE RESTRICT, 
	CHECK (request_id IS NULL OR length(trim(request_id)) > 0), 
	CHECK (relationship_id IS NULL OR length(trim(relationship_id)) > 0), 
	CHECK (sender_agent_id IS NULL OR length(trim(sender_agent_id)) > 0), 
	CHECK (recipient_agent_id IS NULL OR length(trim(recipient_agent_id)) > 0), 
	CHECK (status IS NULL OR length(trim(status)) > 0), 
	CHECK (created_at IS NULL OR created_at BETWEEN -1.0e308 AND 1.0e308), 
	CHECK (responded_at IS NULL OR responded_at BETWEEN -1.0e308 AND 1.0e308)
);

-- chat_operations
CREATE TABLE chat_operations (
	agent_id VARCHAR NOT NULL, 
	operation_key VARCHAR NOT NULL, 
	command VARCHAR NOT NULL CHECK (command IN ('send_team', 'send_direct', 'edit', 'withdraw', 'mark_message_read', 'mark_message_unread', 'delete_message', 'restore_message', 'chat_details', 'request_friendship', 'accept_friendship', 'reject_friendship', 'ignore_friendship', 'cancel_friendship_request', 'block_agent', 'unblock_agent', 'remove_friendship', 'lift_direct_refusal')), 
	request_digest VARCHAR NOT NULL, 
	result JSON NOT NULL, 
	invocation_id VARCHAR, 
	created_at FLOAT NOT NULL, 
	created_version INTEGER NOT NULL, 
	PRIMARY KEY (agent_id, operation_key), 
	CHECK (created_version > 0), 
	FOREIGN KEY(agent_id) REFERENCES agents (agent_id) ON DELETE RESTRICT, 
	FOREIGN KEY(invocation_id) REFERENCES activity_invocations (invocation_id) ON DELETE RESTRICT, 
	CHECK (agent_id IS NULL OR length(trim(agent_id)) > 0), 
	CHECK (operation_key IS NULL OR length(trim(operation_key)) > 0), 
	CHECK (command IS NULL OR length(trim(command)) > 0), 
	CHECK (request_digest IS NULL OR length(trim(request_digest)) > 0), 
	CHECK (invocation_id IS NULL OR length(trim(invocation_id)) > 0), 
	CHECK (created_at IS NULL OR created_at BETWEEN -1.0e308 AND 1.0e308)
);

-- chat_preferences
CREATE TABLE chat_preferences (
	agent_id VARCHAR NOT NULL, 
	team_details INTEGER NOT NULL CHECK (team_details IN (0, 1)), 
	direct_details INTEGER NOT NULL CHECK (direct_details IN (0, 1)), 
	state_version INTEGER NOT NULL, 
	PRIMARY KEY (agent_id), 
	CHECK (state_version > 0), 
	FOREIGN KEY(agent_id) REFERENCES agents (agent_id) ON DELETE RESTRICT, 
	CHECK (agent_id IS NULL OR length(trim(agent_id)) > 0)
);

-- chat_streams
CREATE TABLE chat_streams (
	stream_id VARCHAR NOT NULL, 
	team_id VARCHAR, 
	relationship_id VARCHAR, 
	next_position INTEGER NOT NULL, 
	state_version INTEGER NOT NULL, 
	PRIMARY KEY (stream_id), 
	CHECK ((team_id IS NULL) <> (relationship_id IS NULL)), 
	CHECK (next_position > 0), 
	CHECK (state_version > 0), 
	UNIQUE (team_id), 
	FOREIGN KEY(team_id) REFERENCES teams (team_id) ON DELETE RESTRICT, 
	UNIQUE (relationship_id), 
	FOREIGN KEY(relationship_id) REFERENCES direct_relationships (relationship_id) ON DELETE RESTRICT, 
	CHECK (stream_id IS NULL OR length(trim(stream_id)) > 0), 
	CHECK (team_id IS NULL OR length(trim(team_id)) > 0), 
	CHECK (relationship_id IS NULL OR length(trim(relationship_id)) > 0)
);

-- chat_events
CREATE TABLE chat_events (
	event_id VARCHAR NOT NULL, 
	stream_id VARCHAR NOT NULL, 
	sequence INTEGER NOT NULL, 
	event_kind VARCHAR NOT NULL CHECK (event_kind IN ('join', 'leave', 'send', 'edit', 'withdraw', 'dissolve')), 
	actor_agent_id VARCHAR, 
	created_at FLOAT NOT NULL, 
	created_version INTEGER NOT NULL, 
	PRIMARY KEY (event_id), 
	UNIQUE (stream_id, sequence), 
	CHECK (sequence > 0), 
	CHECK (created_version > 0), 
	FOREIGN KEY(stream_id) REFERENCES chat_streams (stream_id) ON DELETE RESTRICT, 
	FOREIGN KEY(actor_agent_id) REFERENCES agents (agent_id) ON DELETE RESTRICT, 
	CHECK (event_id IS NULL OR length(trim(event_id)) > 0), 
	CHECK (stream_id IS NULL OR length(trim(stream_id)) > 0), 
	CHECK (event_kind IS NULL OR length(trim(event_kind)) > 0), 
	CHECK (actor_agent_id IS NULL OR length(trim(actor_agent_id)) > 0), 
	CHECK (created_at IS NULL OR created_at BETWEEN -1.0e308 AND 1.0e308)
);

-- membership_intervals
CREATE TABLE membership_intervals (
	interval_id VARCHAR NOT NULL, 
	team_id VARCHAR NOT NULL, 
	agent_id VARCHAR NOT NULL, 
	stream_id VARCHAR NOT NULL, 
	join_event_id VARCHAR NOT NULL, 
	leave_event_id VARCHAR, 
	state_version INTEGER NOT NULL, 
	PRIMARY KEY (interval_id), 
	CHECK (state_version > 0), 
	FOREIGN KEY(team_id) REFERENCES teams (team_id) ON DELETE RESTRICT, 
	FOREIGN KEY(agent_id) REFERENCES agents (agent_id) ON DELETE RESTRICT, 
	FOREIGN KEY(stream_id) REFERENCES chat_streams (stream_id) ON DELETE RESTRICT, 
	UNIQUE (join_event_id), 
	FOREIGN KEY(join_event_id) REFERENCES chat_events (event_id) ON DELETE RESTRICT, 
	FOREIGN KEY(leave_event_id) REFERENCES chat_events (event_id) ON DELETE RESTRICT, 
	CHECK (interval_id IS NULL OR length(trim(interval_id)) > 0), 
	CHECK (team_id IS NULL OR length(trim(team_id)) > 0), 
	CHECK (agent_id IS NULL OR length(trim(agent_id)) > 0), 
	CHECK (stream_id IS NULL OR length(trim(stream_id)) > 0), 
	CHECK (join_event_id IS NULL OR length(trim(join_event_id)) > 0), 
	CHECK (leave_event_id IS NULL OR length(trim(leave_event_id)) > 0)
);

-- chat_messages
CREATE TABLE chat_messages (
	message_id VARCHAR NOT NULL, 
	stream_id VARCHAR NOT NULL, 
	author_agent_id VARCHAR NOT NULL, 
	publication_event_id VARCHAR NOT NULL, 
	invocation_id VARCHAR, 
	operation_key VARCHAR NOT NULL, 
	reply_message_id VARCHAR, 
	created_at FLOAT NOT NULL, 
	created_version INTEGER NOT NULL, 
	PRIMARY KEY (message_id), 
	UNIQUE (invocation_id, operation_key), 
	UNIQUE (author_agent_id, operation_key), 
	FOREIGN KEY(author_agent_id, operation_key) REFERENCES chat_operations (agent_id, operation_key), 
	CHECK (created_version > 0), 
	FOREIGN KEY(stream_id) REFERENCES chat_streams (stream_id) ON DELETE RESTRICT, 
	FOREIGN KEY(author_agent_id) REFERENCES agents (agent_id) ON DELETE RESTRICT, 
	UNIQUE (publication_event_id), 
	FOREIGN KEY(publication_event_id) REFERENCES chat_events (event_id) ON DELETE RESTRICT, 
	FOREIGN KEY(invocation_id) REFERENCES activity_invocations (invocation_id) ON DELETE RESTRICT, 
	FOREIGN KEY(reply_message_id) REFERENCES chat_messages (message_id) ON DELETE RESTRICT, 
	CHECK (message_id IS NULL OR length(trim(message_id)) > 0), 
	CHECK (stream_id IS NULL OR length(trim(stream_id)) > 0), 
	CHECK (author_agent_id IS NULL OR length(trim(author_agent_id)) > 0), 
	CHECK (publication_event_id IS NULL OR length(trim(publication_event_id)) > 0), 
	CHECK (invocation_id IS NULL OR length(trim(invocation_id)) > 0), 
	CHECK (operation_key IS NULL OR length(trim(operation_key)) > 0), 
	CHECK (reply_message_id IS NULL OR length(trim(reply_message_id)) > 0), 
	CHECK (created_at IS NULL OR created_at BETWEEN -1.0e308 AND 1.0e308)
);

-- chat_revisions
CREATE TABLE chat_revisions (
	revision_id VARCHAR NOT NULL, 
	message_id VARCHAR NOT NULL, 
	event_id VARCHAR NOT NULL, 
	revision_number INTEGER NOT NULL, 
	markdown JSON NOT NULL, 
	title JSON NOT NULL, 
	committed_at FLOAT NOT NULL, 
	created_version INTEGER NOT NULL, 
	PRIMARY KEY (revision_id), 
	UNIQUE (message_id, revision_number), 
	CHECK (revision_number > 0), 
	CHECK (created_version > 0), 
	FOREIGN KEY(message_id) REFERENCES chat_messages (message_id) ON DELETE RESTRICT, 
	UNIQUE (event_id), 
	FOREIGN KEY(event_id) REFERENCES chat_events (event_id) ON DELETE RESTRICT, 
	CHECK (revision_id IS NULL OR length(trim(revision_id)) > 0), 
	CHECK (message_id IS NULL OR length(trim(message_id)) > 0), 
	CHECK (event_id IS NULL OR length(trim(event_id)) > 0), 
	CHECK (committed_at IS NULL OR committed_at BETWEEN -1.0e308 AND 1.0e308)
);

-- chat_withdrawals
CREATE TABLE chat_withdrawals (
	withdrawal_id VARCHAR NOT NULL, 
	message_id VARCHAR NOT NULL, 
	revision_id VARCHAR NOT NULL, 
	actor_agent_id VARCHAR NOT NULL, 
	event_id VARCHAR NOT NULL, 
	window_seconds FLOAT NOT NULL, 
	committed_at FLOAT NOT NULL, 
	created_version INTEGER NOT NULL, 
	PRIMARY KEY (withdrawal_id), 
	CHECK (window_seconds > 0), 
	CHECK (created_version > 0), 
	UNIQUE (message_id), 
	FOREIGN KEY(message_id) REFERENCES chat_messages (message_id) ON DELETE RESTRICT, 
	FOREIGN KEY(revision_id) REFERENCES chat_revisions (revision_id) ON DELETE RESTRICT, 
	FOREIGN KEY(actor_agent_id) REFERENCES agents (agent_id) ON DELETE RESTRICT, 
	UNIQUE (event_id), 
	FOREIGN KEY(event_id) REFERENCES chat_events (event_id) ON DELETE RESTRICT, 
	CHECK (withdrawal_id IS NULL OR length(trim(withdrawal_id)) > 0), 
	CHECK (message_id IS NULL OR length(trim(message_id)) > 0), 
	CHECK (revision_id IS NULL OR length(trim(revision_id)) > 0), 
	CHECK (actor_agent_id IS NULL OR length(trim(actor_agent_id)) > 0), 
	CHECK (event_id IS NULL OR length(trim(event_id)) > 0), 
	CHECK (window_seconds IS NULL OR window_seconds BETWEEN -1.0e308 AND 1.0e308), 
	CHECK (committed_at IS NULL OR committed_at BETWEEN -1.0e308 AND 1.0e308)
);

-- chat_message_projections
CREATE TABLE chat_message_projections (
	message_id VARCHAR NOT NULL, 
	revision_id VARCHAR NOT NULL, 
	withdrawal_id VARCHAR, 
	state_version INTEGER NOT NULL, 
	PRIMARY KEY (message_id), 
	CHECK (state_version > 0), 
	FOREIGN KEY(message_id) REFERENCES chat_messages (message_id) ON DELETE RESTRICT, 
	FOREIGN KEY(revision_id) REFERENCES chat_revisions (revision_id) ON DELETE RESTRICT, 
	FOREIGN KEY(withdrawal_id) REFERENCES chat_withdrawals (withdrawal_id) ON DELETE RESTRICT, 
	CHECK (message_id IS NULL OR length(trim(message_id)) > 0), 
	CHECK (revision_id IS NULL OR length(trim(revision_id)) > 0), 
	CHECK (withdrawal_id IS NULL OR length(trim(withdrawal_id)) > 0)
);

-- chat_personal_views
CREATE TABLE chat_personal_views (
	view_id VARCHAR NOT NULL, 
	agent_id VARCHAR NOT NULL, 
	message_id VARCHAR NOT NULL, 
	interval_id VARCHAR, 
	revision_id VARCHAR NOT NULL, 
	withdrawal_id VARCHAR, 
	view_kind VARCHAR NOT NULL CHECK (view_kind IN ('live', 'frozen')), 
	departure_cutoff INTEGER, 
	read_at FLOAT, 
	read_revision_number INTEGER, 
	unread_override INTEGER NOT NULL CHECK (unread_override IN (0, 1)), 
	deleted INTEGER NOT NULL CHECK (deleted IN (0, 1)), 
	state_version INTEGER NOT NULL, 
	PRIMARY KEY (view_id), 
	UNIQUE (agent_id, message_id, interval_id), 
	CHECK ((view_kind = 'live' AND departure_cutoff IS NULL) OR (view_kind = 'frozen' AND departure_cutoff IS NOT NULL AND departure_cutoff > 0)), 
	CHECK (read_revision_number IS NULL OR read_revision_number > 0), 
	CHECK ((read_at IS NULL) = (read_revision_number IS NULL)), 
	CHECK (state_version > 0), 
	FOREIGN KEY(agent_id) REFERENCES agents (agent_id) ON DELETE RESTRICT, 
	FOREIGN KEY(message_id) REFERENCES chat_messages (message_id) ON DELETE RESTRICT, 
	FOREIGN KEY(interval_id) REFERENCES membership_intervals (interval_id) ON DELETE RESTRICT, 
	FOREIGN KEY(revision_id) REFERENCES chat_revisions (revision_id) ON DELETE RESTRICT, 
	FOREIGN KEY(withdrawal_id) REFERENCES chat_withdrawals (withdrawal_id) ON DELETE RESTRICT, 
	CHECK (view_id IS NULL OR length(trim(view_id)) > 0), 
	CHECK (agent_id IS NULL OR length(trim(agent_id)) > 0), 
	CHECK (message_id IS NULL OR length(trim(message_id)) > 0), 
	CHECK (interval_id IS NULL OR length(trim(interval_id)) > 0), 
	CHECK (revision_id IS NULL OR length(trim(revision_id)) > 0), 
	CHECK (withdrawal_id IS NULL OR length(trim(withdrawal_id)) > 0), 
	CHECK (view_kind IS NULL OR length(trim(view_kind)) > 0), 
	CHECK (read_at IS NULL OR read_at BETWEEN -1.0e308 AND 1.0e308)
);

-- executions
CREATE TABLE executions (
	execution_id VARCHAR NOT NULL, 
	agent_id VARCHAR NOT NULL, 
	invocation_id VARCHAR, 
	scope_kind VARCHAR NOT NULL CHECK (scope_kind IN ('personal', 'agent_team')), 
	scope_team_id VARCHAR, 
	tool_name VARCHAR NOT NULL, 
	effects JSON NOT NULL, 
	runtime_generation INTEGER NOT NULL, 
	visibility VARCHAR NOT NULL CHECK (visibility IN ('foreground', 'explicit_background', 'detached')), 
	status VARCHAR NOT NULL CHECK (status IN ('queued', 'running', 'completed', 'failed', 'cancelled')), 
	attention VARCHAR NOT NULL CHECK (attention IN ('none', 'required', 'acknowledged')), 
	outcome_unconfirmed INTEGER NOT NULL CHECK (outcome_unconfirmed IN (0, 1)), 
	created_at FLOAT NOT NULL, 
	call_id VARCHAR, 
	contract_snapshot JSON, 
	metadata JSON, 
	source_references JSON, 
	started_at FLOAT, 
	finished_at FLOAT, 
	state_version INTEGER NOT NULL, 
	PRIMARY KEY (execution_id), 
	CHECK ((scope_kind = 'personal' AND scope_team_id IS NULL) OR (scope_kind = 'agent_team' AND scope_team_id IS NOT NULL)), 
	CHECK (runtime_generation > 0), 
	CHECK (status NOT IN ('completed', 'failed', 'cancelled') OR outcome_unconfirmed = 0), 
	CHECK (state_version > 0), 
	FOREIGN KEY(agent_id) REFERENCES agents (agent_id) ON DELETE RESTRICT, 
	FOREIGN KEY(invocation_id) REFERENCES activity_invocations (invocation_id) ON DELETE RESTRICT, 
	FOREIGN KEY(scope_team_id) REFERENCES teams (team_id) ON DELETE RESTRICT, 
	CHECK (execution_id IS NULL OR length(trim(execution_id)) > 0), 
	CHECK (agent_id IS NULL OR length(trim(agent_id)) > 0), 
	CHECK (invocation_id IS NULL OR length(trim(invocation_id)) > 0), 
	CHECK (scope_kind IS NULL OR length(trim(scope_kind)) > 0), 
	CHECK (scope_team_id IS NULL OR length(trim(scope_team_id)) > 0), 
	CHECK (tool_name IS NULL OR length(trim(tool_name)) > 0), 
	CHECK (visibility IS NULL OR length(trim(visibility)) > 0), 
	CHECK (status IS NULL OR length(trim(status)) > 0), 
	CHECK (attention IS NULL OR length(trim(attention)) > 0), 
	CHECK (created_at IS NULL OR created_at BETWEEN -1.0e308 AND 1.0e308), 
	CHECK (call_id IS NULL OR length(trim(call_id)) > 0), 
	CHECK (started_at IS NULL OR started_at BETWEEN -1.0e308 AND 1.0e308), 
	CHECK (finished_at IS NULL OR finished_at BETWEEN -1.0e308 AND 1.0e308)
);

-- execution_attempts
CREATE TABLE execution_attempts (
	attempt_id VARCHAR NOT NULL, 
	execution_id VARCHAR NOT NULL, 
	attempt_index INTEGER NOT NULL, 
	retry_contract JSON NOT NULL, 
	started_at FLOAT, 
	dispatched INTEGER NOT NULL CHECK (dispatched IN (0, 1)), 
	external_handle VARCHAR, 
	created_version INTEGER NOT NULL, 
	PRIMARY KEY (attempt_id), 
	UNIQUE (execution_id, attempt_index), 
	CHECK (attempt_index > 0), 
	CHECK (dispatched = 0 OR started_at IS NOT NULL), 
	CHECK (created_version > 0), 
	FOREIGN KEY(execution_id) REFERENCES executions (execution_id) ON DELETE RESTRICT, 
	CHECK (attempt_id IS NULL OR length(trim(attempt_id)) > 0), 
	CHECK (execution_id IS NULL OR length(trim(execution_id)) > 0), 
	CHECK (started_at IS NULL OR started_at BETWEEN -1.0e308 AND 1.0e308), 
	CHECK (external_handle IS NULL OR length(trim(external_handle)) > 0)
);

-- execution_payloads
CREATE TABLE execution_payloads (
	payload_id VARCHAR NOT NULL, 
	agent_id VARCHAR NOT NULL, 
	execution_id VARCHAR NOT NULL, 
	content_kind VARCHAR NOT NULL CHECK (content_kind IN ('input', 'result')), 
	content JSON NOT NULL, 
	digest VARCHAR NOT NULL, 
	created_version INTEGER NOT NULL, 
	PRIMARY KEY (payload_id), 
	UNIQUE (execution_id, content_kind), 
	CHECK (created_version > 0), 
	FOREIGN KEY(agent_id) REFERENCES agents (agent_id) ON DELETE RESTRICT, 
	FOREIGN KEY(execution_id) REFERENCES executions (execution_id) ON DELETE RESTRICT, 
	CHECK (payload_id IS NULL OR length(trim(payload_id)) > 0), 
	CHECK (agent_id IS NULL OR length(trim(agent_id)) > 0), 
	CHECK (execution_id IS NULL OR length(trim(execution_id)) > 0), 
	CHECK (content_kind IS NULL OR length(trim(content_kind)) > 0), 
	CHECK (digest IS NULL OR length(trim(digest)) > 0)
);

-- execution_observations
CREATE TABLE execution_observations (
	observation_id VARCHAR NOT NULL, 
	execution_id VARCHAR NOT NULL, 
	attempt_id VARCHAR, 
	health VARCHAR NOT NULL CHECK (health IN ('healthy', 'degraded', 'stalled', 'error', 'unknown')), 
	evidence_kind VARCHAR NOT NULL, 
	evidence JSON NOT NULL, 
	observed_at FLOAT NOT NULL, 
	uncertain INTEGER NOT NULL CHECK (uncertain IN (0, 1)), 
	observation_index INTEGER, 
	created_version INTEGER NOT NULL, 
	PRIMARY KEY (observation_id), 
	UNIQUE (execution_id, observation_index), 
	CHECK (observation_index IS NULL OR observation_index > 0), 
	CHECK (created_version > 0), 
	FOREIGN KEY(execution_id) REFERENCES executions (execution_id) ON DELETE RESTRICT, 
	FOREIGN KEY(attempt_id) REFERENCES execution_attempts (attempt_id) ON DELETE RESTRICT, 
	CHECK (observation_id IS NULL OR length(trim(observation_id)) > 0), 
	CHECK (execution_id IS NULL OR length(trim(execution_id)) > 0), 
	CHECK (attempt_id IS NULL OR length(trim(attempt_id)) > 0), 
	CHECK (health IS NULL OR length(trim(health)) > 0), 
	CHECK (evidence_kind IS NULL OR length(trim(evidence_kind)) > 0), 
	CHECK (observed_at IS NULL OR observed_at BETWEEN -1.0e308 AND 1.0e308)
);

-- execution_controls
CREATE TABLE execution_controls (
	control_id VARCHAR NOT NULL, 
	execution_id VARCHAR NOT NULL, 
	requester_agent_id VARCHAR NOT NULL, 
	operation VARCHAR NOT NULL CHECK (operation IN ('stop', 'suspend')), 
	acknowledgement VARCHAR NOT NULL CHECK (acknowledgement IN ('requested', 'acknowledged', 'unsupported', 'uncertain')), 
	requested_at FLOAT NOT NULL, 
	acknowledged_at FLOAT, 
	outcome_race JSON NOT NULL, 
	state_version INTEGER NOT NULL, 
	PRIMARY KEY (control_id), 
	CHECK (state_version > 0), 
	FOREIGN KEY(execution_id) REFERENCES executions (execution_id) ON DELETE RESTRICT, 
	FOREIGN KEY(requester_agent_id) REFERENCES agents (agent_id) ON DELETE RESTRICT, 
	CHECK (control_id IS NULL OR length(trim(control_id)) > 0), 
	CHECK (execution_id IS NULL OR length(trim(execution_id)) > 0), 
	CHECK (requester_agent_id IS NULL OR length(trim(requester_agent_id)) > 0), 
	CHECK (operation IS NULL OR length(trim(operation)) > 0), 
	CHECK (acknowledgement IS NULL OR length(trim(acknowledgement)) > 0), 
	CHECK (requested_at IS NULL OR requested_at BETWEEN -1.0e308 AND 1.0e308), 
	CHECK (acknowledged_at IS NULL OR acknowledged_at BETWEEN -1.0e308 AND 1.0e308)
);

-- tool_cooldowns
CREATE TABLE tool_cooldowns (
	agent_id VARCHAR NOT NULL, 
	tool_name VARCHAR NOT NULL, 
	fault_id VARCHAR NOT NULL, 
	accounting_mode VARCHAR NOT NULL CHECK (accounting_mode IN ('remaining', 'wall_time')), 
	remaining_seconds FLOAT, 
	deadline FLOAT, 
	sampled_at FLOAT NOT NULL, 
	state_version INTEGER NOT NULL, 
	PRIMARY KEY (agent_id, tool_name), 
	CHECK ((accounting_mode = 'remaining' AND remaining_seconds IS NOT NULL AND remaining_seconds >= 0 AND deadline IS NULL) OR (accounting_mode = 'wall_time' AND deadline IS NOT NULL AND remaining_seconds IS NULL)), 
	CHECK (state_version > 0), 
	FOREIGN KEY(agent_id) REFERENCES agents (agent_id) ON DELETE RESTRICT, 
	CHECK (agent_id IS NULL OR length(trim(agent_id)) > 0), 
	CHECK (tool_name IS NULL OR length(trim(tool_name)) > 0), 
	CHECK (fault_id IS NULL OR length(trim(fault_id)) > 0), 
	CHECK (accounting_mode IS NULL OR length(trim(accounting_mode)) > 0), 
	CHECK (remaining_seconds IS NULL OR remaining_seconds BETWEEN -1.0e308 AND 1.0e308), 
	CHECK (deadline IS NULL OR deadline BETWEEN -1.0e308 AND 1.0e308), 
	CHECK (sampled_at IS NULL OR sampled_at BETWEEN -1.0e308 AND 1.0e308)
);

-- health_incidents
CREATE TABLE health_incidents (
	incident_id VARCHAR NOT NULL, 
	subject_agent_id VARCHAR, 
	subject_team_id VARCHAR, 
	subject_att_id VARCHAR, 
	fingerprint VARCHAR NOT NULL, 
	occurrence_count INTEGER NOT NULL, 
	first_at FLOAT NOT NULL, 
	latest_at FLOAT NOT NULL, 
	evidence JSON NOT NULL, 
	status VARCHAR NOT NULL CHECK (status IN ('pending', 'claimed', 'acknowledged')), 
	state_version INTEGER NOT NULL, 
	PRIMARY KEY (incident_id), 
	UNIQUE (subject_agent_id, fingerprint), 
	UNIQUE (subject_team_id, fingerprint), 
	UNIQUE (subject_att_id, fingerprint), 
	CHECK ((subject_agent_id IS NOT NULL) + (subject_team_id IS NOT NULL) + (subject_att_id IS NOT NULL) = 1), 
	CHECK (subject_att_id IS NULL OR subject_att_id = 'ATT'), 
	CHECK (occurrence_count > 0), 
	CHECK (latest_at >= first_at), 
	CHECK (state_version > 0), 
	FOREIGN KEY(subject_agent_id) REFERENCES agents (agent_id) ON DELETE RESTRICT, 
	FOREIGN KEY(subject_team_id) REFERENCES teams (team_id) ON DELETE RESTRICT, 
	CHECK (incident_id IS NULL OR length(trim(incident_id)) > 0), 
	CHECK (subject_agent_id IS NULL OR length(trim(subject_agent_id)) > 0), 
	CHECK (subject_team_id IS NULL OR length(trim(subject_team_id)) > 0), 
	CHECK (subject_att_id IS NULL OR length(trim(subject_att_id)) > 0), 
	CHECK (fingerprint IS NULL OR length(trim(fingerprint)) > 0), 
	CHECK (first_at IS NULL OR first_at BETWEEN -1.0e308 AND 1.0e308), 
	CHECK (latest_at IS NULL OR latest_at BETWEEN -1.0e308 AND 1.0e308), 
	CHECK (status IS NULL OR length(trim(status)) > 0)
);

-- health_observations
CREATE TABLE health_observations (
	observation_id VARCHAR NOT NULL, 
	agent_id VARCHAR NOT NULL, 
	detector VARCHAR NOT NULL CHECK (detector IN ('model_protocol', 'tool_arguments', 'semantic')), 
	tool_name VARCHAR, 
	error_kind VARCHAR, 
	valid INTEGER NOT NULL CHECK (valid IN (0, 1)), 
	observed_at FLOAT NOT NULL, 
	source_id VARCHAR NOT NULL, 
	created_version INTEGER NOT NULL, 
	PRIMARY KEY (observation_id), 
	CHECK (created_version > 0), 
	FOREIGN KEY(agent_id) REFERENCES agents (agent_id) ON DELETE RESTRICT, 
	CHECK (observation_id IS NULL OR length(trim(observation_id)) > 0), 
	CHECK (agent_id IS NULL OR length(trim(agent_id)) > 0), 
	CHECK (detector IS NULL OR length(trim(detector)) > 0), 
	CHECK (tool_name IS NULL OR length(trim(tool_name)) > 0), 
	CHECK (error_kind IS NULL OR length(trim(error_kind)) > 0), 
	CHECK (observed_at IS NULL OR observed_at BETWEEN -1.0e308 AND 1.0e308), 
	CHECK (source_id IS NULL OR length(trim(source_id)) > 0)
);

-- health_detector_states
CREATE TABLE health_detector_states (
	agent_id VARCHAR NOT NULL, 
	detector VARCHAR NOT NULL, 
	tool_key VARCHAR NOT NULL, 
	error_kind VARCHAR, 
	samples JSON NOT NULL, 
	observation_ids JSON NOT NULL, 
	last_assessed_id VARCHAR, 
	state_version INTEGER NOT NULL, 
	PRIMARY KEY (agent_id, detector, tool_key), 
	CHECK (detector IN ('model_protocol', 'tool_arguments', 'semantic')), 
	CHECK (state_version > 0), 
	FOREIGN KEY(agent_id) REFERENCES agents (agent_id) ON DELETE RESTRICT, 
	CHECK (agent_id IS NULL OR length(trim(agent_id)) > 0), 
	CHECK (detector IS NULL OR length(trim(detector)) > 0), 
	CHECK (tool_key IS NULL OR length(trim(tool_key)) > 0), 
	CHECK (error_kind IS NULL OR length(trim(error_kind)) > 0), 
	CHECK (last_assessed_id IS NULL OR length(trim(last_assessed_id)) > 0)
);

-- health_incident_events
CREATE TABLE health_incident_events (
	event_id VARCHAR NOT NULL, 
	incident_id VARCHAR NOT NULL, 
	event_kind VARCHAR NOT NULL CHECK (event_kind IN ('occurrence', 'claimed', 'acknowledged', 'released', 'cleared')), 
	occurrence_count INTEGER NOT NULL, 
	actor_agent_id VARCHAR, 
	details JSON NOT NULL, 
	created_at FLOAT NOT NULL, 
	created_version INTEGER NOT NULL, 
	PRIMARY KEY (event_id), 
	CHECK (occurrence_count > 0), 
	CHECK (created_version > 0), 
	FOREIGN KEY(incident_id) REFERENCES health_incidents (incident_id) ON DELETE RESTRICT, 
	FOREIGN KEY(actor_agent_id) REFERENCES agents (agent_id) ON DELETE RESTRICT, 
	CHECK (event_id IS NULL OR length(trim(event_id)) > 0), 
	CHECK (incident_id IS NULL OR length(trim(incident_id)) > 0), 
	CHECK (event_kind IS NULL OR length(trim(event_kind)) > 0), 
	CHECK (actor_agent_id IS NULL OR length(trim(actor_agent_id)) > 0), 
	CHECK (created_at IS NULL OR created_at BETWEEN -1.0e308 AND 1.0e308)
);

-- audit_runs
CREATE TABLE audit_runs (
	audit_id VARCHAR NOT NULL, 
	subject_agent_id VARCHAR, 
	subject_team_id VARCHAR, 
	subject_att_id VARCHAR, 
	temporary_team_id VARCHAR NOT NULL, 
	template JSON NOT NULL, 
	electorate JSON NOT NULL, 
	runtime_generation INTEGER NOT NULL, 
	status VARCHAR NOT NULL CHECK (status IN ('prepared', 'running', 'completed', 'interrupted', 'unknown')), 
	created_at FLOAT NOT NULL, 
	deadline FLOAT NOT NULL, 
	token_budget INTEGER NOT NULL, 
	state_version INTEGER NOT NULL, 
	PRIMARY KEY (audit_id), 
	CHECK ((subject_agent_id IS NOT NULL) + (subject_team_id IS NOT NULL) + (subject_att_id IS NOT NULL) = 1), 
	CHECK (subject_att_id IS NULL OR subject_att_id = 'ATT'), 
	CHECK (runtime_generation > 0), 
	CHECK (token_budget >= 0), 
	CHECK (deadline >= created_at), 
	CHECK (state_version > 0), 
	FOREIGN KEY(subject_agent_id) REFERENCES agents (agent_id) ON DELETE RESTRICT, 
	FOREIGN KEY(subject_team_id) REFERENCES teams (team_id) ON DELETE RESTRICT, 
	CHECK (audit_id IS NULL OR length(trim(audit_id)) > 0), 
	CHECK (subject_agent_id IS NULL OR length(trim(subject_agent_id)) > 0), 
	CHECK (subject_team_id IS NULL OR length(trim(subject_team_id)) > 0), 
	CHECK (subject_att_id IS NULL OR length(trim(subject_att_id)) > 0), 
	CHECK (temporary_team_id IS NULL OR length(trim(temporary_team_id)) > 0), 
	CHECK (status IS NULL OR length(trim(status)) > 0), 
	CHECK (created_at IS NULL OR created_at BETWEEN -1.0e308 AND 1.0e308), 
	CHECK (deadline IS NULL OR deadline BETWEEN -1.0e308 AND 1.0e308)
);

-- audit_participants
CREATE TABLE audit_participants (
	audit_id VARCHAR NOT NULL, 
	scoped_agent_id VARCHAR NOT NULL, 
	identity_snapshot JSON NOT NULL, 
	model_alias VARCHAR NOT NULL, 
	position INTEGER NOT NULL, 
	created_version INTEGER NOT NULL, 
	PRIMARY KEY (audit_id, scoped_agent_id), 
	UNIQUE (audit_id, position), 
	CHECK (position >= 0), 
	CHECK (created_version > 0), 
	FOREIGN KEY(audit_id) REFERENCES audit_runs (audit_id) ON DELETE RESTRICT, 
	CHECK (audit_id IS NULL OR length(trim(audit_id)) > 0), 
	CHECK (scoped_agent_id IS NULL OR length(trim(scoped_agent_id)) > 0), 
	CHECK (model_alias IS NULL OR length(trim(model_alias)) > 0)
);

-- audit_activity_checkpoints
CREATE TABLE audit_activity_checkpoints (
	checkpoint_id VARCHAR NOT NULL, 
	audit_id VARCHAR NOT NULL, 
	scoped_agent_id VARCHAR NOT NULL, 
	invocation_id VARCHAR NOT NULL, 
	context_version INTEGER NOT NULL, 
	working_context JSON NOT NULL, 
	intent VARCHAR NOT NULL CHECK (intent IN ('continuing', 'idle')), 
	interrupted INTEGER NOT NULL CHECK (interrupted IN (0, 1)), 
	created_at FLOAT NOT NULL, 
	created_version INTEGER NOT NULL, 
	PRIMARY KEY (checkpoint_id), 
	FOREIGN KEY(audit_id, scoped_agent_id) REFERENCES audit_participants (audit_id, scoped_agent_id) ON DELETE RESTRICT, 
	CHECK (context_version >= 0), 
	CHECK (created_version > 0), 
	CHECK (checkpoint_id IS NULL OR length(trim(checkpoint_id)) > 0), 
	CHECK (audit_id IS NULL OR length(trim(audit_id)) > 0), 
	CHECK (scoped_agent_id IS NULL OR length(trim(scoped_agent_id)) > 0), 
	CHECK (invocation_id IS NULL OR length(trim(invocation_id)) > 0), 
	CHECK (intent IS NULL OR length(trim(intent)) > 0), 
	CHECK (created_at IS NULL OR created_at BETWEEN -1.0e308 AND 1.0e308)
);

-- audit_findings
CREATE TABLE audit_findings (
	audit_id VARCHAR NOT NULL, 
	scoped_agent_id VARCHAR NOT NULL, 
	status VARCHAR NOT NULL CHECK (status IN ('healthy', 'unhealthy', 'unknown')), 
	reason VARCHAR NOT NULL, 
	operational_status VARCHAR NOT NULL CHECK (operational_status IN ('healthy', 'degraded', 'unknown')), 
	operational_reason VARCHAR NOT NULL, 
	evidence_references JSON NOT NULL, 
	created_at FLOAT NOT NULL, 
	created_version INTEGER NOT NULL, 
	PRIMARY KEY (audit_id, scoped_agent_id), 
	FOREIGN KEY(audit_id, scoped_agent_id) REFERENCES audit_participants (audit_id, scoped_agent_id) ON DELETE RESTRICT, 
	CHECK (created_version > 0), 
	CHECK (audit_id IS NULL OR length(trim(audit_id)) > 0), 
	CHECK (scoped_agent_id IS NULL OR length(trim(scoped_agent_id)) > 0), 
	CHECK (status IS NULL OR length(trim(status)) > 0), 
	CHECK (reason IS NULL OR length(trim(reason)) > 0), 
	CHECK (operational_status IS NULL OR length(trim(operational_status)) > 0), 
	CHECK (operational_reason IS NULL OR length(trim(operational_reason)) > 0), 
	CHECK (created_at IS NULL OR created_at BETWEEN -1.0e308 AND 1.0e308)
);

-- audit_model_requests
CREATE TABLE audit_model_requests (
	request_id VARCHAR NOT NULL, 
	audit_id VARCHAR NOT NULL, 
	scoped_agent_id VARCHAR NOT NULL, 
	invocation_id VARCHAR NOT NULL, 
	frame_id VARCHAR NOT NULL, 
	input_version INTEGER NOT NULL, 
	model_alias VARCHAR NOT NULL, 
	attempt_index INTEGER NOT NULL, 
	dispatch_state VARCHAR NOT NULL CHECK (dispatch_state IN ('unsent', 'sent', 'confirmed_unsent', 'unknown_sent')), 
	outcome VARCHAR NOT NULL CHECK (outcome IN ('pending', 'completed', 'failed', 'cancelled', 'uncertain')), 
	created_at FLOAT NOT NULL, 
	dispatched_at FLOAT, 
	request_budget FLOAT NOT NULL, 
	sequence_budget FLOAT NOT NULL, 
	state_version INTEGER NOT NULL, 
	PRIMARY KEY (request_id), 
	FOREIGN KEY(audit_id, scoped_agent_id) REFERENCES audit_participants (audit_id, scoped_agent_id) ON DELETE RESTRICT, 
	CHECK (input_version >= 0), 
	CHECK (attempt_index > 0), 
	CHECK (request_budget > 0), 
	CHECK (sequence_budget >= request_budget), 
	CHECK (state_version > 0), 
	CHECK (request_id IS NULL OR length(trim(request_id)) > 0), 
	CHECK (audit_id IS NULL OR length(trim(audit_id)) > 0), 
	CHECK (scoped_agent_id IS NULL OR length(trim(scoped_agent_id)) > 0), 
	CHECK (invocation_id IS NULL OR length(trim(invocation_id)) > 0), 
	CHECK (frame_id IS NULL OR length(trim(frame_id)) > 0), 
	CHECK (model_alias IS NULL OR length(trim(model_alias)) > 0), 
	CHECK (dispatch_state IS NULL OR length(trim(dispatch_state)) > 0), 
	CHECK (outcome IS NULL OR length(trim(outcome)) > 0), 
	CHECK (created_at IS NULL OR created_at BETWEEN -1.0e308 AND 1.0e308), 
	CHECK (dispatched_at IS NULL OR dispatched_at BETWEEN -1.0e308 AND 1.0e308), 
	CHECK (request_budget IS NULL OR request_budget BETWEEN -1.0e308 AND 1.0e308), 
	CHECK (sequence_budget IS NULL OR sequence_budget BETWEEN -1.0e308 AND 1.0e308)
);

-- audit_execution_evidence
CREATE TABLE audit_execution_evidence (
	execution_id VARCHAR NOT NULL, 
	audit_id VARCHAR NOT NULL, 
	scoped_agent_id VARCHAR NOT NULL, 
	tool_name VARCHAR NOT NULL, 
	effects JSON NOT NULL, 
	attempt_index INTEGER NOT NULL, 
	runtime_generation INTEGER NOT NULL, 
	status VARCHAR NOT NULL CHECK (status IN ('queued', 'running', 'completed', 'failed', 'cancelled')), 
	health VARCHAR NOT NULL CHECK (health IN ('healthy', 'degraded', 'stalled', 'error', 'unknown')), 
	attention VARCHAR NOT NULL CHECK (attention IN ('none', 'required', 'acknowledged')), 
	sanitized_result JSON NOT NULL, 
	outcome_unconfirmed INTEGER NOT NULL CHECK (outcome_unconfirmed IN (0, 1)), 
	state_version INTEGER NOT NULL, 
	PRIMARY KEY (execution_id), 
	FOREIGN KEY(audit_id, scoped_agent_id) REFERENCES audit_participants (audit_id, scoped_agent_id) ON DELETE RESTRICT, 
	CHECK (attempt_index > 0), 
	CHECK (runtime_generation > 0), 
	CHECK (state_version > 0), 
	CHECK (execution_id IS NULL OR length(trim(execution_id)) > 0), 
	CHECK (audit_id IS NULL OR length(trim(audit_id)) > 0), 
	CHECK (scoped_agent_id IS NULL OR length(trim(scoped_agent_id)) > 0), 
	CHECK (tool_name IS NULL OR length(trim(tool_name)) > 0), 
	CHECK (status IS NULL OR length(trim(status)) > 0), 
	CHECK (health IS NULL OR length(trim(health)) > 0), 
	CHECK (attention IS NULL OR length(trim(attention)) > 0)
);

-- audit_chat_evidence
CREATE TABLE audit_chat_evidence (
	event_id VARCHAR NOT NULL, 
	audit_id VARCHAR NOT NULL, 
	scoped_agent_id VARCHAR NOT NULL, 
	sequence INTEGER NOT NULL, 
	event_kind VARCHAR NOT NULL CHECK (event_kind IN ('send', 'edit', 'withdraw')), 
	findings JSON NOT NULL, 
	created_at FLOAT NOT NULL, 
	created_version INTEGER NOT NULL, 
	PRIMARY KEY (event_id), 
	FOREIGN KEY(audit_id, scoped_agent_id) REFERENCES audit_participants (audit_id, scoped_agent_id) ON DELETE RESTRICT, 
	UNIQUE (audit_id, sequence), 
	CHECK (sequence > 0), 
	CHECK (created_version > 0), 
	CHECK (event_id IS NULL OR length(trim(event_id)) > 0), 
	CHECK (audit_id IS NULL OR length(trim(audit_id)) > 0), 
	CHECK (scoped_agent_id IS NULL OR length(trim(scoped_agent_id)) > 0), 
	CHECK (event_kind IS NULL OR length(trim(event_kind)) > 0), 
	CHECK (created_at IS NULL OR created_at BETWEEN -1.0e308 AND 1.0e308)
);

-- audit_evidence
CREATE TABLE audit_evidence (
	audit_id VARCHAR NOT NULL, 
	evidence_references JSON NOT NULL, 
	findings JSON NOT NULL, 
	result VARCHAR NOT NULL CHECK (result IN ('healthy', 'unhealthy', 'unknown')), 
	identity_snapshots JSON NOT NULL, 
	created_at FLOAT NOT NULL, 
	created_version INTEGER NOT NULL, 
	PRIMARY KEY (audit_id), 
	CHECK (created_version > 0), 
	FOREIGN KEY(audit_id) REFERENCES audit_runs (audit_id) ON DELETE RESTRICT, 
	CHECK (audit_id IS NULL OR length(trim(audit_id)) > 0), 
	CHECK (result IS NULL OR length(trim(result)) > 0), 
	CHECK (created_at IS NULL OR created_at BETWEEN -1.0e308 AND 1.0e308)
);

-- system_memory_events
CREATE TABLE system_memory_events (
	event_id VARCHAR NOT NULL, 
	sequence INTEGER NOT NULL, 
	event_type VARCHAR NOT NULL, 
	agent_id VARCHAR, 
	agent_name_snapshot VARCHAR, 
	team_id VARCHAR, 
	invocation_id VARCHAR, 
	source_chat_message_id VARCHAR, 
	source_execution_id VARCHAR, 
	role VARCHAR, 
	payload JSON NOT NULL, 
	redacted INTEGER NOT NULL, 
	created_at FLOAT NOT NULL, 
	PRIMARY KEY (event_id), 
	UNIQUE (sequence), 
	FOREIGN KEY(source_chat_message_id) REFERENCES chat_messages (message_id) ON DELETE RESTRICT, 
	FOREIGN KEY(source_execution_id) REFERENCES executions (execution_id) ON DELETE RESTRICT
);

-- agent_memory_segments
CREATE TABLE agent_memory_segments (
	segment_id VARCHAR NOT NULL, 
	agent_id VARCHAR NOT NULL, 
	invocation_id VARCHAR NOT NULL, 
	origin_team_id VARCHAR, 
	recall_content VARCHAR NOT NULL, 
	content_sha256 VARCHAR NOT NULL, 
	status VARCHAR NOT NULL, 
	attempts INTEGER NOT NULL, 
	last_error_kind VARCHAR, 
	created_at FLOAT NOT NULL, 
	updated_at FLOAT NOT NULL, 
	PRIMARY KEY (segment_id), 
	CONSTRAINT ck_memory_segment_status CHECK (status IN ('pending', 'processing', 'indexed', 'failed')), 
	FOREIGN KEY(agent_id) REFERENCES agents (agent_id) ON DELETE RESTRICT, 
	UNIQUE (invocation_id), 
	FOREIGN KEY(invocation_id) REFERENCES activity_invocations (invocation_id) ON DELETE RESTRICT
);

-- agent_memory_cards
CREATE TABLE agent_memory_cards (
	memory_id VARCHAR NOT NULL, 
	agent_id VARCHAR NOT NULL, 
	invocation_id VARCHAR NOT NULL, 
	title VARCHAR NOT NULL, 
	summary VARCHAR NOT NULL, 
	origin_team_id VARCHAR, 
	segment_id VARCHAR NOT NULL, 
	status VARCHAR NOT NULL, 
	version INTEGER NOT NULL, 
	created_at FLOAT NOT NULL, 
	updated_at FLOAT NOT NULL, 
	PRIMARY KEY (memory_id), 
	CONSTRAINT ck_memory_card_status CHECK (status IN ('active', 'forgotten')), 
	FOREIGN KEY(agent_id) REFERENCES agents (agent_id) ON DELETE RESTRICT, 
	UNIQUE (invocation_id), 
	FOREIGN KEY(invocation_id) REFERENCES activity_invocations (invocation_id) ON DELETE RESTRICT, 
	UNIQUE (segment_id), 
	FOREIGN KEY(segment_id) REFERENCES agent_memory_segments (segment_id) ON DELETE CASCADE
);

-- memory_card_tags
CREATE TABLE memory_card_tags (
	memory_id VARCHAR NOT NULL, 
	tag VARCHAR NOT NULL, 
	sequence INTEGER NOT NULL, 
	PRIMARY KEY (memory_id, tag), 
	CONSTRAINT uq_memory_card_tag_sequence UNIQUE (memory_id, sequence), 
	FOREIGN KEY(memory_id) REFERENCES agent_memory_cards (memory_id) ON DELETE CASCADE
);

-- memory_card_source_events
CREATE TABLE memory_card_source_events (
	segment_id VARCHAR NOT NULL, 
	event_id VARCHAR NOT NULL, 
	sequence INTEGER NOT NULL, 
	PRIMARY KEY (segment_id, event_id), 
	CONSTRAINT uq_memory_card_source_sequence UNIQUE (segment_id, sequence), 
	FOREIGN KEY(segment_id) REFERENCES agent_memory_segments (segment_id) ON DELETE CASCADE, 
	FOREIGN KEY(event_id) REFERENCES system_memory_events (event_id) ON DELETE RESTRICT
);

-- retained_memory_references
CREATE TABLE retained_memory_references (
	reference_id VARCHAR NOT NULL, 
	agent_id VARCHAR NOT NULL, 
	memory_id VARCHAR NOT NULL, 
	note VARCHAR NOT NULL, 
	created_at FLOAT NOT NULL, 
	PRIMARY KEY (reference_id), 
	FOREIGN KEY(agent_id) REFERENCES agents (agent_id) ON DELETE CASCADE, 
	FOREIGN KEY(memory_id) REFERENCES agent_memory_cards (memory_id) ON DELETE CASCADE
);

-- commit_receipts
CREATE TABLE commit_receipts (
	operation_id VARCHAR NOT NULL, 
	state_version INTEGER NOT NULL, 
	dependencies JSON NOT NULL, 
	digest VARCHAR NOT NULL, 
	record_digest VARCHAR, 
	PRIMARY KEY (operation_id), 
	CHECK (length(trim(operation_id)) > 0 AND state_version > 0)
);

-- recovery_incidents
CREATE TABLE recovery_incidents (
	incident_id VARCHAR NOT NULL, 
	agent_id VARCHAR NOT NULL, 
	checkpoint_id VARCHAR NOT NULL, 
	publication_id VARCHAR, 
	invocation_id VARCHAR, 
	execution_id VARCHAR, 
	affected_identity VARCHAR NOT NULL, 
	last_confirmed JSON NOT NULL, 
	uncertain INTEGER NOT NULL CHECK (uncertain IN (0, 1)), 
	created_at FLOAT NOT NULL, 
	created_version INTEGER NOT NULL, 
	PRIMARY KEY (incident_id), 
	UNIQUE (checkpoint_id, agent_id, affected_identity), 
	CHECK (created_version > 0), 
	FOREIGN KEY(agent_id) REFERENCES agents (agent_id) ON DELETE RESTRICT, 
	FOREIGN KEY(publication_id) REFERENCES publication_manifests (publication_id) ON DELETE RESTRICT, 
	FOREIGN KEY(invocation_id) REFERENCES activity_invocations (invocation_id) ON DELETE RESTRICT, 
	FOREIGN KEY(execution_id) REFERENCES executions (execution_id) ON DELETE RESTRICT, 
	CHECK (incident_id IS NULL OR length(trim(incident_id)) > 0), 
	CHECK (agent_id IS NULL OR length(trim(agent_id)) > 0), 
	CHECK (checkpoint_id IS NULL OR length(trim(checkpoint_id)) > 0), 
	CHECK (publication_id IS NULL OR length(trim(publication_id)) > 0), 
	CHECK (invocation_id IS NULL OR length(trim(invocation_id)) > 0), 
	CHECK (execution_id IS NULL OR length(trim(execution_id)) > 0), 
	CHECK (affected_identity IS NULL OR length(trim(affected_identity)) > 0), 
	CHECK (created_at IS NULL OR created_at BETWEEN -1.0e308 AND 1.0e308)
);

-- publication_manifests
CREATE TABLE publication_manifests (
	publication_id VARCHAR NOT NULL, 
	checkpoint_id VARCHAR NOT NULL, 
	previous_generation INTEGER NOT NULL, 
	target_generation INTEGER NOT NULL, 
	staged_files JSON NOT NULL, 
	recovery_operation_id VARCHAR NOT NULL, 
	status VARCHAR NOT NULL CHECK (status IN ('prepared', 'published', 'rolled_back')), 
	prepared_at FLOAT NOT NULL, 
	resolved_at FLOAT, 
	recovery_before JSON, 
	state_version INTEGER NOT NULL, 
	PRIMARY KEY (publication_id), 
	CHECK (previous_generation > 0), 
	CHECK (target_generation > previous_generation), 
	CHECK (state_version > 0), 
	CHECK (publication_id IS NULL OR length(trim(publication_id)) > 0), 
	CHECK (checkpoint_id IS NULL OR length(trim(checkpoint_id)) > 0), 
	CHECK (recovery_operation_id IS NULL OR length(trim(recovery_operation_id)) > 0), 
	CHECK (status IS NULL OR length(trim(status)) > 0), 
	CHECK (prepared_at IS NULL OR prepared_at BETWEEN -1.0e308 AND 1.0e308), 
	CHECK (resolved_at IS NULL OR resolved_at BETWEEN -1.0e308 AND 1.0e308)
);

CREATE INDEX ix_agent_inbox_agent_id ON agent_inbox (agent_id);

CREATE UNIQUE INDEX uq_live_activity_owner ON activity_admissions (agent_id) WHERE disposition = 'admitted';

CREATE UNIQUE INDEX uq_active_sleep_owner ON sleep_plans (agent_id) WHERE status = 'active';

CREATE UNIQUE INDEX uq_open_membership ON membership_intervals (team_id, agent_id) WHERE leave_event_id IS NULL;

CREATE UNIQUE INDEX uq_direct_personal_view ON chat_personal_views (agent_id, message_id) WHERE interval_id IS NULL;
