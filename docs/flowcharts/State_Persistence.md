# State Persistence and Recovery Flow

```mermaid
flowchart LR
    Mutation["State mutation"] --> Dirty["Mark entity/path dirty"]
    Dirty --> Scope{"Inside task-local suppression?"}
    Scope -- "Yes" --> Merge["Merge into outer ContextVar batch"]
    Scope -- "No" --> Capture["Capture versioned shallow COW record"]
    Merge --> Capture
    Capture --> Admission{"Writer admission"}
    Admission --> Active["One executing delta"]
    Admission --> Pending["One coalesced pending delta"]
    Pending --> Active
    Active --> Worker["Worker: deep copy, JSON, files and SQLite"]
    Worker --> Commit["Incremental transaction commit"]
    Flush["await flush_state()"] --> Admission
```

```mermaid
flowchart TD
    Open["Claim exclusive writer lease"] --> Preflight["Read schema version before DDL"]
    Preflight --> Load["await load_state(path)"]
    Load --> Version["Validate schema version"]
    Version --> Aliases["Read persisted model aliases"]
    Aliases --> Bindings{"All aliases have a direct client\nor generator handler?"}
    Bindings -- "No" --> Error["Raise StateRestoreError with all aliases"]
    Bindings -- "Yes" --> Validate["Validate UUID references and exactly one private DocLib per agent"]
    Validate --> Privacy["Reject private public flags, team ACLs, links, and lifecycle mismatch"]
    Privacy --> Stage["Build detached manager and temporary DocLib trees"]
    Stage --> Pointers["Rebuild parent/child pointers and recompute depth"]
    Pointers --> Runtime["Rebind built-in and registered runtime tools"]
    Runtime --> Publish["Publish DocLib directories and swap live registries"]
    Publish --> Ready["Manager ready"]
    Validate -- "Invalid" --> Error
    Privacy -- "Invalid" --> Error
    Stage -- "Failure" --> Rollback["Discard staging; live manager and files unchanged"]
    Publish -- "Failure" --> Rollback
```

- SQLite uses foreign keys, WAL, and an explicit busy timeout.
- A second manager or process fails its non-blocking writer lease immediately.
- Schema 7 stores autonomous communication records together with the separated Working Context, append-only Journal, optional episodic-memory catalog, source provenance, retained references, and FTS5 index.
- It intentionally does not migrate old databases.
