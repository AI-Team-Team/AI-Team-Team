# Schema 15: Round-Free Institutional Evidence

Schema 15 rejects schema 14 and earlier before any writable connection or DDL, without migration or compatibility aliases.

The existing writer ownership, WAL, foreign-key checks, exact operation receipts, staged restore, and publication recovery contracts remain in force.

## New Record Groups

| Table | Evidence |
| --- | --- |
| `resource_decisions` | An independently bounded parent-resource attempt, its actual organizational principal and position revision, frozen candidate aliases, deadline, exact case, and factual resolution. |
| `audit_activity_checkpoints` | Restricted temporary activity context and interruption evidence, referenced by an audit run and scoped participant rather than an ordinary Agent. |
| `audit_findings` | One immutable structured health and operational finding from each predefined scoped auditor, with admitted evidence references and a deadline-checked timestamp. |
| `health_observations` | Deduplicated logical model-response or tool-invocation observations attributed to one continuing Agent identity. |
| `health_detector_states` | Rolling consecutive evidence, category and tool boundaries, resets, and the retained threshold-to-assessment outbox. |
| `health_incident_events` | Append-only occurrence, processing claim, release, and explicit generation acknowledgement evidence. |

## Replaced and Extended Sources

`governance_cases` replaces `governance_rounds`; electorate revisions identify frozen eligibility rather than an execution schedule.

Each AgentTeam electorate binds voters to their exact membership intervals, so departure and rejoining cannot reuse old authority.

Communication approvals reference the exact accepted case, and communication ballot projections are derived from that case's immutable votes.

Communication requests retain canonical side-specific route evidence, position revisions, immutable policy snapshots, and stale/successor references.

An independent-to-independent successor can be resolved without fabricated approvals or an Agreement when the old route becomes exempt.

`teams` stores a positive position revision and exactly zero or one explicit organizational parent, independently of creator provenance.

`team_topology_events` retains a contiguous creation-and-transition history and a deduplicated notification outbox for affected people.

`parent_acceptances` binds attachment to a valid complete case for the exact child, proposed parent, and captured path.

`team_position_cooldowns` records the team's own successful position change with a 600-second duration and the configured offline-time accounting mode.

The position event, cooldown time fields, and migration resolution are finalized together inside their SQLite transaction after expensive preparation, and its exact receipt digest covers those final immutable values.

The coordinator's clock handoff and prepared timestamp templates are runtime commit plumbing rather than new serialized tables or a schema-version change.
Formation requests and optional candidate artifacts preserve explicit Agent or AgentTeam parents without inferring one from membership or creation provenance.

Optional candidates retain initiator-invocation and source-message references rather than a detached deliberation job or discussion transcript.

Memory segments and cards use invocation provenance, and the Journal retains explicit invocation/source references without discussion or turn columns.

## Health and Recovery

An audit subject is an Agent, AgentTeam, or ATT; ATT is not represented by a fabricated Root Agent subject.

Audit runs capture the predefined electorate, permitted evidence, operational decision mode, shared model ledger, admission time, and total deadline.

Temporary audit identities are registered while active but excluded from ordinary Agent, membership, DocLib, and restored-runtime records.

Historical audit identity snapshots and scoped request, execution, conversation, checkpoint, and finding records remain durable after teardown.

Health incidents retain stable fingerprints, occurrence counts, first/latest timestamps, current processing claims, and optional receipt-owned queue/wake delivery plans.

Incidents have no TTL or hard dropping limit, and observation-window expiry never deletes an incident.

Restore interrupts resource attempts and unfinished audits without replaying their ballots, providers, or temporary people.

Claims return to pending with release evidence, and retained alert delivery resumes without rerunning the health assessment.
