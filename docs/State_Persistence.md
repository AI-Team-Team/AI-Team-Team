# State Persistence and Multi-Turn Memory

ATT persists mutable runtime state to a versioned SQLite database through a
single asynchronous writer. The public persistence API is asynchronous:

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

`save_state(path=None, full=True)` writes a complete snapshot by default.
`flush_state()` waits for every queued write. `close()` flushes, disposes the
reused SQLAlchemy engines, and shuts down the persistence worker. The
asynchronous context manager calls `close()` on exit.

## Incremental single-writer design

Auto-save hooks mark individual agents, teams, proposals, inboxes, agreements,
libraries, permissions, configuration records, and library file paths dirty.
The manager captures an immutable delta and sends it to one writer queue.
SQLite and document-file I/O run outside the event-loop thread. A delta
rewrites only the selected rows. Replacing an agent's bounded message history
does not rewrite another agent's messages.

Long operations batch their changes with a nested, task-local context:

```python
async with manager.suppress_auto_save():
    # Nested scopes merge into this task's outer batch.
    ...
```

The implementation uses `ContextVar`, so concurrent team discussions do not
share suppression state. The outermost scope submits one merged delta.

## Persisted and runtime-only state

The database stores:

- schema version, `ATTConfig`, model metadata, presets, and token usage;
- all registered agents and their bounded message histories;
- teams, membership, lineage, migration counters, inboxes, and proposals;
- broker agreements;
- document-library metadata, ACLs, paths, and file contents.

Callables and external connections are runtime bindings and are not
serialized. This includes generator handlers, concrete clients, tools,
auditors, and callbacks.

## Restore contract

`load_state(path)` requires the current schema version; old databases are not
migrated. It reads persisted model aliases before constructing agents.
Hosts must register direct clients or a generator handler before loading:

```python
manager = ATTManager(runtime_root)
manager.llm_clients["analysis"] = analysis_client
manager.register_generator_handler(handler)
await manager.load_state("att.db")
```

If any named alias lacks a direct client and no generator handler can serve
it, loading raises `StateRestoreError` listing every missing alias. ATT never
silently substitutes the default model.

Restoration rebuilds agents, physical document files under
`config.workspace_root/.att_doc_libs`, teams, parent/child pointers, tools,
permissions, proposals, inboxes, and agreements. Runtime tools and callbacks
already registered on the host remain runtime-owned.

## Memory compression

When an agent exceeds `max_memory_turns`, ATT summarizes older messages while
preserving the initial instruction, recent high-fidelity messages, and native
tool-call/result boundaries. The subsequent agent delta rewrites only that
agent's bounded message window.

## Schema policy

The current persistence schema version is `2`. Compatibility with earlier
SQLite layouts is intentionally unsupported. Create a new database when
upgrading from an earlier schema.
