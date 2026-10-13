# Phase 1: Durable Primitives and Publication Safety

## Scope

Phase 1 installs schema 12 and the common durable record, receipt, publication, and resource-generation foundations required by the governing implementation plan.

It does not implement personal activity scheduling, chat tools, registered background execution, complete recovery activation, or the institutional adapters that remove numbered discussions.

The existing runtime remains intermediate branch code until those later phases replace its producers and public APIs, not a selectable compatibility mode for the final architecture.

## Durability and Ownership

`ATTManager(..., db_path="att.db")` uses durable mode by default and claims a non-blocking cross-process writer lease before registering managed resources.

`ATTManager(..., persistence_mode="volatile")` requires no database path and retains authority checks without promising restart recovery.

The Host selects this mode; no Agent tool accepts a durability override.

Schema version, physical columns, declared checks, restrictive foreign keys, and required indexes are inspected before any writable connection or `create_all()` call.

Unsupported or incomplete layouts are rejected rather than repaired, including crash-left WAL inspection without modifying an unsupported checkpoint.

Loading an empty checkpoint rejects it without initializing tables or changing its journal mode; schema initialization belongs to the write path.

Supported connections explicitly enable foreign keys, WAL, and a five-second busy timeout.

## Immutable Records and Exact Receipts

The [activity table package](../../../src/ai_team_team/database/models/activity/) defines the new relational domains listed in [Schema 12](Schema_12.md), while cases, electorates, and ballots use the retained governance model package.

The trusted [record service](../../../src/ai_team_team/core/manager/durable_records.py) accepts deeply immutable `DomainRecord` values and retains a copy-on-write index.

It captures concrete prerequisite closure, inserts missing ordinary owner dependencies without rewriting existing people, and keeps captured authority immutable while permitting versioned factual progress.

Append-only conflicts, equal-version conflicts, reopened admissions, changed confirmed invocation endings, reversed terminal execution outcomes, and regressing ordering cursors fail closed.

Membership checkpoint capture produces ordered join/leave facts and distinct intervals while changing only the team's current relationship projection, never Agent-owned identity, memory, or files.

Volatile sessions use the same relationship producer for automatic mutations and authoritative local commits, including consensual creation and late joins, without creating a database or writer queue.

Relationship changes are recorded even inside nested save suppression, so leaving and rejoining remains two distinct intervals rather than an unchanged current pair.

Provisional formation and draft-publication batches defer relationship facts until their authoritative local commit, so a rolled-back team cannot leave orphaned history or erase an independently committed record.

Existing concrete history references prevent permanent deletion of their owner in both modes; retention and archival preserve that identity and remain available.

Registered chat stream IDs are opaque and remain unchanged through checkpoint export, restore, and later membership updates.

Current-member projections include their concrete stream, interval, and join-event prerequisites even when those records were already captured in memory, so a first partial export does not depend on an earlier full checkpoint.

Current relationships and open historical intervals must agree in both directions, and individual `leave` events must identify the departing Agent.

A `dissolve` event may close several intervals without impersonating each member.

Full detached checkpoints require every current interval, while volatile reference-only deltas validate captured history against current relationships without fabricating missing intervals.

The later chat phase supplies the shared live publication ordering service and its public visibility queries.

Snapshot capture freezes containers and retains immutable text references; JSON serialization, body hashing, detached validation, and database work run on workers rather than reading changing runtime objects there.

The writer still has one executing delta and one coalesced pending delta, with exact receipts preserved for each accepted authoritative operation.

Coalescing uses captured state-version order rather than arrival order, so an older full snapshot cannot replace a newer pending delta.

`CommitReceipt` records operation identity, version, durability, prerequisite identifiers, and a domain-value digest for idempotent retry after a lost response or restore.

Retry identity is independent of record order, and explicitly invalid operation IDs fail before acceptance rather than generating replacement identities.

An awaited domain commit does not require flushing every unrelated pending mutation.

Notification observers receive only committed notice and operation IDs, never the source body.

Event-loop and worker-thread observations share one ordered ingress, and `flush_callbacks()` includes observations accepted into that ingress before the flush.

Observers execute in a fresh context rather than inheriting Agent or AgentTeam invocation authority, and an observer-raised `CancelledError` does not discard subsequent events.

Each callback executes in its own observation task, so calling `current_task().cancel()` cannot cancel the ordered dispatcher or strand an in-progress flush.

Shutdown cancels the dispatcher and its current observation without waiting indefinitely for an extension that suppresses cancellation, and late observer exceptions remain observational.

Repeated caller cancellation does not cancel an accepted transaction or release its mutation protection before commit or rollback is known, and a write failure takes precedence over a cancelled observer's lost response.

The same settlement rule applies to directory reconciliation workers, so cancelled restore callers retain publication protection until the worker finishes and cannot hide its failure.

## Publication and Mutation Leases

Restore reads a detached checkpoint and validates ordinary bindings, references, private ownership, historical intervals, cases, ballots, frames, captured scopes, dedicated audit identities, and source ownership before directory reconciliation or staging publication.

Strict integer versions, finite timestamps, integer-backed boolean flags, and receipt JSON shapes are checked on the worker before publication; corrupt values are never silently coerced into valid authority.

It stages restored files on the same filesystem and records a fsynced namespace journal plus a durable publication manifest before the first directory swap.

Managed resource access is gated while files are provisional, and a short namespace writer lease serializes competing publishers.

The durable publication decision and recovery additions commit before the synchronous registry switch, without an intervening observer or external dispatch.

A live failure restores original registries, files, and unobserved provisional recovery additions, or retains a fail-closed resource fence if rollback cannot safely complete.

A restart reconciles prepared versus published directory decisions before external work is admitted, without treating SQLite commits and filesystem renames as one OS-atomic operation.

Cleanup or callback failure after publication is observational and leaves the committed new generation intact.

Publication generations continue from checkpoint evidence instead of restarting at one, and loading into a volatile Host adopts durable mode only after successful publication.

Managed DocLib operations capture a generation lease and revalidate registration, active ownership, current membership, live ACLs, and archive status at the final destructive boundary.

Permission, membership, and private lifecycle changes share the short resource guard with those commits, without holding an asynchronous lock over external I/O.

An active managed operation prevents restore publication; shutdown fences late workers without waiting indefinitely for an external executor.

Shutdown drains already accepted local state operations from early restore through publication before closing the writer, then finishes queued persistence workers before disposing engines and releasing database ownership.

Old DocLib objects cannot access or mutate a newly published generation, and ordinary callbacks contain no private file body.

Shared chat source projections must exactly match committed withdrawal facts, and a confirmed withdrawal pointer cannot be cleared or replaced by a later delta.

This check applies to the writer and detached restore validator without retroactively changing frozen recipient views, read evidence, or previously captured reminder previews.

Independent writer managers should use separate managed workspaces; the namespace publication lease is not a general cross-process executor coordinator or protection against arbitrary trusted-Host filesystem edits.

## Audit, Quota, and Initial Recovery

Dedicated audit tables retain scoped identity and model snapshots without creating ordinary persisted Agents, memberships, teams, inboxes, or Private DocLibs for temporary auditors.

Ordinary, audit, and optional-index request records use concrete provenance references and the same atomic model-alias quota ledger.

All three profiles share dispatch/outcome validation at record capture and checkpoint validation.

An `unsent` request has a `pending` outcome; confirmed local failure or cancellation uses `confirmed_unsent` with `failed` or `cancelled`.

Sent and unknown-sent requests retain independent pending, completed, failed, cancelled, or uncertain outcomes, so uncertainty does not erase confirmed outcome evidence.

Claims reserve prompt and output budgets before a future dispatcher may send, settle idempotently against factual usage, refund confirmed-unsent claims, and keep uncertain sent or unresolved reservations charged across restore.

A zero token limit disables the model even when the estimated prompt and requested output budgets are both zero.

These are common-service foundations; routing all model producers through durable request frames and claims belongs to Phase 2 and the institutional adapters.

The initial `RecoveryPlan` derives protected, stable-key notices for unfinished ordinary invocations and queued/running executions, preserves their last confirmed evidence, and excludes inactive owners from activation candidates.

Repeated load does not issue the same incident again, and no historical external handle is automatically replayed, polled, or reconnected.

Unaffected sleep plans remain candidates with their saved remainder intact; complete timer anchoring, per-domain interruption handling, acknowledgement, and actual post-publication admission belong to Phase 6.

Existing numbered-discussion provenance is kept only as transitional checkpoint metadata, not fabricated into a durable invocation or model-request identity.

## Verification

The Phase 1 foundation gate was initially completed on 2026-10-12, with fourth-review fixes verified on 2026-10-13.

All 98 Phase 1 tests and the complete 544-test regression suite pass, including a fresh branch-coverage run reporting 81 percent against the existing 70 percent baseline.

The review adds six regressions for empty checkpoints, repeated reconciliation cancellation, failure precedence, early-restore shutdown, and disposal of engines created by already queued preparation.

The second review adds seven regressions for order-independent replay, explicit operation identity validation, stable membership stream references, out-of-order full snapshots, corrupt numeric evidence, malformed receipts, and disabled zero-budget quotas.

The third-review follow-up adds 21 regressions for bidirectional membership validation, leave/dissolve identities, immutable invocation endings, all three model-request state matrices, and threaded callback ordering, wake, flush, authority isolation, and shutdown.

The fourth-review follow-up adds 20 regressions for volatile membership producers, provisional rollback isolation, first partial-checkpoint prerequisites and export continuity, shared withdrawal projection consistency and frozen-history preservation, and per-observer cancellation, ordered flush, and bounded shutdown.

Ruff, both consumer mypy contracts, source-distribution and wheel builds, and an installed-wheel save/restore and receipt smoke test pass.

The installed-wheel check verifies schema 12, foreign-key integrity, explicit volatile mode, committed publication, order-independent replay, corrupt numeric rejection, disabled zero-budget quotas, read-only empty-checkpoint rejection, and the absence of model dispatch during foundation operations.

No project-root `.att_doc_libs` directory remains after the tests.

These checks ran locally on macOS with Python 3.13; parsing every Python source with the Python 3.11 grammar is an additional syntax check, not a substitute for the supported Python and operating-system CI matrix.

Run the implemented foundation tests with:

```bash
./venv/bin/python -m unittest discover -s test/test_att/test_autonomous_activity_phase1 -t .
./venv/bin/python -m unittest discover -s test
./venv/bin/ruff check src test typecheck
./venv/bin/mypy typecheck/consumer_contract.py typecheck/activity_contract.py
./venv/bin/coverage run -m unittest discover -s test
./venv/bin/coverage report
./venv/bin/python -m build --no-isolation
```

The Phase 1 package exercises dependency-only writes, immutable capture, receipt identity, coalescing, cancellation, SQL checks, missing-reference and cross-owner corruption, historical membership, dedicated audits, common quotas, every publication decision boundary, process interruption, permission revocation, generation fencing, and close-time publication settlement.

The five separately invoked Phase 0 runtime specifications remain red until their later-phase prerequisites exist; they are not skipped or counted as Phase 1 success.
