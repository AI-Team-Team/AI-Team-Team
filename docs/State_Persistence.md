# State Persistence and Multi-Turn Memory

ATT persists mutable runtime state to a versioned SQLite database through a single asynchronous writer. The public persistence API is asynchronous:

```python
async with ATTManager(root_ai, config, db_path="att.db") as manager:
    # Build teams and run discussions.
    await manager.save_state()          # Full snapshot and commit.
    await manager.flush_state()         # Wait for queued deltas.

restored = ATTManager(rebound_root, config)
restored.register_generator_handler(runtime_handler)
await restored.load_state("att.db")
await restored.close()
```

`save_state(path=None, full=True)` writes a complete snapshot by default. `flush_state()` waits for every accepted write.

Persistence errors are always re-raised by `save_state()`, `flush_state()`, or `close()`.

`close()` flushes, disposes the reused SQLAlchemy engines, and shuts down the persistence worker.

The asynchronous context manager calls `close()` on exit.

## Incremental single-writer design

Auto-save hooks mark individual agents, teams, proposals, inboxes, agreements, libraries, permissions, managed links, configuration records, and library file paths dirty.

Each database has one non-blocking cross-process writer lease.

Constructing a second writer manager for the same path raises `DatabaseOwnershipError` immediately.

Admission keeps at most one executing delta and one pending delta; later changes merge into the pending entity records without losing their latest values or retaining an unbounded list of futures.

The manager captures a versioned, copy-on-write shallow record and sends it to the writer.

JSON serialization, deep copying, database I/O, and large state assembly run on the background worker. A delta rewrites only the selected rows.

Replacing one agent's persisted history does not rewrite another agent's messages.

SQLite connections explicitly enable foreign keys, WAL journal mode, and a five-second busy timeout.

ATT reads schema metadata in read-only mode before running `create_all()`, so an unsupported database is rejected without DDL or other modification.

Long operations batch their changes with a nested, task-local context:

```python
async with manager.suppress_auto_save():
    # Nested scopes merge into this task's outer batch.
    ...
```

The implementation uses `ContextVar`, so concurrent team discussions do not share suppression state. The outermost scope submits one merged delta.

## Persisted and runtime-only state

The database stores:

- schema version, `ATTConfig`, model metadata, presets, and token usage;
- all registered agents and their complete message histories, including each message's source `team_id` and `discussion_id`;
- teams, membership, lineage, migration counters, inboxes, and proposals;
- broker agreements;
- document-library metadata, ACLs, managed cross-library links, paths, and file contents.

Callables and external connections are runtime bindings and are not serialized. This includes generator handlers, concrete clients, tools, auditors, and callbacks.

## Restore contract

`load_state(path)` requires the current schema version; old databases are not migrated.

It reads persisted model aliases before constructing agents.

Hosts must register direct clients or a generator handler before loading:

```python
manager = ATTManager(runtime_root)
manager.register_llm_client("analysis", analysis_client)
manager.register_generator_handler(handler)
await manager.load_state("att.db")
```

Except for `ManagerDefaultClientAdapter`, every direct client must be registered under exactly one stable alias.

A `model_name` attribute is accepted only when the same object is registered under that name. Saving fails once with all affected agent names when an alias is missing or ambiguous.

Loading likewise raises `StateRestoreError` listing every missing binding and never substitutes the default model.

Restoration is transactional. ATT validates every agent, member, creator, parent, model alias, DocLib owner, permission, agreement, file path, and managed link before publishing anything.

It builds agents and files in a detached manager and a same-filesystem staging directory, recomputes derived team depth, then swaps the DocLib directories and live registries.

Any validation, staging, or publication error leaves the original manager and original DocLib trees unchanged.

Runtime tools and callbacks already registered on the host remain runtime-owned.

## Memory compression

When an agent exceeds `max_memory_turns`, ATT summarizes older messages for the active model window while preserving the initial instruction, recent high-fidelity messages, and native tool-call/result boundaries.

Its complete cross-team history remains available for persistence. One shared agent keeps a single identity and memory; calls are serialized by the agent lock, while `ContextVar` records identify the active team and discussion for prompts and team-sensitive tools.

## Schema policy

The current persistence schema version is `4`. Compatibility with earlier SQLite layouts is intentionally unsupported. Create a new database when upgrading from an earlier schema.
