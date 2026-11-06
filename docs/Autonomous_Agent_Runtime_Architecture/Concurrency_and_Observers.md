# Concurrency, Acceptance, and Observers

ATT protects each state domain at its authority boundary without introducing an all-member activity barrier.

## Protection Responsibilities

| Protection | Responsibility |
| --- | --- |
| Personal invocation guard | One person's model-driven activity and Working Context mutation. |
| Short activity-state protection | Owner admission, arrivals, presentation generation, controls, and idle handoff. |
| Runtime/publication gate | Restore eligibility, generation lifetime, accepted local operations, and registry publication. |
| Team relationship/state lock | Ordered membership, shared publication, revisions, withdrawal, and departure-view capture. |
| Pair/lifecycle protection | Direct-contact endpoints, friendship, blocks/refusal, and shared send/edit allowance. |
| Institutional locks | Exact case, electorate, ballot, request, and outcome transitions. |
| Resource reservations and managed leases | Cross-owner conflicts, binding identity, live ACLs, and final physical publication. |
| Short synchronous registry protection | Internally consistent discovery and thread-visible publication. |

Personal checkpoint transactions order activity state before runtime admission and domain-record acceptance.

The following orders describe specific workflows, not a universal total order for every lock in ATT.

Each workflow revalidates captured identities, lifecycle, membership, and source authority after its admission waits.

### Service-Specific Lock Ordering

| Workflow | Acquisition order | Release and revalidation boundary |
| --- | --- | --- |
| Personal checkpoint | `PersonalActivityService.lock` → `manager._runtime_gate` → `DurableRecordService.lock`. | The runner owns the activity lock while accepting its checkpoint; the domain transaction publishes the exact receipt before releasing acceptance protection. |
| Host team dissolution | `team.state_lock` → `manager._topology.transition_lock` → `manager._activity.lock` → domain acceptance. | Recheck the registered team and lifecycle after admission, then commit departure views, membership closure, and parent-loss changes together. |
| Execution admission | `owner.lifecycle_lock` → `manager._activity.lock` → domain acceptance. | Recheck owner lifecycle, captured scope, binding, and cooldown before registration; resource waiting and executor dispatch occur after admission releases these locks. |
| Chat edit or withdrawal | Message-domain lock → `manager._activity.lock` → domain acceptance. | The message lock resolves to `team.state_lock` for team chat or the canonical contact-pair lock for direct chat; recheck author, membership or contact controls, and current revision before acceptance. |
| Governance ballot submission | `manager._governance.lock` → domain acceptance. | Validate the actual actor, strict choice, exact case, and electorate before accepting an immutable ballot; no other voter's model work is awaited. |
| Communication approval outcome | Broker `_transaction_lock` → `manager._governance.lock` → `manager._topology.transition_lock` → `manager._activity.lock` → domain acceptance. | Revalidate the case and actual route, then commit a pending/denied outcome, stale successor, or final Request/Agreement transition without waiting for model work. |
| Migration outcome | `manager._migration.lock` → `manager._governance.lock` → `manager._topology.transition_lock` → `manager._activity.lock` → domain acceptance. | Revalidate exact authority, original/target positions, parent acceptance, Host policy, and cooldown before the position transition. |
| Domain capture | `manager._runtime_gate` → `manager._records.lock` → short synchronous resource/snapshot protection. | Capture the immutable candidate and submit its writer operation without holding synchronous locks over the receipt wait. |
| Accepted domain publication | Resource protection → nonblocking topology acquisition → snapshot protection. | If topology is contended, release resource protection before waiting and retry; publish only the acknowledged operation's records and runtime projections. |

The checkpoint path is implemented in [the personal runner](../../src/ai_team_team/core/manager/activity/runner.py) and [checkpoint service](../../src/ai_team_team/core/manager/activity/checkpoints.py).

[Archive finalization](../../src/ai_team_team/core/manager/messaging/archive.py), [execution admission](../../src/ai_team_team/core/manager/executions/dispatch.py), [message mutation](../../src/ai_team_team/core/manager/messaging/writes.py), and [domain acceptance/publication](../../src/ai_team_team/core/manager/durable_records.py) define the remaining workflows in the table.

[Ballot submission](../../src/ai_team_team/core/manager/governance/submissions.py), [communication outcomes](../../src/ai_team_team/core/broker/approvals.py), and [migration outcomes](../../src/ai_team_team/core/manager/migration.py) define the institutional lock paths.

No short state, domain-record, or synchronous registry lock is held while waiting for model generation, an external executor, retry backoff, or another person's ballot.

Resource authority is released while waiting for contended topology admission and revalidated before registration/publication, avoiding a revocation deadlock.

Remaining genuine synchronous identity dependencies use cycle detection and fair activity-slot handoff.

## Acceptance Before Observation

Domain producers capture operation-local candidate state, validate exact authority, and await the matching accepted receipt before publishing registries or scheduling dependent activity.

Cancelling an observer after acceptance cannot undo the operation or release its mutation protection before settlement.

For example, execution admission first validates a candidate, then acquires owner-lifecycle and activity protection and rechecks authority before submitting its domain delta.

If the observer is cancelled during the writer wait, receipt settlement still determines whether that exact operation was accepted.

An accepted admission publishes its execution registration before protected cleanup completes; rejection leaves no runnable registration, and a returned foreground admission whose observer was cancelled receives the explicit cancellation handling defined by the execution service.

Admission releases its lifecycle/activity locks only after receipt-bound registration and local bookkeeping settle, preserving the boundary for competing coordinated lifecycle operations.

Provisional entities and mail do not become visible through unrelated snapshots or ordinary discovery.

Long operations use task-local nested save suppression only for their own batching; continuing activity uses bounded authoritative checkpoints.

## Isolated Execution Context

Activity, executor, indexing, and callback tasks receive deliberate context rather than inheriting caller authority accidentally.

Activity and execution services retain workers in explicit task registries through completion and owned cleanup rather than relying on garbage collection to preserve pending work.

A detached execution carries its captured identity and revocable authority without retaining an unfinished Native batch, mutable personal Session, or stale dependency chain.

Returning from a tool does not authorize arbitrary child tasks to mutate managed state later.

Already entered atomic local operations may settle, while newly started late accesses must pass generation and live-authority checks.

## Ordered Observational Callbacks

Synchronous and asynchronous callbacks share one ordered event-loop/worker-thread ingress.

`flush_callbacks()` observes events accepted into that ingress before the flush.

Callbacks run in fresh contexts with no inherited Agent or AgentTeam authority.

Each callback has an isolated observation task so its cancellation or exception does not cancel the dispatcher or discard subsequent accepted events.

Synchronous functions run on worker threads and need a thread-safe handoff when notifying an asyncio Event.

Observer failures remain recorded observational failures and cannot invalidate committed state.

Shutdown cancels or detaches uncooperative observers without indefinitely delaying core close, while already accepted persistence settles independently.

Callback fields contain permitted IDs, scopes, transitions, and results rather than private bodies or sensitive arguments.

See [Transactions and Validation](../Database/Transactions_and_Validation.md) and [Performance Measurement](../dev/Performance_Measurement.md) for correctness and measurement boundaries.
