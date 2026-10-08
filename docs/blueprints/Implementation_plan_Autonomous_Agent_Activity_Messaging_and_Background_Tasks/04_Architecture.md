# 4. Proposed Architecture and Ownership

[Back to plan index](README.md).

## 4.1 Service boundaries

The service names and package paths below are proposed implementation boundaries.

| Proposed component | Responsibility | Explicit non-responsibility |
| --- | --- | --- |
| `core/manager/activity/` | Personal admission, serial invocation, continuation, scope transitions, and technical availability. | Business completion, team leadership, or per-team copies of a person. |
| `core/manager/notifications/` | Durable event references, wake eligibility, presentation receipts, and lost-wakeup prevention. | Storing every conversation body or casting domain decisions. |
| `core/manager/messaging/` | Team streams, direct streams, read state, previews, and authorized history queries. | Communication Agreement policy or DocLib grants. |
| `core/manager/relationships/` | Friendship, requests, refusal, individually owned blocks, and stranger allowances. | Team membership or private-resource sharing. |
| `core/manager/executions/` | Execution admission, handles, detachment, cancellation requests, health observations, and protected results. | Independent model activity on behalf of an owner. |
| `core/manager/recovery/` | Derive interruption evidence, prepare protected notices, and build post-publication activation plans. | External-status discovery or replay of old business execution. |
| Existing governance and formation services | Preserve institutional consent and apply authoritative outcomes exactly once. | Running their own Agent invocation loops. |
| Existing supervision and alert services | Health evidence, temporary audit-team lifecycle, deduplication, and explicit incident handling. | Business-progress evaluation. |
| Existing state, restore, library, and discovery services | Authoritative transactions, publication, live access control, and public projections. | Inferring permissions from friendship or chat. |

```text
Committed source records
    ├── Team conversation messages
    ├── Direct personal messages
    ├── Personal mail and governance references
    └── Execution outcomes and protected system notices
                │
                ▼
       Durable notification admission
                │
                ▼
   One personal activity runtime per agent_id
       ├── One coordinated model activity
       ├── Explicit communication tools
       ├── Existing DocLib and memory tools
       └── Validated execution admission
                      │
                      ▼
          Independent non-self-mutating executor
                      │
                      └── Committed result → owner notification
```

## 4.2 Runtime and durable state

Live queues, model clients, tool callables, coroutines, Futures, locks, and timer handles remain runtime bindings.

Persistent records contain identities, immutable inputs or protected references, factual transitions, scopes, evidence, and delivery progress.

A process-local queue is a scheduling optimization over committed records, not the only record that accepted information exists.

Use a manager-owned ready queue and admission tracking keyed by `agent_id` rather than one always-running coroutine for every team membership.

Workers must use explicitly seeded execution context rather than inherit a caller's mutable auto-save batch, unfinished Native batch, or obsolete dependency chain.

Python copies the current task context by default, so isolated task creation must supply a deliberate context and retain strong task references through completion ([Python task documentation](https://docs.python.org/3.11/library/asyncio-task.html#creating-tasks)).
