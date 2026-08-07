# State Persistence and Recovery Flow

```mermaid
flowchart LR
    Mutation["State mutation"] --> Dirty["Mark entity/path dirty"]
    Dirty --> Scope{"Inside task-local suppression?"}
    Scope -- "Yes" --> Merge["Merge into outer ContextVar batch"]
    Scope -- "No" --> Capture["Capture immutable delta"]
    Merge --> Capture
    Capture --> Queue["Single writer queue"]
    Queue --> Worker["Worker thread: file and SQLite I/O"]
    Worker --> Commit["Incremental transaction commit"]
    Flush["await flush_state()"] --> Queue
```

```mermaid
flowchart TD
    Load["await load_state(path)"] --> Version["Validate schema version"]
    Version --> Aliases["Read persisted model aliases"]
    Aliases --> Bindings{"All aliases have a direct client\nor generator handler?"}
    Bindings -- "No" --> Error["Raise StateRestoreError with all aliases"]
    Bindings -- "Yes" --> Validate["Validate every member, creator, parent, ACL, agreement and link"]
    Validate --> Stage["Build detached manager and temporary DocLib trees"]
    Stage --> Pointers["Rebuild parent/child pointers and recompute depth"]
    Pointers --> Runtime["Rebind built-in and registered runtime tools"]
    Runtime --> Publish["Publish DocLib directories and swap live registries"]
    Publish --> Ready["Manager ready"]
    Validate -- "Invalid" --> Error
    Stage -- "Failure" --> Rollback["Discard staging; live manager and files unchanged"]
    Publish -- "Failure" --> Rollback
```

The schema is versioned and intentionally does not migrate old databases.
