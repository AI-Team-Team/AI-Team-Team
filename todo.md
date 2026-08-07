# Todo

This document only contains In Progress, Known Issues, and Future Plans.

Any resolved issues should not be stored in this document.

## In Progress

## Known Issues

### High

1. **Persistence admission and database ownership are not production-bounded.**
   `PersistenceCoordinator` retains every submitted future until `flush()` and has
   no queue limit or pending-delta coalescing. `DatabaseStore` also runs
   `create_all()` before checking the stored schema version, which can add tables to
   an unsupported database before rejecting it. SQLite supplies its own file locks
   and the driver normally supplies a default connection timeout, but ATT does not
   explicitly configure foreign keys, WAL, busy timeout, or logical writer
   ownership when multiple managers/processes target one file.

2. **Fallback model alias persistence can lose client identity.**
   An unregistered client that has no string `model_name` is persisted as
   `"default"`. Distinct runtime clients can consequently restore through the same
   binding. Saving must fail when a stable alias cannot be resolved, or the host
   must register an explicit alias first.

3. **A shared agent has ambiguous team identity.**
   `get_agent_team()` selects the first team containing an agent and caches it on
   `agent._parent_team`. An agent hired into multiple teams can therefore run a
   team-sensitive tool against the wrong or stale team. Team context should be
   invocation-scoped; APIs that require a unique owner must reject ambiguous
   membership.

4. **Numeric configuration validation is incomplete.**
   Retry counts, backoff factors, discussion/tool rounds, migration limits, inbox
   thresholds, and several other numeric settings accept invalid zero or negative
   values. Token limits are validated at construction, but mutable configuration
   containers and later runtime assignment are not validated. Team-size enforcement
   also uses `assert`, which disappears under `python -O`.
   `strict_state_persistence` is persisted but currently has no behavioral effect
   and should either be implemented or removed.

5. **Lifecycle and extension hooks can block indefinitely.**
   `ATTManager.close()` waits for all emergency tasks without a deadline, so a hung
   model call can prevent shutdown. LLM retryability is inferred from a few error
   message substrings, causing programming and validation errors to be retried.
   Synchronous status/log/system callbacks execute on the event-loop thread, so a
   slow callback stalls discussions.

6. **Queued UNKNOWN audit alerts have no lifecycle policy.**
   Active `wake` alerts have an in-memory stable-key deduplicator, but `queue` mode
   has no capacity, TTL, acknowledgement state, or persistent deduplication window.
   A prolonged audit outage can grow inboxes without bound.

7. **Large snapshot materialization can pause the event loop.**
   Database and file I/O run outside the event loop, but `_capture_state_snapshot()`
   performs JSON serialization/deep copying synchronously while holding the snapshot
   lock. Large histories, inboxes, or DocLib indexes can still create latency spikes.

8. **Adversarial reliability coverage is incomplete.**
   The suite now covers missing-reference rollback, late publication rollback,
   native symlink attacks, token-call cancellation, incremental writes, and a
   slow-write heartbeat. It still lacks a complete corruption matrix, abrupt
   process interruption, competing managers/processes, cancellation at every
   awaited boundary, bounded queue behavior, and long-duration persistence stress.

## Future Plans

1. **Visual Lineage Dashboard**: Build a lightweight web-based viewer to render the active dynamic Agent Team lineages tree, agent roles, real-time thinking states, and debate transcripts.
2. **Human-in-the-Loop Interception Hook**: Extend the tool auditor callback system to support asynchronous human approval prompts before executing destructive or high-cost tools.
