# Relational Keys, Constraints, and Authority

ATT combines physical SQLite constraints with domain and graph validation to preserve accepted identity, provenance, and authority.

The complete [schema 16 SQL reference](Schema.sql) records all 83 declared tables, 771 columns, 591 SQL checks, 43 additional unique constraints, and five explicitly declared indexes.

SQLite also creates internal indexes for applicable primary and unique keys; those are separate from the five named indexes below.

The SQL reference includes concrete column nullability, check expressions, foreign-key columns and delete actions, and index predicates.

Application and ORM defaults do not become SQLite server defaults merely because capture normally supplies a value.

Optional FTS5 search structures are derived and are outside this authoritative relational layout.

## Declared Primary and Unique Keys

Parentheses identify one composite key, and semicolons separate independent unique constraints.

This table lists physical keys; additional service-level uniqueness and complete foreign-key/check declarations are described below and in the SQL reference.

| Table | Primary key | Additional SQL unique keys |
| --- | --- | --- |
| `manager_config` | (`config_key`) | None beyond the primary key. |
| `agents` | (`agent_id`) | (`name`) |
| `agent_messages` | (`id`) | None beyond the primary key. |
| `agent_inbox` | (`message_id`) | None beyond the primary key. |
| `teams` | (`team_id`) | None beyond the primary key. |
| `team_members` | (`team_id`, `agent_id`) | (`interval_id`) |
| `team_inbox` | (`id`) | None beyond the primary key. |
| `team_proposals` | (`proposal_id`) | None beyond the primary key. |
| `libraries` | (`lib_id`) | (`owner_agent_id`) |
| `library_permissions` | (`lib_id`, `path`, `team_id`) | None beyond the primary key. |
| `doc_lib_files` | (`lib_id`, `path`) | None beyond the primary key. |
| `doc_lib_links` | (`source_lib_id`, `source_path`) | None beyond the primary key. |
| `team_formation_requests` | (`request_id`) | (`created_team_id`) |
| `team_formation_invitations` | (`request_id`, `agent_id`) | None beyond the primary key. |
| `team_formation_revisions` | (`revision_id`) | (`request_id`, `proposal_revision`); (`source_draft_id`) |
| `team_formation_invitation_decisions` | (`decision_id`) | None beyond the primary key. |
| `team_formation_drafts` | (`draft_id`) | None beyond the primary key. |
| `communication_requests` | (`request_id`) | None beyond the primary key. |
| `communication_approvals` | (`request_id`, `principal_kind`, `principal_id`) | None beyond the primary key. |
| `communication_agreements` | (`agreement_id`) | None beyond the primary key. |
| `peer_messages` | (`message_id`) | (`invocation_id`) |
| `governance_cases` | (`case_id`) | None beyond the primary key. |
| `governance_electorates` | (`case_id`, `voter_agent_id`) | (`case_id`, `position`) |
| `governance_ballots` | (`ballot_id`) | (`case_id`, `voter_agent_id`) |
| `migration_requests` | (`request_id`) | None beyond the primary key. |
| `team_topology_events` | (`event_id`) | (`team_id`, `position_revision`) |
| `parent_acceptances` | (`acceptance_id`) | None beyond the primary key. |
| `team_position_cooldowns` | (`team_id`) | None beyond the primary key. |
| `resource_decisions` | (`attempt_id`) | None beyond the primary key. |
| `agent_activities` | (`agent_id`) | None beyond the primary key. |
| `activity_admissions` | (`admission_id`) | None beyond the primary key. |
| `activity_invocations` | (`invocation_id`) | None beyond the primary key. |
| `notification_frames` | (`frame_id`) | None beyond the primary key. |
| `model_requests` | (`model_request_id`) | None beyond the primary key. |
| `memory_index_requests` | (`request_id`) | None beyond the primary key. |
| `model_token_claims` | (`claim_id`) | (`audit_request_id`); (`index_request_id`); (`model_request_id`) |
| `model_availability` | (`agent_id`, `model_alias`) | None beyond the primary key. |
| `agent_notifications` | (`notification_id`) | (`agent_id`, `deduplication_key`) |
| `notification_claims` | (`notification_id`, `model_request_id`) | None beyond the primary key. |
| `chat_reminder_previews` | (`notification_id`) | None beyond the primary key. |
| `notification_suppression` | (`preference_id`) | None beyond the primary key. |
| `notification_summary_items` | (`summary_id`, `notification_id`) | (`notification_id`) |
| `sleep_plans` | (`sleep_id`) | None beyond the primary key. |
| `sleep_conditions` | (`condition_id`) | None beyond the primary key. |
| `direct_relationships` | (`relationship_id`) | (`agent_a_id`, `agent_b_id`) |
| `friendship_requests` | (`request_id`) | None beyond the primary key. |
| `chat_operations` | (`agent_id`, `operation_key`) | None beyond the primary key. |
| `chat_preferences` | (`agent_id`) | None beyond the primary key. |
| `chat_streams` | (`stream_id`) | (`relationship_id`); (`team_id`) |
| `chat_events` | (`event_id`) | (`stream_id`, `sequence`) |
| `membership_intervals` | (`interval_id`) | (`join_event_id`) |
| `chat_messages` | (`message_id`) | (`author_agent_id`, `operation_key`); (`invocation_id`, `operation_key`); (`publication_event_id`) |
| `chat_revisions` | (`revision_id`) | (`event_id`); (`message_id`, `revision_number`) |
| `chat_withdrawals` | (`withdrawal_id`) | (`event_id`); (`message_id`) |
| `chat_message_projections` | (`message_id`) | None beyond the primary key. |
| `chat_personal_views` | (`view_id`) | (`agent_id`, `message_id`, `interval_id`) |
| `executions` | (`execution_id`) | None beyond the primary key. |
| `execution_attempts` | (`attempt_id`) | (`execution_id`, `attempt_index`) |
| `execution_payloads` | (`payload_id`) | (`execution_id`, `content_kind`) |
| `execution_observations` | (`observation_id`) | (`execution_id`, `observation_index`) |
| `execution_controls` | (`control_id`) | None beyond the primary key. |
| `tool_cooldowns` | (`agent_id`, `tool_name`) | None beyond the primary key. |
| `health_incidents` | (`incident_id`) | (`subject_agent_id`, `fingerprint`); (`subject_att_id`, `fingerprint`); (`subject_team_id`, `fingerprint`) |
| `health_observations` | (`observation_id`) | None beyond the primary key. |
| `health_detector_states` | (`agent_id`, `detector`, `tool_key`) | None beyond the primary key. |
| `health_incident_events` | (`event_id`) | None beyond the primary key. |
| `audit_runs` | (`audit_id`) | None beyond the primary key. |
| `audit_participants` | (`audit_id`, `scoped_agent_id`) | (`audit_id`, `position`) |
| `audit_activity_checkpoints` | (`checkpoint_id`) | None beyond the primary key. |
| `audit_findings` | (`audit_id`, `scoped_agent_id`) | None beyond the primary key. |
| `audit_model_requests` | (`request_id`) | None beyond the primary key. |
| `audit_execution_evidence` | (`execution_id`) | None beyond the primary key. |
| `audit_chat_evidence` | (`event_id`) | (`audit_id`, `sequence`) |
| `audit_evidence` | (`audit_id`) | None beyond the primary key. |
| `system_memory_events` | (`event_id`) | (`sequence`) |
| `agent_memory_segments` | (`segment_id`) | (`invocation_id`) |
| `agent_memory_cards` | (`memory_id`) | (`invocation_id`); (`segment_id`) |
| `memory_card_tags` | (`memory_id`, `tag`) | (`memory_id`, `sequence`) |
| `memory_card_source_events` | (`segment_id`, `event_id`) | (`segment_id`, `sequence`) |
| `retained_memory_references` | (`reference_id`) | None beyond the primary key. |
| `commit_receipts` | (`operation_id`) | None beyond the primary key. |
| `recovery_incidents` | (`incident_id`) | (`checkpoint_id`, `agent_id`, `affected_identity`) |
| `publication_manifests` | (`publication_id`) | None beyond the primary key. |

## Partial and Secondary Indexes

| Index | Columns | Predicate and purpose |
| --- | --- | --- |
| `uq_live_activity_owner` | `activity_admissions(agent_id)` | Unique where `disposition = 'admitted'`; one live admission per ordinary person. |
| `uq_open_membership` | `membership_intervals(team_id, agent_id)` | Unique where `leave_event_id IS NULL`; one open relationship interval per pair. |
| `uq_direct_personal_view` | `chat_personal_views(agent_id, message_id)` | Unique where `interval_id IS NULL`; one direct-conversation view per owner and message. |
| `uq_active_sleep_owner` | `sleep_plans(agent_id)` | Unique where `status = 'active'`; one finite active sleep plan per owner. |
| `ix_agent_inbox_agent_id` | `agent_inbox(agent_id)` | Nonunique owner lookup for addressed personal mail. |

For example, a completed admission does not prevent a new admission, and a closed membership interval does not prevent a distinct rejoin interval.

`execution_observations(execution_id, observation_index)` has an additional unique key so equal or adjusted wall-clock timestamps cannot reorder accepted execution health facts.

The physical column allows null for retained foundation evidence; registered execution producers supply a positive ordered observation index.

## Concrete References and Exclusive Choices

| Domain | Physical shape | Additional authority validation |
| --- | --- | --- |
| Library ownership | `library_kind`, nullable team/Agent owner references, exclusive kind/owner checks, and a unique private owner. | Every ordinary Agent has exactly its canonical private library; private libraries are nonpublic, have no team ACL or links, and match the owner's lifecycle. |
| Organizational parent | Explicit nullable Agent/AgentTeam references, mutually exclusive parent columns, and separate creator provenance. | Active parents are eligible, topology is acyclic, position events are contiguous, and attachment has exact prospective-parent acceptance. |
| Operation scope | `scope_kind` with a team reference only for `agent_team`. | Owner, invocation, captured generation, current membership, and resource ACLs agree at protected access and publication. |
| Notification source | Exactly one concrete chat, mail, execution, or system-event FK plus matching `source_kind`. | Recipient entitlement, direct/team stream kind, trusted classification, source owner, and deduplication evidence agree. |
| Token claim profile | Exactly one ordinary, audit, or indexing request FK, independently unique. | Referenced alias, dispatch/outcome, settlement, beneficiary, and scoped audit provenance agree. |
| Governance electorate | Case/voter key and a ballot's composite electorate reference. | Frozen eligible voters and exact membership intervals belong to the actual principal and case revision; choice schema and ballots remain immutable. |
| Chat publication | Concrete stream, author, event, optional invocation, and authenticated Host operation reference. | Model origin matches its actual invocation; Host origin has the matching owner/operation receipt, digest, authorized input, and source event. |
| Chat recipient view | Owner/message key, concrete interval where applicable, and revision/withdrawal pointers. | Publication belongs to the allowed interval or direct endpoints, live/frozen pointers match the accepted boundary, and all eligible recipient views exist. |
| Audit participant | Composite `(audit_id, scoped_agent_id)` snapshot reference. | Actual temporary identity and permitted evidence are retained without ordinary reusable Agent, membership, or private-library registrations. |

Foreign keys establish existence and identity relationships; they do not by themselves establish current membership, permission, consent, or an authorized producer.

Some retained core records, including `library_permissions`, have composite keys without physical foreign-key declarations for every ID column; their library/team references are enforced by domain and detached-state validation.

The SQL reference distinguishes those columns from actual foreign keys rather than inferring constraints from names ending in `_id`.

Current team membership and open intervals agree in both directions, and a leave event identifies its actual departing person.

A dissolution event may close several intervals without impersonating each participant.

Current active-Agreement equivalence, source-body digests, complete recipient projections, matching frozen cases, and exact operation-receipt contents require graph/domain checks in addition to these SQL keys.

## Scalar and State Checks

Activity-table identifiers reject blank text, integer-backed booleans require `0` or `1`, version columns are positive, and finite timestamp checks bound stored numbers.

Strict record validation rejects coerced integers, booleans, nonfinite values, malformed JSON shapes, and inconsistent references before acceptance.

Count, ordering, and budget columns retain their individual nonnegative or positive bounds rather than share an inferred universal default.

The [request and token matrices](Request_and_Token_States.md) specify legal cross-profile request, settlement, and presentation states.

Execution terminal states require confirmed outcomes, visibility cannot move from background back to foreground, and a confirmed terminal outcome cannot become uncertain later.

Sleep and timed suppression require captured admitted bounds and finite nonnegative remaining durations, while permanent suppression has no fabricated expiration.

Ended suppression identities cannot be reactivated, and summary coverage associates each ordinary arrival with at most one covering summary without changing read state or ballots.

## Delete Actions and Retained History

The declared graph contains restrictive source references as well as explicit `CASCADE`, `SET NULL`, and default `NO ACTION` relationships.

The SQL reference records each action rather than treating every foreign key as restrictive.

For example, library files cascade with an actually deleted library, while durable activity, request, interval, and other retained evidence can prevent deleting their ordinary owner.

Some initiating-Agent audit references become null on permitted physical deletion; that does not select a replacement actor or modify retained identity snapshots.

Manager lifecycle validation precedes physical deletion in both durable and volatile modes and rejects required creator/history references before lower-level cascade actions could erase authority.

Retained death archives personal artifacts and closes current authority while preserving the person and historical references.

Actual parent loss is an accepted domain transition that detaches surviving direct children and retains its event; it is not inferred from a missing FK during restoration.

## Dependency and Validation Order

Capture retained owners before their source streams, events, intervals, messages, personal views, notices, and presentation claims.

Capture admission, invocation, frame, request, and token-claim prerequisites before dispatch, and execution inputs before executor side effects.

Missing insert-only prerequisites may be inserted without overwriting an existing unrelated Agent, library, file, or team snapshot.

Append-only conflicts, equal-version conflicts, regressing sequence cursors, reopened admissions, and reversed terminal facts fail closed.

Required graph validation and exact receipt verification finish before commit, while runtime publication and dependent dispatch follow acceptance.

Restore uses the same authority rules over detached state and rejects missing or contradictory references rather than creating replacement people, libraries, consent, or model bindings.

See [Transactions and Validation](Transactions_and_Validation.md) and [Recovery and Publication](Recovery_and_Publication.md) for worker capture, accepted-write cancellation, validation reuse, rollback, and restart settlement.
