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
    Aliases --> Bindings{"All active Agent aliases have a direct client\nor generator handler?"}
    Bindings -- "No" --> Error["Raise StateRestoreError with all aliases"]
    Bindings -- "Yes" --> Validate["Validate UUID references and exactly one private DocLib per Agent"]
    Validate --> Privacy["Reject private public flags, team ACLs, links, and lifecycle mismatch"]
    Privacy --> Stage["Build detached manager and temporary DocLib trees"]
    Stage --> Pointers["Rebuild parent/child pointers and recompute depth"]
    Pointers --> Runtime["Rebind built-in and registered runtime tools"]
    Runtime --> Recovery["Settle required interruption facts in detached state"]
    Recovery --> Prepared["Persist prepared manifest and exact before-images"]
    Prepared --> Files["Publish gated DocLib directories"]
    Files --> Receipt["Commit required recovery facts and publication decision"]
    Receipt --> Publish["Synchronously switch live registries and runtime indexes"]
    Publish --> Ready["Schedule eligible owners and timers after publication"]
    Validate -- "Invalid" --> Error
    Privacy -- "Invalid" --> Error
    Stage -- "Failure" --> Rollback["Discard staging; live manager and files unchanged"]
    Recovery -- "Failure" --> Rollback
    Files -- "Failure" --> Inverse["Restore exact prior records and DocLib trees"]
    Receipt -- "Failure" --> Inverse
    Publish -- "Failure" --> Inverse
    Inverse --> Rollback
```

- SQLite uses foreign keys, WAL, and an explicit busy timeout.
- A second manager or process fails its non-blocking writer lease immediately.
- Schema 16 retains personal, institutional, memory, chat, and execution history and adds suppression lifecycle, source-count summary coverage, and recoverable before-images for required publication changes.
- Restore cross-validates personal emails against cases and voters, resets communication processing states, and expires interrupted failover attempts without treating read receipts as ballots or deleting historical choices.
- Audit-scoped supervisory teams and auditors stay live only during their audit; snapshots exclude their identities and DocLibs, while audit-specific tables retain scoped evidence and results.
- Position events include parent acceptance and cooldown prerequisites; stale projections cannot replace accepted parent edges.
- Health observations, incidents, occurrence generations, scoped audit requests, findings, and results validate before publication.
- Sleep and timed reminder preferences resume saved monotonic remainders from restoration start; expired safeguards dispatch only after publication.
- Affected active owners wake without replaying old external work, while unaffected sleepers and retained dead identities do not activate.
- Dead identities retain historical creators, messages, and private artifacts and cannot be reactivated.
- It intentionally does not migrate old databases.
