# Current Database Schema

ATT schema `16` comprises the following 83 declared relational tables.

The catalogue includes retained core state and all personal-runtime domains, with the most important keys and relationships summarized below.

The complete [SQL reference](Schema.sql) records every declared column, check, foreign-key action, unique key, and index for schema `16`.

The [relational constraint reference](Relational_Constraints.md) lists exact primary/unique keys and explains which invariants require graph or domain validation.

The [request and token state matrices](Request_and_Token_States.md) describe the legal dispatch, outcome, settlement, and presentation combinations shared by ordinary, audit, and indexing requests.

The [model package](../../src/ai_team_team/database/models/) implements these declarations, and application defaults remain distinct from SQLite server defaults.

## Scalar and Reference Rules

Identifiers are nonblank opaque text references; ordinary Agent identity uses an immutable UUID `agent_id` rather than a display name.

Integer-backed booleans require `0` or `1`, integer counts and versions retain their domain bounds, and timestamps must be finite.

Mutable domain projections carry positive `state_version` evidence, while append-only facts use stable identities and, where declared, `created_version`.

Typed source references use concrete foreign-key columns with matching discriminator and exclusivity checks rather than an unchecked polymorphic JSON ID.

JSON snapshots supplement relational ownership and are validated for their exact domain shape and references.

Deleting an identity must respect retained historical references rather than erase authorized history through cascading deletion.

## Identity, Organizations, and Libraries

| Table | Keys and responsibility |
| --- | --- |
| `manager_config` | `config_key`; schema/checkpoint metadata, serializable configuration, stable model metadata, presets, and accounting values. |
| `agents` | `agent_id`; unique name, personal role and instructions, saved model alias, context, lifecycle, and presentation preferences. |
| `agent_messages` | Ordered message identity and owner; committed personal window with actual invocation and authorized chat/execution provenance. |
| `agent_inbox` | `message_id` and owner; addressed mail payload and independently mutable `read_at`. |
| `teams` | `team_id`; active/dissolved state, explicit optional parent, position revision, immutable creator provenance, and team-owned configuration. |
| `team_members` | `(team_id, agent_id)`; current relationship projection with its accepted open membership interval. |
| `team_inbox` | Team-owned organizational messages and incident references. |
| `team_proposals` | Proposal identity, proposed action, initiator provenance, vote projection, and factual status. |
| `libraries` | `lib_id`; exclusive team/private ownership, lifecycle, metadata, and public visibility. |
| `library_permissions` | Library/path/team grant; normalized live team ACLs for ordinary libraries. |
| `doc_lib_files` | `(lib_id, path)`; managed text-file contents captured by path deltas. |
| `doc_lib_links` | Source library/path and target library/path; registered managed file links with live target authorization. |

Each ordinary Agent owns exactly one canonical `PDL-<agent_id>` private library.

Private libraries are nonpublic, have no team grants or managed links, and retain an owner-compatible lifecycle.

Membership rows contain relationships rather than personal roles, memory, model configuration, or private-library copies.

Accepted membership intervals determine the current projection; an older progress snapshot cannot reopen a departed relationship.

An active team has zero or one organizational parent, selected from an Agent or AgentTeam independently of its creator.

A null parent means independence, while a dissolved team's retained former parent is historical provenance.

## Consensual Formation

| Table | Keys and responsibility |
| --- | --- |
| `team_formation_requests` | `request_id`; initiator, creator, proposed parent and members, normalized design, exact fingerprints, creation/late-join policy, and resulting team. |
| `team_formation_invitations` | Request/invitee identity; current revision attitude, public response time, joining, and explicit late-join state. |
| `team_formation_revisions` | Immutable revision identity and proposal snapshot, exact fingerprints, author, and optional candidate provenance. |
| `team_formation_invitation_decisions` | Append-only exact-revision invitee decisions. |
| `team_formation_drafts` | Optional initiator-owned candidate, base revision, intended participants, source message, and actual initiator invocation. |

Material revisions require renewed exact-revision consent, while unchanged proposals cannot fabricate a new decision.

Invitation attitude remains separate from mail presentation and read state.

Optional candidates are neither membership authority nor executable jobs that restore may replay.

## Communication and Institutional Authority

| Table | Keys and responsibility |
| --- | --- |
| `communication_requests` | Request identity, AT endpoints, initiating Agent audit metadata, immutable policy/direction, real route evidence, and stale/successor chain. |
| `communication_approvals` | Request/principal identity and order; factual status and exact governance `case_id`. |
| `communication_agreements` | Agreement identity, directional AT endpoints, origin request, immutable policy, active/revoked state, and supersession evidence. |
| `peer_messages` | Message identity, AT endpoints, actual invocation, optional Agreement, body, and delivery/consumption facts. |
| `governance_cases` | `case_id`; exclusive Agent or AgentTeam principal, business data, strict choice schema, electorate revision, and version. |
| `governance_electorates` | `(case_id, voter_agent_id)`; ordered frozen eligibility and applicable membership interval. |
| `governance_ballots` | Immutable ballot identity with unique case/voter, strict choice, and timestamp. |
| `migration_requests` | Request identity; moving team, exact original/target parents, acceptance, route evidence, and retained resolution data. |
| `team_topology_events` | Ordered team-position revision; old/new explicit parents, creator provenance, transition kind, exact authority, and notification outbox. |
| `parent_acceptances` | Acceptance identity; exact child and prospective parent, actual case or Agent decision, fingerprint, and explicit boolean. |
| `team_position_cooldowns` | One own-position event per team with duration, timing evidence, and offline-time accounting mode. |
| `resource_decisions` | Bounded model-resource attempt, requesting person, captured scope and position, real parent principal, legal candidates, case, and deadline. |

Governance cases bind immutable choice schemas and electorates to exact eligibility rather than a model execution schedule.

Changing eligibility requires a new case; old ballots remain evidence for their original case only.

Communication ballots derive from governance records rather than a duplicate authoritative communication-ballot table.

Independent-side exemptions retain explicit route evidence and do not invent an approved ballot or remove another side's required principal.

Successful position changes finalize their event time, cooldown, resolution, and exact receipt together after expensive preparation.

## Personal Activity and Model Accounting

| Table | Keys and responsibility |
| --- | --- |
| `agent_activities` | One owner marker with deliberate intent, factual availability, arrival/presentation generations, context version, and current admission. |
| `activity_admissions` | Admission identity, owner, generation, originally requested scope, disposition, and accepted version; partial uniqueness prevents simultaneous live owner admissions. |
| `activity_invocations` | Invocation identity, admission/owner, captured personal/team scope, context version, boundaries, and interruption evidence. |
| `notification_frames` | Frame identity, invocation/owner, context version, arrival cutoff, and sanitized summary references. |
| `model_requests` | Request identity, frame/owner, alias, attempt, input version, factual dispatch/outcome, retry boundary, and request/sequence budgets. |
| `memory_index_requests` | Maintenance request identity, matching beneficiary and segment, source version, alias, bounded dispatch/outcome facts, and input digest. |
| `model_token_claims` | Claim identity with exactly one ordinary/audit/index request FK, alias, prompt/output reservation, and idempotent settlement evidence. |
| `model_availability` | Owner/alias resource boundary, retry sequence, status/reason, budgets, earliest admission, and last-confirmed evidence. |

Personal scope requires no team column, while team scope records a concrete retained team and still requires live authority at access.

An admission may contain several bounded invocations without copying the person.

Frames precede requests, which precede claim-backed dispatch, avoiding circular identity dependencies.

All request profiles use one atomic model-alias quota ledger.

Confirmed-unsent claims refund reservations, factual usage settles once, and potentially sent unknown usage remains conservatively charged after restore.

## Notifications, Suppression, and Sleep

| Table | Keys and responsibility |
| --- | --- |
| `agent_notifications` | Notice identity and owner; exclusive typed source, trusted classification, deduplication key, arrival generation, and committed provenance. |
| `notification_claims` | Notice/request association with frame, reserved/dispatched/presented/uncertain state, and observation time. |
| `chat_reminder_previews` | Notice identity, recipient, exact authorized revision, bounded preview, and independent visibility evidence. |
| `notification_suppression` | Preference identity and owner; exclusive all/Agent/AT source selection, permanent/timed evidence, captured bounds, remainder, and active/expired/removed lifecycle. |
| `notification_summary_items` | Append-only covering-summary/original-notice association, with unique original-arrival coverage. |
| `sleep_plans` | Sleep identity and owner; finite admitted duration, captured bounds, nonnegative saved remainder, and lifecycle; at most one active plan per owner. |
| `sleep_conditions` | Sleep-bound authorized Agent/AT message or owned-execution condition with generation and invalidation evidence. |

Presentation claims do not contain read receipts, invitation attitudes, ballots, or attention acknowledgements.

Permanent suppression has no artificial expiration; timed plans require complete duration evidence within their captured bounds.

Ended preferences cannot return to active under the same identity.

Summary coverage records which ordinary arrivals a source-and-count summary covers without rewriting any source-domain state.

## Conversations and Historical Relationships

| Table | Keys and responsibility |
| --- | --- |
| `direct_relationships` | Canonically ordered Agent pair, bilateral friendship, separately owned blocks/refusals, generation, and directional allowances in `0..3`. |
| `friendship_requests` | Request identity, relationship/endpoints, captured generation, metadata-only request, and factual outcome. |
| `chat_operations` | Owner/operation key; append-only command, canonical request digest, metadata-only result, optional actual invocation, and receipt time. |
| `chat_preferences` | Owner identity and independent team/direct detail preferences. |
| `chat_streams` | Stream identity with exactly one team or direct-relationship owner and next ordering position. |
| `chat_events` | Event identity and stream; unique sequence, kind, actual actor, and timestamp. |
| `membership_intervals` | Interval identity, team/Agent/stream, join and optional leave events; nonoverlap and at most one open pair. |
| `chat_messages` | Message identity, stream, author, publication event, actual model invocation or authenticated Host operation, and optional reply source. |
| `chat_revisions` | Revision identity, message/event, unique positive revision number, immutable Markdown/title, and commit time. |
| `chat_withdrawals` | Withdrawal identity, exact message/revision/author/event, finite positive applied window, and commit time. |
| `chat_message_projections` | Message identity and latest revision/withdrawal pointers with authoritative version. |
| `chat_personal_views` | Owner/message identity, authorizing interval, live/frozen revision and withdrawal, departure cutoff, read watermark, unread override, and personal deletion. |

One team ordering domain includes membership and source changes, so visibility depends on accepted sequence boundaries rather than equal wall-clock timestamps.

Departure freezes the last authorized shared state, and rejoining cannot expose absence-period publications or refresh the old frozen view.

Current views, retained reminders, source projections, and personal read facts remain separately validated.

Withdrawal retains its actual applied duration and latest committed revision without a fixed ten-minute maximum or substitution of later configuration.

An accepted historical friendship request may belong to an older generation and cannot authorize current friendship.

Command receipts validate their original authorized references and digest rather than require their result to equal today's projection.

## Execution and Resource Evidence

| Table | Keys and responsibility |
| --- | --- |
| `executions` | Execution identity and owner, optional actual invocation, captured scope/generation, tool/effects/contract, origin metadata, source provenance, visibility, state, attention, and uncertainty. |
| `execution_attempts` | Attempt identity and execution; unique positive attempt index, retry declaration, actual start, dispatch fact, and external-handle evidence. |
| `execution_payloads` | Protected payload identity and owner/execution; unique input/result kind, immutable content or transient metadata, and digest. |
| `execution_observations` | Append-only observation and optional attempt; ordered per-execution index, health, supported evidence, timestamp, and uncertainty. |
| `execution_controls` | Stop/suspend request identity, authorized requester, operation, acknowledgement, time, and outcome-race evidence. |
| `tool_cooldowns` | Owner/tool key with eligible fault, accounting mode, deadline or saved remainder, and sample evidence. |

Execution declarations, authority, confirmed start/finish times, and provenance cannot be rewritten by later deltas.

Terminal outcomes cannot reverse and background visibility cannot revert to foreground.

Execution states are `queued`, `running`, `completed`, `failed`, and `cancelled`.

Health, attention, stop acknowledgement, and uncertain current outcome remain independent facts.

## Health and Temporary Audit Evidence

| Table | Keys and responsibility |
| --- | --- |
| `health_incidents` | Incident identity, exclusive Agent/AT/ATT subject, stable fingerprint, occurrence count, first/latest time, admitted evidence, and handling state. |
| `health_observations` | Logical response/tool observation identity, actual Agent, detector/category/tool, validity, source identity, and time. |
| `health_detector_states` | Agent/detector/tool streak, samples, observed IDs, last assessment outbox, and version. |
| `health_incident_events` | Append-only occurrence, processing claim, release, and exact-generation acknowledgement history. |
| `audit_runs` | Audit identity, retained subject, temporary team snapshot, predefined electorate/template, generation, shared budget, admission, deadline, and lifecycle. |
| `audit_participants` | Audit/scoped-Agent identity; sanitized identity snapshot, model alias, and frozen position without an ordinary Agent FK. |
| `audit_activity_checkpoints` | Restricted participant invocation/context evidence, intent, and interruption state. |
| `audit_findings` | One immutable structured finding per predefined participant, both health dimensions, admitted references, and timestamp. |
| `audit_model_requests` | Scoped participant request/frame/invocation evidence, alias, bounded attempts, dispatch/outcome, and budgets. |
| `audit_execution_evidence` | Scoped execution, tool/effects, attempt/generation, factual outcome/health/attention, permitted sanitized result, and uncertainty. |
| `audit_chat_evidence` | Ordered restricted audit conversation facts attributable to actual scoped participants. |
| `audit_evidence` | Final admitted references, participant findings, aggregate result, and forensic identity snapshots. |

Audit snapshots preserve evidence without ordinary reusable Agent, team, membership, or private-library registrations.

Restoration does not make those forensic subjects executable or recreate their memory.

Detector windows expire samples rather than incidents; incident records have no TTL or hard dropping limit.

## Journal and Optional Memory

| Table | Keys and responsibility |
| --- | --- |
| `system_memory_events` | Immutable event identity and unique sequence, sanitized payload, personal identity snapshot, and invocation/chat/execution provenance. |
| `agent_memory_segments` | Owner/invocation segment, origin, sanitized recall text and digest, indexing status, attempts, and timestamps. |
| `agent_memory_cards` | Owner/invocation card, segment, title/summary, origin, status/version, and timestamps. |
| `memory_card_tags` | Card/tag association and stable ordering. |
| `memory_card_source_events` | Segment/source-event association and ordering. |
| `retained_memory_references` | Owner/card reference with an explicitly retained note and creation time. |

Optional FTS5 structures are derived search indexes rather than additional authoritative declared tables or a prerequisite for ordinary messaging.

Personal memory remains Agent-owned across memberships, and transient private-read/recall bodies do not become durable content merely because a checkpoint occurs.

## Receipts and Recoverable Publication

| Table | Keys and responsibility |
| --- | --- |
| `commit_receipts` | Operation identity, accepted version, concrete dependencies, authoritative digest, and record digest for exact idempotent replay. |
| `recovery_incidents` | Owner/checkpoint/affected-evidence identity, last-confirmed invocation/execution facts, uncertainty, and publication provenance. |
| `publication_manifests` | Publication identity, source checkpoint, previous/target generation, staged files, recovery operation, status/times, and exact recovery before-images. |

Publication before-images contain only whitelisted primary keys and prior SQL values required to reverse provisional recovery additions and updates.

They support restoration of the complete prior reference graph without compensating business actions.

See [Transactions and Validation](Transactions_and_Validation.md) and [Recovery and Publication](Recovery_and_Publication.md) for acceptance ordering and failure behavior.
