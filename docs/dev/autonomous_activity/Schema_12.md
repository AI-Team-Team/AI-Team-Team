# Schema 12 Freeze

## Activation Boundary

`12` is the incompatible target schema for the complete replacement, not a change to the current schema-version constant without implementing its tables.

Phase 1 must install this layout, readers, immutable deltas, dependency closure, restore validators, and supported-version preflight together.

Schema 11 and earlier must then fail before `create_all`, WAL mutation, or any structural write, with no migration or legacy loader.

The physical SQL types below are SQLite `TEXT`, `INTEGER`, and finite timestamp `REAL`, with typed JSON only where explicitly identified.

IDs are nonblank text, booleans are checked integers in `{0, 1}`, counts and versions are checked integers, and timestamps are validated as finite before binding.

Every table carries a positive `state_version` for mutable projections or a positive `created_version` for insert-only facts unless its existing immutable identity already supplies that evidence.

Existing ordinary identities and historical subjects are retained with restrictive references rather than cascading deletion of authorized history.

Temporary audit identities remain absent from ordinary persisted Agent, membership, team, and library rows.

Ordinary activity, chat, notification, and execution tables below apply to retained ordinary identities, while audit-scoped participants use the dedicated evidence references defined later in this freeze.

This is a persistence profile of the common services rather than a separate scheduler, model engine, or model-selectable durability bypass.

## Retained and Replaced Tables

| Existing table | Target treatment |
| --- | --- |
| `manager_config` | Retain config and registrations as serializable values, add durable-mode evidence, publication generation, and required model accounting; never store live clients or callables. |
| `agents` | Retain UUID identity and personal fields including explicit presentation preferences, allow retained `dead` lifecycle alongside supported inactive states, and preserve strict active-model binding. |
| `agent_messages` | Replace `discussion_id` with nullable `invocation_id` and explicit source references; preserve complete provider-valid committed personal context and transient-body redaction. |
| `agent_inbox` | Retain addressed mail and independently mutable read receipt, replace ballot `round_id` payload references with exact `case_id` references. |
| `teams` | Add active/dissolved lifecycle and explicit nullable Agent or AT parent, preserve immutable creator provenance separately, remove stored depth authority and reset-on-discussion migration counts. |
| `team_members` | Retain only the current `(team_id, agent_id)` projection, tied to the corresponding open historical interval. |
| `team_inbox` | Retain organizational source references and incidents, never duplicate every member's chat body or infer incident acknowledgement from activity completion. |
| `team_proposals` | Retain institution-specific proposal data with exact case or consent references rather than inferred transcript authority. |
| `libraries`, `library_permissions`, `doc_lib_files`, `doc_lib_links` | Retain ownership, private lifecycle, live ACLs, managed links, and file deltas without coupling chat or friendship authority to them. |
| `team_formation_requests`, `team_formation_invitations`, `team_formation_revisions`, `team_formation_invitation_decisions` | Retain exact revision consent and four attitudes, add applicable topology and membership-interval provenance. |
| `team_formation_drafts` | Retain optional advisory artifacts, replace `source_discussion_id` with source message and initiator-invocation references, and remove a mandatory draft prerequisite. |
| `communication_requests`, `communication_approvals`, `communication_agreements`, `peer_messages` | Retain policy snapshots and authority, add exact case and side-specific exemption evidence with actual organizational parents. |
| `communication_ballots` | Remove the duplicated authoritative table and derive communication projections from immutable governance ballots. |
| `governance_rounds` | Replace with `governance_cases` and an exact electorate revision. |
| `governance_ballots` | Keep immutable votes but replace the round foreign key with a case and electorate reference. |
| `migration_requests` | Replace team-only target ancestry with nullable explicit Agent or AT principals, add prospective-parent acceptance, detachment kind, and relevant path evidence. |
| `system_memory_events` | Preserve append-only sanitized historical snapshots, replace discussion/turn provenance with invocation and source references, and retain ephemeral audit evidence without executable identity FKs. |
| `agent_memory_segments`, `agent_memory_cards` | Replace turn and discussion provenance with invocation and authorized origin references without changing owner or personal catalog on membership changes. |
| `memory_card_tags`, `memory_card_source_events`, `retained_memory_references` | Preserve ordering, optional indexing dependencies, owned references, and transient recall protections. |

FTS indexes remain derived optional memory indexes rather than a required dependency for messaging or ordinary activity.

## Personal Admission and Model Evidence

| New table | Keys, fields, and constraints |
| --- | --- |
| `agent_activities` | PK/FK `agent_id`; `intent` in continuing/idle/sleep, last factual availability, arrival generation, presentation generation, context version, and current admission reference; one marker per retained Agent. |
| `activity_admissions` | PK `admission_id`; owner FK, runtime generation, accepted version, captured requested scope, and technical disposition; at most one live admitted owner via a partial unique index. |
| `activity_invocations` | PK `invocation_id`; admission and owner FKs, generation, personal/team scope XOR, context version, start and boundary evidence, and interruption evidence; no member number or round number. |
| `notification_frames` | PK `frame_id`; invocation and owner FKs, context version and arrival cutoff, authorized sanitized summary references, and no complete raw prompt. |
| `model_requests` | PK `model_request_id`; frame and owner FKs, stable model alias, attempt index, input version, dispatch and outcome evidence, provider earliest-retry boundary, and request/sequence budgets. |
| `memory_index_requests` | PK `request_id`; source segment and matching retained beneficiary FKs, source version, stable indexing alias, bounded attempt/dispatch/outcome evidence, and input digest; no personal invocation or raw prompt. |
| `model_token_claims` | PK `claim_id`; exactly one concrete ordinary-request, audit-request, or optional-index-request FK with uniqueness on each request column, model alias, reserved prompt/output budgets, settlement evidence, and confirmed-unsent/known-usage/unknown-sent distinction. |

Personal scope requires `scope_team_id IS NULL`, while AgentTeam scope requires a valid retained team reference and live authority at access time.

An admission is not a provider request, and several bounded invocations may checkpoint one continuing admission without cloning its owner.

`model_requests.frame_id` points to a previously admitted frame, avoiding a circular foreign-key dependency from frames back to provider requests.

Frame evidence stores sanitized context and authorized references instead of persisting transient private or recall body text.

Token settlement is idempotent by claim ID, and uncertain sent usage is not made available again merely by loading state.

Ordinary and audit requests reserve and settle against the same atomic model-alias ledger, without requiring an audit caller to have an ordinary Agent row or attributing its request to Root.

Optional memory indexing uses the same model admission and quota primitives with source-owner provenance, without impersonating that beneficiary's personal activity or creating a Working Context frame.

The Host's existing indexing service chooses this maintenance profile, and neither ordinary tools nor model arguments can use it to bypass a personal invocation or quota claim.

## Source References and Notification Progress

| New table | Keys, fields, and constraints |
| --- | --- |
| `agent_notifications` | PK `notification_id`; owner FK, typed source reference, closed trusted classification, arrival generation, deduplication key, and committed version; unique `(owner, deduplication_key)`. |
| `notification_claims` | PK `(notification_id, model_request_id)` with both FKs; frame evidence, state in reserved/dispatched/presented/uncertain, and observation time. |
| `chat_reminder_previews` | PK/FK `notification_id`; owner and source revision FKs, bounded captured authorized title/preview, and visibility evidence independent of subsequent withdrawal. |
| `notification_suppression` | PK `preference_id`; owner FK, all/Agent/AT scope with exclusive concrete source columns, permanent or timed evidence, saved remainder and sample anchor. |
| `sleep_plans` | PK `sleep_id`; owner FK, positive admitted latest-wake duration, finite nonnegative remaining duration, sampled anchor, accepted bounds, and active/expired evidence; at most one active plan per owner. |
| `sleep_conditions` | PK `condition_id`; sleep FK, typed authorized Agent/AT message source or owned execution FK, admitted generation, and invalidation evidence. |

A typed source reference uses exactly one concrete nullable FK for chat message, personal mail, execution, or System Memory event, with a matching source-kind check.

Do not put a polymorphic ID into an unchecked JSON field and claim that it has referential integrity.

Direct/team message kind must also match the referenced stream ownership.

Suppression has no producer-selected protected-notice override, and permanent suppression has no fabricated expiration.

Claims do not contain read receipts, domain choices, or attention acknowledgement.

Unique notice keys prevent repeated recovery or result presentation from replaying the source operation.

## Chat and Historical Relationships

| New table | Keys, fields, and constraints |
| --- | --- |
| `direct_relationships` | PK `relationship_id`; canonical ordered pair of retained Agent FKs, bilateral friendship, separately owned blocks/refusals, positive generation, and per-direction allowance in 0..3; unique pair. |
| `friendship_requests` | PK `request_id`; relationship and endpoint FKs, captured generation, factual request/response state, and metadata only; stale generations cannot restore friendship. |
| `chat_streams` | PK `stream_id`; exactly one team FK or direct-relationship FK, unique owner relation, and next ordering position. |
| `chat_events` | PK `event_id`; stream FK, positive sequence, event kind, actor provenance, and finite creation timestamp; unique `(stream_id, sequence)`. |
| `membership_intervals` | PK `interval_id`; team and Agent FKs, stream and join-event FKs, optional later leave-event FK; one open interval per pair and no overlaps. |
| `chat_messages` | PK `message_id`; stream, author, and publication-event FKs, invocation idempotency key, and timestamps; one deliberate publication per admitted invocation operation. |
| `chat_revisions` | PK `revision_id`; message and event FKs, positive version, immutable Markdown body, extracted title, and committed time; unique `(message_id, version)`. |
| `chat_withdrawals` | PK `withdrawal_id`; message, exact last revision, actor, and event FKs, admitted window evidence, and committed time; author-only mutation checked at commit. |
| `chat_message_projections` | PK/FK `message_id`; latest revision and optional withdrawal FKs, plus authoritative version; a child projection avoids message-to-revision identity cycles. |
| `chat_personal_views` | PK `view_id`; owner/message FKs, applicable membership interval for team chat, authorized live or frozen revision and withdrawal pointers, departure cutoff, read evidence, unread override, and personal deletion flag. |

The team stream's ordering domain includes joins, leaves, publication, editing, withdrawal, and dissolution rather than relying on wall-clock comparison.

An interval admits publication strictly after join and before leave, with all referenced events required to belong to that team's stream.

Membership publication and the current `team_members` projection commit together without updating existing Agent-owned rows.

Freezing departure views captures allowed revision and withdrawal references at the same ordered boundary as closing membership.

Rejoining opens a new interval without synchronizing old frozen views or admitting absence-period publications and revisions.

Each personal view must be backed by its authorized publication interval, or by direct-conversation endpoint ownership, before any count, preview, search, reference, or pagination result is produced.

Withdrawal hides live source content but cannot delete retained departure snapshots or already captured recipient reminder previews.

Read evidence, unread overrides, deletion, and restoration remain recipient-owned projections rather than mutation of shared source history.

Dissolution closes live intervals and removes live team discovery while retaining team rows and eligible archives as historical evidence.

## Execution, Availability, and Control

| New table | Keys, fields, and constraints |
| --- | --- |
| `executions` | PK `execution_id`; owner and invocation FKs, captured original scope, registered tool identity/effects snapshot, admitted generation, explicit/detached visibility, five execution states, and independently stored attention. |
| `execution_attempts` | PK `attempt_id`; execution FK, positive index, captured retry contract, actual-start timestamp, dispatch evidence and external handle; unique `(execution_id, attempt_index)`. |
| `execution_payloads` | PK `payload_id`; owner and execution references, immutable protected input/result, content kind and digest; owner authorization and privacy filtering apply to every query. |
| `execution_observations` | PK `observation_id`; execution and optional attempt FKs, health state, supported evidence kind, finite observation time, and uncertainty; append-only. |
| `execution_controls` | PK `control_id`; execution FK, authorized requester, requested stop/suspend operation, factual acknowledgement, and outcome-race evidence; a request does not overwrite execution state. |
| `tool_cooldowns` | PK `(agent_id, registered_tool_name)`; owner FK, eligible fault identity, accounting mode, saved remainder or wall-time boundary, and sample evidence; new-call-only and no extension on denied calls. |
| `model_availability` | PK `(agent_id, model_alias)` with owner FK; retry-sequence identity, recoverable versus remediation-required reason, bounded budgets, earliest allowed admission, and last-confirmed evidence; no implicit unrelated-person ban. |
| `team_position_cooldowns` | PK/FK `team_id`; successful own-position event, accounting mode, timing evidence, and positive cooldown duration; ancestor-carried movement does not rewrite it. |

Inputs and results may use owner-protected storage, but complete submitted prompts, provider-hidden reasoning, and transient recall bodies are not automatically persisted into execution payloads.

Execution payloads point to their admitted execution rather than introduce a circular execution-to-payload identity FK, and inputs commit with their execution before dispatch.

Shared provider protection, if required, is a separate explicit Host resource policy rather than inferred from one person's availability failure.

Runtime clients, tool callables, coroutine stacks, locks, executor connections, and active transport handles remain host bindings.

An external operation ID is evidence rather than proof of remote completion or permission to reconnect after load.

Executor suspension acknowledgement is control evidence rather than a sixth execution state or permission for automatic resumption.

Interrupted queued/running evidence stays last-confirmed with explicit uncertainty and cannot be counted as freshly verified live execution.

## Governance, Topology, Health, and Recovery

| New or replacement table | Keys, fields, and constraints |
| --- | --- |
| `governance_cases` | PK `case_id`; exactly one Agent/AT principal FK, business reference, positive electorate revision, strict choice-schema snapshot, factual status and deadline where applicable. |
| `governance_electorates` | PK `(case_id, voter_agent_id)` with both FKs; frozen eligibility evidence and deterministic position. |
| `governance_ballots` | PK `ballot_id`; composite electorate FK, immutable strict choice and finite timestamp; unique `(case_id, voter_agent_id)`. |
| `team_topology_events` | PK `event_id`; team FK, old/new explicit optional parent references, creator provenance, exact acceptance/case reference, and voluntary/parent-loss detachment kind. |
| `parent_acceptances` | PK `acceptance_id`; exact attaching team, exactly one prospective Agent/AT parent FK, case or Agent decision reference, factual decision, and topology fingerprint. |
| `health_incidents` | PK `incident_id`; retained subject reference, stable fingerprint, occurrence count, first/latest timestamps, evidence, and pending/claimed/acknowledged handling; unique subject/fingerprint. |
| `audit_runs` | PK `audit_id`; retained subject references, temporary team identity snapshot, frozen template/electorate, generation, factual lifecycle, and budget/deadline evidence; never an ordinary team FK. |
| `audit_participants` | PK `(audit_id, scoped_agent_id)` with a run FK; sanitized identity/model snapshots and frozen electorate position; no ordinary Agent FK, memory, inbox, or library registration. |
| `audit_model_requests` | PK `request_id`; composite participant FK, invocation/frame identity evidence, input version, stable alias, bounded attempt/dispatch/outcome facts, and no raw prompt or Working Context. |
| `audit_execution_evidence` | PK `execution_id`; composite participant FK, captured audit scope, tool/effects snapshot, attempt and generation evidence, factual outcome/health/attention, and only permitted sanitized result references. |
| `audit_chat_evidence` | PK `event_id`; run and participant references, ordered explicit publication/revision facts, and sanitized permitted findings without an ordinary chat stream or membership FK. |
| `audit_evidence` | PK/FK `audit_id` to its run; subject references, sanitized evidence, strict findings, aggregation result, and auditor identity snapshots with no FK to ephemeral runtime participants. |
| `recovery_incidents` | PK `incident_id`; retained owner FK, source checkpoint and affected invocation/execution references, last-confirmed facts, and uncertainty; unique stable affected-evidence identity. |
| `publication_manifests` | PK `publication_id`; source checkpoint, previous/target generation, validated staged-file references, required recovery transaction identity, and preparation/publication/rollback evidence. |

Current Agent/AT parent columns are exclusive and nullable for independence, while immutable creator provenance remains separate and may point to retained dead identities.

Deleting a parent is not silently handled by `SET NULL`, and the authoritative parent-loss transition must retain event provenance and detach only surviving direct children.

Case deadlines do not create implicit defaults for ordinary voluntary unanswered approval.

A case's frozen electorate and choice schema are immutable.

An electorate change invalidates the old solicitation and creates a new case identity with an explicit electorate revision, while its old ballots remain evidence only for the original case.

Communication approvals reference the authoritative case, derive their ballots from it, and persist independent-side exemption evidence without manufacturing a vote.

Reattachment acceptance binds the exact attaching team and prospective parent and must survive commit-time topology, eligibility, and cycle revalidation.

Audit runs and participants are durable forensic snapshots, not retained active registrations or an exception granting them ordinary recruitment, friendship, or library access.

The common activity, message, notification, and execution services select the trusted audit persistence profile from the registered supervisory lifecycle before capturing dependencies.

Audit frames and request evidence use scoped IDs without persisting reusable personal windows, while explicit permitted findings and tool outcomes are retained in their dedicated evidence rows.

An audit request and its token claim commit together before model dispatch, and an audit execution's required evidence commits before restricted tool dispatch.

Ending or interrupting an audit fences its live workers, records its last-confirmed evidence and final or UNKNOWN assessment, and removes the temporary runtime identities.

Restore validates these evidence references and quota uncertainty but never recreates auditors, restores their memory, reopens their conversation, or replays their model/tool work.

## Dependency Closure and Write Order

Insert retained identities and source owners before streams, events, intervals, revisions, views, notifications, claims, and derived observations.

Create admission/frame/request/claim dependencies in that order, with explicit captured identity prerequisites.

Insert-only prerequisites never overwrite existing unrelated personal windows, teams, libraries, or files.

Versioned mutable projections merge by newest authoritative version, while append-only facts merge by identity and reject conflicting bodies for the same ID.

Tombstones and retained-history constraints prevent stale pending deltas from resurrecting removed runtime projections or erasing evidence.

Keep one executing write and one coalescible pending delta with exact per-domain receipt dependencies.

SQLite foreign keys, exclusive writer ownership, WAL, busy timeout, cancellation settlement, and strict error propagation remain mandatory.

## Publication and Recovery Gate

Acquire writer ownership and admission/resource gates, settle accepted current commits, and reject surviving unsafe mutators before staging.

Validate every reference in detached state, stage files and views, derive interruption facts without external calls, and prepare a recoverable generation manifest.

While files are provisional, managed resource reads stay gated and directory projections retain the old complete runtime.

The required durable recovery and publication-preparation receipt precedes the synchronous runtime registry switch, without an intervening await or observer.

Before publication completes, live-process failure restores old runtime, directories, additions, and timer admission, or stays fail-closed if reconciliation cannot safely complete.

Crash recovery reconciles an incomplete manifest before allowing any model or worker mutation, because SQLite and directory renames are not one OS-atomic instruction.

After publication commits, a scheduling failure before dispatch retains committed new state and pending notices rather than undoing it or asserting an activation occurred.

Callbacks are observational and cannot roll back a completed authoritative publication.

Affected active people and owners are admitted once after publication, unaffected sleepers retain restoration-start countdowns, and retained dead/inactive people are not reconstructed.

Historical handles are never automatically replayed, polled, or reconnected.

## Required Physical Validation

Phase 1 tests must exercise SQL checks, uniqueness, concrete foreign keys, interval ordering, cross-owner references, stale generations, impossible state combinations, and each manifest failure boundary.

Restore rejects corruption rather than creating missing people, libraries, frames, electorates, or parent consent.

An active current Root requires its binding, while a retained dead creator is valid provenance and does not need a runtime model.

Remaining tuning choices concern measured checkpoint precision, supported executor integration, and evidence-specific health thresholds, not these confirmed institutions or permission boundaries.
