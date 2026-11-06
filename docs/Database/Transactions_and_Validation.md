# Transactions, Receipts, and Validation

ATT accepts domain changes through immutable versioned records, strict validation, and exact commit receipts.

## Database Admission

Durable operation requires an explicit database path and acquires an immediate-failure cross-process writer lease before managed resources are registered.

A second active writer for the same database raises `DatabaseOwnershipError`.

Read-only schema preflight checks the supported version, physical columns, declared constraints, restrictive references, and required indexes before a writable connection or `create_all()`.

Unsupported, incomplete, or corrupt layouts are rejected rather than repaired in place.

A crash-left WAL requiring index reconstruction is inspected through detached files so unsupported state is not modified.

Loading an empty checkpoint does not initialize it or change its journal mode.

Supported writable connections enable foreign keys, WAL, and a five-second busy timeout.

## Immutable Capture and Dependency Closure

Domain producers capture immutable records and copy-on-write containers from one consistent state version.

Worker-side serialization, body hashing, detached validation, and SQL work consume captured values rather than changing live objects.

Insert-only prerequisites include the concrete owner, libraries, teams, source events, intervals, invocations, frames, and other references needed by a first partial checkpoint.

Inserting a missing prerequisite cannot rewrite another person's existing window, a library's contents, or unrelated topology.

Causal personal-mail prerequisites are insert-only, so a delayed dependency or coalesced delta cannot overwrite the recipient's independently accepted read receipt.

Append-only identities reject conflicting bodies, while mutable projections advance by authoritative version.

Equal-version conflicts, regressing ordering cursors, reversed terminal facts, reopened admissions, and stale resurrection fail closed.

Relationship transitions publish their intervals and current projection without changing existing Agent-owned records.

Provisional formation, lifecycle, permission, and summary state remains operation-local until its own authoritative acceptance, preventing unrelated full exports from retaining later rejected changes.

## Bounded Writer and Exact Acceptance

The coordinator retains one executing delta and one coalescible pending delta instead of an unbounded list of completion Futures.

Merging follows captured version order, so an older full snapshot cannot replace newer pending state.

Exact receipt dependencies remain available for every accepted authoritative operation even when deltas coalesce.

`CommitReceipt` associates an operation identity with its accepted version, dependencies, and canonical state digests.

Retrying an accepted operation returns its exact receipt rather than applying its side effects again.

Receipt identity is independent of record ordering, and an invalid operation ID is rejected rather than silently replaced.

Authoritative domain commits await their own receipt rather than flush all unrelated dirty state.

Position transitions bind their accepted timestamp and cooldown inside the actual SQLite transaction after materialization and validation, using an event-loop clock handoff.

Pending-delta merging retains that binding, and the canonical receipt covers its final values.

Rejected clock reads roll back the transaction, while elapsed online time after commit remains counted even when the observer receives its receipt later.

Callbacks and model scheduling are published only after the corresponding required state succeeds.

## Cancellation Settlement

Cancelling an observer does not cancel a transaction already accepted for persistence.

The operation retains its mutation protection until commit or rollback is known, including repeated cancellation and reconciliation-worker waits.

A persistence failure propagates rather than being hidden by a cancelled observer's lost response.

Already accepted local writes and finalizers settle without an arbitrary flush timeout during shutdown.

External model/executor waits and observational callbacks have separate bounded or fenced lifetimes.

## Reference and Incremental Validation

Full SQL validation is the reference path for restore, untrusted checkpoints, and equivalence tests.

Routine commits may reuse accepted table projections and refresh physical validation from actual writer mutations.

Shared cross-row validators enforce ownership, reverse references, current intervals, source projections, request/claim combinations, and institutional authority in both paths.

The [relational constraints](Relational_Constraints.md) and [request/token matrices](Request_and_Token_States.md) state these rules independently of the validator's implementation.

Volatile mode uses the same authority rules and immutable accepted records without claiming SQLite durability.

A validation candidate becomes reusable only after the real transaction commits.

Preparation failure cannot publish its candidate, and failed writes invalidate reuse.

Database/connection changes, out-of-band writes, full snapshots, unknown effects, and unmodelled triggers cause conservative reference validation.

Derived FTS exemptions recognize complete known writer statements rather than table-name mentions in literals, comments, or CTEs.

Replacing an active writer's database file is rejected instead of reusing a stale connection and cache baseline.

Validation and exact-receipt verification finish before SQL commit; runtime publication, cache promotion, and dependent dispatch follow success.

Graph and retained-history checks may scale with related state, so cache reuse is not a universal constant-time guarantee.

See [Performance Measurement](../dev/Performance_Measurement.md) for controlled measurements and equivalence checks.
