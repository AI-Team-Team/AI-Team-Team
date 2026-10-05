# Team Governance, Policies & Protocols

This document explains how ATT governs AgentTeam communication, topology migration, token budgeting, model failover, and emergency wakeups.

ATT separates institutional authority from model execution.

`ATTConfig` defines the communication institution, an `AgentTeam` owns communication requests and agreements, and an `Agent` invokes tools with the authority of its current invocation-scoped AgentTeam.

Member order, creator identity, role names, and fallback selection never create governance authority.

## 1. The Team Inbox & Communication Protocols

Every `AgentTeam` maintains a `message_inbox` for incoming messages, governance requests, and escalation events.

Messages are not inserted into an Agent's active reasoning turn.

`manager.execute_team_discussion()` reads the current inbox at the start of a discussion and adds the relevant items to the discussion context.

Each AgentTeam owns one discussion-session lock.

Normal, emergency, audit, and communication-governance discussions for the same AgentTeam execute serially, while different AgentTeams may continue concurrently unless they share an Agent whose invocation lock is in use.

Peer messages are acknowledged only after a successful discussion.

Failed or cancelled discussions leave peer messages and pending communication approvals available for a later retry.

Normal discussions collect `AgentTurnResult` values.

With the default isolate policy, a member-scoped tool or LLM failure produces an incomplete placeholder, preserves every peer result, marks the discussion `PARTIAL`, and lets that Agent rejoin the next round with a fresh tool-correction budget.

Strict communication, migration, full-member ballot, and parent-failover discussions require complete turns; any incomplete member keeps the governance action pending and cannot authorize from a partial transcript.

### Inbox Summarization

`inbox_summarize_threshold_chars` controls when a large inbox is summarized before prompt injection.

UNKNOWN audit alerts have no TTL and no hard capacity limit.

Stable fingerprints merge repeated UNKNOWN alerts while preserving occurrence counts and first/last timestamps.

A discussion marks an UNKNOWN alert as processing and removes it only after success; failure or cancellation returns it to pending.

Operational degradation alerts use the same durable lifecycle when `operational_degraded_escalation_mode` is `"queue"` or `"wake"`.

Content health and runtime health are independent, so an otherwise healthy transcript may still produce operational `DEGRADED` because one member turn was incomplete.

## 2. Peer Communication & Negotiation Broker

`NegotiationBroker` coordinates the communication policy, persistent requests, approvals, agreements, delivery records, and audit events.

The broker never uses member order, creator identity, or Root AI fallback to infer AgentTeam authority.

Any active member may invoke a communication tool for its current invocation-scoped AgentTeam.

The public tools do not accept sender, policy, direction, mode, or approval-principal overrides.

The available tools are:

* `send_peer_message(team_id, message)`
* `request_peer_communication(team_id, rationale)`
* `revoke_peer_agreement(agreement_id, reason)`
* `list_peer_requests(status="pending")`
* `list_peer_agreements(active_only=True)`

Under an approval policy, `send_peer_message()` returns `NO_AGREEMENT` until a matching active channel exists and does not create a request implicitly.

Under the permissive policy, `send_peer_message()` delivers directly without creating an implicit Agreement.

Durable message and inbox records commit before `DELIVERED` is returned.

Communication Agreements do not grant DocLib, managed-link, or file access.

## 3. Inter-Team Communication Policies

`ATTConfig.communication` is a strict Pydantic discriminated union with `extra="forbid"` and assignment validation.

The selected policy applies to every AgentTeam at every topology depth.

### A. Permissive Policy (`"permissive"`)

Authenticated AgentTeam members may deliver peer messages directly.

No approval request or Agreement is required.

### B. Parent Approval Policy (`"parent_approval"`)

The sender and recipient parent principals must all approve a persistent channel.

An ordinary parent is an `ApprovalPrincipal(kind="agent_team", ...)`.

The parent of a top-level AgentTeam is the Root AI as an explicit `ApprovalPrincipal(kind="agent", ...)`.

Duplicate parent principals are removed.

### C. Lineage Approval Policy (`"lineage_approval"`)

The sender's request is the sender AgentTeam's consent.

The recipient, every intermediate AgentTeam on the unique route, and the Root AI Agent when the route crosses top-level branches must approve.

### D. Request Delivery and Direction

`request_delivery="queue"` places AgentTeam approvals in their inboxes for the next normal discussion.

Agent principals have no AgentTeam inbox, so their approvals are delivered directly to their personal Agent inbox and notified through a detached ordinary interaction.

`request_delivery="wake"` schedules an AgentTeam governance discussion immediately while still respecting that AgentTeam's discussion lock.

`direction="one_way"` creates a source-to-target channel.

`direction="bidirectional"` creates a channel usable by both endpoints.

### E. Approval Decisions

An AgentTeam decision freezes the active membership at discussion start and requires one valid ballot from every frozen member.

After a complete governance discussion, ATT persists a voting round and delivers a personal voting email to each frozen member.

Each Agent receives a normal-context notice identifying `open_agent_mail()` and `submit_governance_choice()` rather than a separate model call with a generic ballot persona.

The same Agent's personal instructions, working memory, message history, and invocation lock apply to this activity.

Opening the email and submitting a choice are voluntary separate operations; the AgentTeam session lock is released while personal responses are outstanding.

Strictly more than half JSON literal `true` ballots approve, and strictly more than half JSON literal `false` ballots deny.

A tie, membership change, missing ballot, invalid ballot, model error, incomplete discussion, or cancellation keeps the Approval pending.

An Agent principal decides under that Agent's invocation lock and cannot be replaced by another Agent.

The Root Agent uses its own personal inbox and ordinary interaction context without a fabricated AgentTeam.

Only the JSON literal `true` grants approval.

Strings, numbers, null, missing fields, and extra fields are invalid governance results.

An accepted ballot is immutable within its identified round, and resubmitting the same choice is idempotent.

A tie or changed electorate can start a new identified round while retaining the preceding round, emails, and public choices.

### Personal Email Is Not a Ballot

`open_agent_mail(message_id)` neither marks the message read nor votes.

`mark_agent_inbox_read()` changes only the read receipt, and `submit_governance_choice(round_id, choice)` changes only the ballot and public response history.

`list_governance_requests()` keeps unanswered pending requests discoverable even after their emails are marked read.

The four team-formation attitudes remain `accepted`, `declined`, `explicitly_ignored`, and `no_response`; explicit `None` withholds a public attitude and still projects to `no_response`.

Those attitudes are independent of email states and do not become a universal governance vocabulary.

Communication and migration use strict boolean choices, parent failover uses eligible model aliases, and membership proposals keep `Agree`, `Disagree`, and `Abstain` with their existing rules.

Optional episodic memory is not required for voting, and ATT does not automatically read a private DocLib to prepare a choice.

### F. Request and Agreement Lifecycle

`request_peer_communication()` creates a durable `CommunicationRequest` under an approval policy.

Each request stores its endpoint AgentTeams, initiating Agent audit metadata, rationale, direction, immutable policy snapshot, ordered principals, individual Approvals, ballots, route fingerprint, state, and timestamps.

Equivalent pending requests reuse the existing request ID.

An explicit denial marks the request `DENIED` and cancels unfinished Approvals.

Temporary failures and cancellations return the affected Approval to `PENDING`.

Before final approval, ATT recomputes the relevant route fingerprint.

A changed route marks the old request `STALE` and creates a successor using the stored policy snapshot.

An approved request creates one durable `CommunicationAgreement` in the same persistence transaction.

An Agreement remains active across later policy and topology changes until either endpoint revokes it.

For the detailed state machine, see [Autonomous Communication Governance](flowcharts/Autonomous_Communication_Governance.md).

## 4. Migration & Reorganization Policies

Dynamic topology migration is requested through `request_migration()` and governed by `migration_policy`.

### A. Permissive Policy (`"permissive"`)

The manager may commit the migration after topology validation without a governance decision.

### B. Ancestor Approval Policy (`"ancestor_approval"`)

The explicit current-parent, target-parent, and Least Common Ancestor principals decide, with duplicates removed.

### C. Lineage Path Policy (`"lineage_path"`)

Every explicit principal along the affected lineage path decides.

Ordinary topology authorities are AgentTeam principals, while a root-level authority is the Root AI Agent principal.

AgentTeam principals use full-member personal-email ballots, and the Root AI Agent submits its own explicit personal-email choice.

The API returns a `MigrationOperationResult` with a durable request ID and `PENDING` status while approvals are outstanding instead of waiting inside the initiating tool invocation.

`inspect_migration_request(request_id)` lets the moving, target, or original-parent AgentTeam inspect progress without granting authority to decide for another principal.

Authorization runs outside the topology lock.

Before committing, the manager reacquires the topology lock and revalidates the parent relationship, cycle constraints, migration count, and authorized path.

## 5. Token Budget & Failover Policies

Configured model token limits are hard quotas.

Before each model attempt, ATT atomically reserves the estimated prompt, system instruction, transmitted tool-definition, and maximum output tokens.

The estimate covers explicit ATT request components without attempting to reproduce provider-internal framing or billing details.

Settlement charges reported usage when available, refunds unused output capacity, and conservatively accounts for sent failures or cancellations.

Failover reads the same atomic ledger, including active reservations.

A token limit of `0` disables the model alias.

### A. Failover Routing Strategies

* **Auto (`"auto"`)**: Selects an explicitly bound compatible alias with available quota.
* **Parent (`"parent"`)**: Requests a model choice from the explicit parent principal.
* **None (`"none"`)**: Performs no model failover.

For parent failover, an AgentTeam principal discusses the choice and every member submits a valid model-alias ballot.

Strictly more than half of the ballots must select the same eligible alias.

At the top level, the Root AI Agent receives a personal model-selection email and explicitly submits an eligible alias through its ordinary tools and memory context.

Timeout, lock conflict, invalid output, missing majority, model failure, or unavailable authority fails closed without falling back to `auto`.

`parent_failover_timeout_seconds` defaults to `120` and must be positive.

The bounded failover attempt expires after timeout, caller cancellation, shutdown, or process interruption; a late reply cannot change the replacement client after that attempt ends.

Expiration closes execution authority but retains the email, accepted public choices, and personal memory.

## 6. Code Configuration Example

Communication policy is configured once in `ATTConfig` and cannot be changed by a communication tool invocation.

```python
from ai_team_team import (
    ATTConfig,
    ATTManager,
    Agent,
    ParentApprovalCommunicationConfig,
)

config = ATTConfig(
    communication=ParentApprovalCommunicationConfig(
        request_delivery="queue",
        direction="bidirectional",
    ),
    migration_policy="lineage_path",
    failover_policy="parent",
    parent_failover_timeout_seconds=120,
    model_token_limits={"reasoning": 50_000},
    model_max_output_tokens={"reasoning": 2_048},
)

root_agent = Agent(name="Root_AI", role="Architect")
manager = ATTManager(root_ai=root_agent, config=config)
```

## 7. Emergency Wakeup Protocol

Emergency wakeups allow critical child failures and supervisory anomalies to schedule a parent AgentTeam discussion.

Emergency discussions use the same discussion-session lock as normal and communication-governance discussions.

### A. Trigger Conditions

Emergency wakeups may be triggered by:

* `"child_failure_escalation"`
* `"escalation_spawn"`
* `"audit_unknown_escalation"` when `audit_unknown_escalation_mode="wake"`
* `"operational_degraded_escalation"` when `operational_degraded_escalation_mode="wake"`

When `enable_emergency_wakeup=True`, an idle AgentTeam is scheduled immediately and a running AgentTeam keeps the alert queued.

### B. Active and Deferred Scheduling

With an active event loop, ATT schedules `execute_emergency_discussion()` as an asynchronous task.

Without an active event loop, ATT stores a plain deferred call specification for `flush_deferred_tasks()` and does not retain an un-awaited coroutine object.

### C. UNKNOWN Audit Failures

`audit_unknown_escalation_mode="wake"` schedules an immediate parent discussion, while `"queue"` waits for the next normal discussion.

Emergency discussions created by UNKNOWN audit failures or operational degradation skip that round's supervision, and identical active wakeups are deduplicated, preventing recursive supervision or failure storms.

Root-level anomalies are emitted through system events and callbacks.
