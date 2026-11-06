# 1. Scope of the Replacement

[Back to plan index](README.md).

## 1.1 Required outcome

ATT coordinates one continuing personal activity mechanism per Agent, explicit communication, factual execution records, and durable interruption recovery.

AgentTeams remain organizations with membership, topology, collective authority, shared conversations, document libraries, and configurable communication institutions.

An AgentTeam no longer owns an all-member discussion loop or requires every member to answer before another member can continue.

Ordinary model output remains personal unless its author explicitly publishes a message.

Formal approvals use explicit personal ballots under the existing institution rather than inferring a decision from a transcript or model response.

Short-lived supervisory AgentTeams use the same new Agent and AgentTeam mechanisms as ordinary participants, with explicitly restricted health-audit privileges.

Background execution continues an admitted operation without creating another model-driven version of its owner.

Persistent work plans, research, and business judgments remain AI-authored DocLib artifacts.

## 1.2 Concepts and interfaces to remove

- Numbered discussion rounds, previous-round answer injection, all-member response barriers, and automatic transcript publication.
- `execute_team_discussion()`, `execute_team_discussion_detailed()`, their private execution helpers, and round-driven emergency discussion entry points.
- `DiscussionRoundResult`, round-based `DiscussionResult`, `round_number`, and `_active_round_number` in activity results, provenance, callbacks, and persistence.
- `subagent_discussion_rounds`, `emergency_discussion_rounds`, and `max_migrations_per_team_discussion`.
- The assumption that completing a discussion automatically completes delegated work, resolves an alert, or supplies collective consent.
- The whole-session `suppress_auto_save()` boundary as the persistence boundary for ongoing personal activity.
- The team-wide `discussion_lock` as the serialization mechanism for ordinary activity.
- Standalone paths that invoke an existing Agent's model outside its personal activity runtime.

The existing governance concept named `GovernanceRound` represents a frozen ballot solicitation rather than a discussion round, but its name and numbered-round fields should also be replaced with explicit governance-case and electorate-revision terminology.

Technical execution limits remain necessary, but `max_tool_rounds` should become an explicitly named per-invocation tool-batch budget rather than preserve round vocabulary.

A technical invocation boundary, message sequence, electorate revision, or execution attempt must not become a disguised barrier requiring coordinated progress by every member.

## 1.3 Confirmed boundaries that do not change

- One immutable Agent identity and one personal memory across all memberships.
- Membership consent, exact proposal-revision authorization, the four invitation attitudes, and trusted bootstrap separation.
- Strict governance schemas, explicit ballots, complete eligible participation where already required, and fail-closed authorization.
- Communication institutions controlled by `ATTConfig`, with AgentTeam endpoints and explicit `agent_team` or `agent` approval principals.
- Real-time DocLib ACL checks, owner-only Private DocLib access, managed-link restrictions, and atomic file operations.
- Atomic model-token accounting, complete explicit model-input estimation, stable model bindings, and optional episodic memory.
- Single-writer SQLite ownership, bounded pending-delta coalescing, schema preflight, strict persistence failures, and all-or-nothing restore publication.

The confirmed communication default remains `permissive` at every team depth, without requiring an Agreement.

An independent AgentTeam without an organizational parent is permissive on its own side even when `ATTConfig` selects parent or lineage approval.

The exemption removes only that independent endpoint's parent or ancestor approval requirement, while a non-independent counterpart still requires all approvals applicable to its side.

Two independent AgentTeams communicate permissively without requiring a Request or Agreement, and one independent endpoint does not turn an attached endpoint permissive.

Approval institutions retain default queued delivery and bidirectional channels, while active Agreements retain their existing endpoint revocation and configuration-independent lifetime.

Queued communication approval now means addressed personal mail with voluntary handling, not waiting for a normal team discussion or forcing a ballot.

Immediate communication-approval handling through `wake` is deferred to future work and is not part of the initial implementation.
