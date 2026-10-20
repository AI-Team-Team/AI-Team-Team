# State Persistence and Multi-Turn Memory

ATT persists mutable runtime state to a versioned SQLite database through a single asynchronous writer.

The public persistence API is asynchronous:

```python
async with ATTManager(root_ai, config, db_path="att.db") as manager:
    # Build teams and run discussions.
    await manager.save_state()          # Full snapshot and commit.
    await manager.flush_state()         # Wait for queued deltas.

restored = ATTManager(rebound_root, config, db_path="att.db")
restored.register_generator_handler(runtime_handler)
await restored.load_state("att.db")
await restored.close()
```

- `save_state(path=None, full=True)` writes a complete snapshot by default and rejects saves throughout state restoration or shutdown, including saves already waiting for runtime admission.
- `flush_state()` waits for every accepted write.
- Persistence errors are always re-raised by `save_state()`, `flush_state()`, or `close()`.
- `close()` flushes, disposes the reused SQLAlchemy engines, and shuts down the persistence worker.
- The asynchronous context manager calls `close()` on exit.

Durable mode is the default and requires an explicit database path.

The Host can explicitly select `persistence_mode="volatile"` without `db_path` for a session that has no restart-recovery promise; permission and ownership rules are unchanged.

The [Phase 1 engineering profile](dev/autonomous_activity/Phase_1.md) describes schema 12 records, exact commit receipts, recoverable publication, and resource-generation leases.

The [Phase 3 messaging profile](dev/autonomous_activity/Phase_3.md) activates incompatible schema 13 for explicit publications, exact chat command keys, private read/detail controls, historical views, friendship periods, and recipient-owned reminder evidence.

The [Phase 4 execution profile](dev/autonomous_activity/Phase_4.md) activates incompatible schema 14 for explicit and detached execution, immutable declaration and source provenance, protected input/result references, factual cancellation, and owner-only result recovery without replay.

The [Phase 2 personal runtime](dev/autonomous_activity/Phase_2.md) atomically checkpoints the sanitized personal window, Journal dependencies, notification claims, and activity progress.

Open Native exchanges are excluded from saved model windows while their issued execution evidence remains retained.

Model requests and quota claims commit before dispatch; sent requests with unknown usage remain conservatively charged after cancellation or recovery.

Explicit saves sample finite sleep and downtime-excluded cooldown remainders, while restore anchors their remaining durations at restoration start.

Restore does not replay an external tool, reconnect to it, or poll it for a fabricated result.

## Incremental single-writer design

Auto-save hooks mark individual agents, Agent identity inboxes, teams, formation requests and invitations, proposals, AgentTeam inboxes, communication requests/approvals/agreements/deliveries, Journal events, memory segments/cards/references, libraries, permissions, managed links, configuration records, and library file paths dirty.

- Each database has one non-blocking cross-process writer lease.
- Constructing a second writer manager for the same path raises `DatabaseOwnershipError` immediately.
- Admission keeps at most one executing delta and one pending delta; later changes merge into the pending entity records without losing their latest values or retaining an unbounded list of futures.

The manager captures a versioned, copy-on-write shallow record and sends it to the writer.

JSON serialization, deep copying, database I/O, and large state assembly run on the background worker.

A delta rewrites only the selected rows.

Replacing one Agent's persisted Working Context does not rewrite another Agent's messages, Journal events, Memory Cards, or retained references.

Memory deltas include the referenced cards, segments, and immutable source Journal events in the same transaction, even when a background indexer runs before the originating discussion's auto-save batch is submitted.

Missing owner identities, provenance teams and their parent/creator dependencies, Private DocLibs, and built-in team DocLibs are inserted as dependencies without rewriting existing Agent-owned state, team topology, or library contents.

- SQLite connections explicitly enable foreign keys, WAL journal mode, and a five-second busy timeout.
- ATT reads schema metadata in read-only mode before running `create_all()`, so an unsupported database is rejected without DDL or other modification.

Long operations batch their changes with a nested, task-local context:

```python
async with manager.suppress_auto_save():
    # Nested scopes merge into this task's outer batch.
    ...
```

The implementation uses `ContextVar`, so concurrent team discussions do not share suppression state.

The outermost scope submits one merged delta.

### Validation and acceptance boundaries

Full SQL validation remains the reference path for restore, untrusted checkpoints, and incremental-validator equivalence tests.

Routine commits reuse accepted, copy-on-write table projections and refresh physical checks from actual writer mutations rather than relying only on snapshot dirty flags.

Cross-row authority rules are shared by both paths and conservatively recheck related collections, including reverse references, current membership intervals, notification presentation, and source ownership.

Volatile commits bulk-check changed record groups without repeatedly replaying every historical row into the validation database.

Database validation falls back to the full reference after connection or database-version changes, out-of-band store mutations, unknown SQL effects, full snapshots, or unmodelled triggers.

Governance dependencies use mapped table names, and derived FTS exemptions recognize only complete known writer statements; a table-name mention in a literal, comment, or CTE never proves a write safe to ignore.

Replacing an active writer's database file is rejected rather than reusing its old connection and validation baseline.

A candidate validation cache becomes reusable only after the real commit succeeds; failed or cancelled preparation cannot publish it, and failed writes invalidate reuse.

The writer may stage SQL changes inside its uncommitted transaction, but validation and exact-receipt checks must finish before the database commit.

Only a successful commit permits runtime publication, cache promotion, and dependent notification dispatch.

These are two execution paths with the same authority requirements, not configurable strict and permissive persistence modes.

This optimization does not change schema version, production request deadlines, cancellation settlement, Agent identity, personal memory, or persistence error propagation.

## Persisted and runtime-only state

The database stores:

- schema version, `ATTConfig`, model metadata, presets, and token usage;
- all active and inactive agents by immutable UUID, lifecycle state, private-library ownership, bounded Working Context, and persistent identity-addressed inbox messages;
- append-only System Memory Journal events with identity snapshots and source provenance, plus optional Agent-owned segments, Memory Cards, normalized tags, retained references, and FTS5 search data;
- ordinary teams with role-neutral `team_id ↔ agent_id` membership rows linked to historical intervals, explicit parent references, AgentTeam inboxes, and proposals;
- consensual formation request projections, normalized content and revision fingerprints, immutable revision snapshots, append-only exact-revision invitation decisions, detached collaborative drafts, creation choices, late-join state, and resulting team references;
- communication requests, ordered approvals, member ballots, directional Agreements, and peer-delivery records;
- team and direct Markdown chat sources, append-only revisions and withdrawal evidence, independently owned personal views, captured reminder previews, exact operation receipts, preferences, and friendship requests and relationship generations;
- identified governance cases with frozen electorates, immutable explicit personal-email ballots, and asynchronous migration requests;
- document-library metadata, ACLs, managed cross-library links, paths, and file contents.

An incremental membership change rewrites the affected team's `team_members` rows without rewriting an already persisted Agent record, Working Context, Journal, Memory Catalog, model binding, lifecycle state, or Private DocLib.

Those rows are derived from the latest accepted open membership intervals after record application, so a coalesced or later progress snapshot cannot reopen a departed relationship.

New membership identities, their Private DocLibs, and proposal replacements publish with the same receipt; ordinary snapshots cannot capture their unaccepted staging state or overwrite a replacement that is still settling.

Departure and archive-finalization transactions freeze exact authorized source references, while later edits and withdrawals update only live views.

Personal-runtime body reads acknowledge only observations included in their accepted Working Context checkpoint.

Cancelled, unreturned Host reads compensate only their own immediately preceding read projection through an exact preparation receipt, preserving earlier read and unread facts without relaxing normal watermark validation.

Withdrawal validation uses the persisted finite positive applied window, not a hard-coded ten-minute cap or a later configuration value.

An accepted historical friendship request remains accepted after its relationship generation changes, without granting current contact authority.

Each audit's supervisory AgentTeam and fresh auditors are fully registered in the running Manager but deliberately omitted from state snapshots, including full saves taken during an audit.

The completed audit's source transcript, debate, and result remain in the System Memory Journal after the temporary team, auditors, and DocLibs are removed.

Insert-only dependency records satisfy identity and provenance references when registered Agents or teams have not yet been written to the database.

Callables and external connections are runtime bindings and are not serialized.

This includes generator handlers, concrete clients, tools, auditors, and callbacks.

## Restore contract

`load_state(path)` requires the current schema version; old databases are not migrated.

It reads persisted model aliases before constructing agents.

Hosts must register direct clients or a generator handler before loading:

```python
manager = ATTManager(runtime_root, db_path="att.db")
manager.register_llm_client("analysis", analysis_client)
manager.register_generator_handler(handler)
await manager.load_state("att.db")
```

- Except for `ManagerDefaultClientAdapter`, every direct client must be registered under exactly one stable alias.
- A `model_name` attribute is accepted only when the same object is registered under that name.
- Saving fails once with all affected agent names when an alias is missing or ambiguous.
- Loading likewise raises `StateRestoreError` listing every missing binding and never substitutes the default model.

Restoration is transactional.

- ATT validates every Agent UUID, identity inbox message, formation request, contiguous revision history, invitation decision, detached draft and publication provenance, member, creator, parent, model alias, DocLib owner, permission, communication principal and state combination, Agreement, peer delivery, Journal sequence, memory ownership and provenance edge, deterministic segment digest, file path, and managed link before publishing anything.
- Multiple membership rows resolve to the same restored Agent object and do not carry team-role metadata.
- Every agent must own exactly one canonical `PDL-<agent_id>` private library; private libraries must be non-public, have no team ACL or managed links, and match the owner's lifecycle state.
- Persisted communication `PROCESSING` states reset to `PENDING` after validation, and a formation draft interrupted in `RUNNING` returns to `PENDING` with an explicit retry-required reason.
- Personal governance emails, eligible voters, round histories, complete tallies, and authoritative communication or migration outcomes are cross-validated; email read state never supplies a missing ballot.
- Pending failover rounds become `EXPIRED` because their original resource invocation did not survive the process interruption; the retained email and choice history are not deleted.
- `load_state()` fails closed while foreground formation, governance submission, migration commit, or detached formation/governance work is active, so restored registries cannot race ongoing authoritative operations.

Before staging or publication, restore drains accepted writes and verifies that its candidate Journal contains every event already committed to the destination database with its original sequence and contents.

Restore validation and immutable-event writes use the same JSON comparison, distinguishing booleans from numbers at every nesting level while ignoring object key order.

A stale or divergent detached snapshot raises `StateRestoreError` without changing the live runtime, DocLib files, or writer health; restore an independent checkpoint database instead of writing an older snapshot back over a newer Journal.

It builds agents and files in a detached manager and a same-filesystem staging directory, recomputes derived team depth, then swaps the DocLib directories and live registries.

Before publication completes, any validation, staging, or publication error restores the original manager and original DocLib trees, or leaves resources fenced if rollback itself cannot safely complete.

A durable journal and publication manifest coordinate directory swaps with SQLite decisions after a process interruption; SQLite and filesystem renames are not one OS-atomic operation.

Managed access is gated during provisional publication, and old DocLib objects cannot mutate a newly published generation.

Cleanup or callback failure after a committed registry switch does not undo the new state.

Runtime tools and callbacks already registered on the host remain runtime-owned.

## Memory compression

When an agent exceeds `max_memory_turns`, ATT summarizes older messages for the active model window while preserving the initial instruction, recent high-fidelity messages, and native tool-call/result boundaries.

The complete sanitized cross-team history remains in the append-only System Memory Journal, while only the compressed Working Context is restored into `agent.messages`.

One shared agent keeps a single identity and memory; calls are serialized by the agent lock, while `ContextVar` records identify the active team and discussion for prompts and team-sensitive tools.

The optional [Selective Episodic Memory](Selective_Episodic_Memory.md) catalog creates one background-indexed card per completed or incomplete business Agent turn and never changes ownership when team memberships change.

## Schema policy

- The current persistence schema version is `14`.
- Compatibility with schema `13` and earlier SQLite layouts is intentionally unsupported.
- Create a new database when upgrading.
