# Todo

This document only contains In Progress, Known Issues, and Future Plans.

Any resolved issues should not be stored in this document.

## In Progress

## Known Issues

### Critical

1. **A team can run overlapping discussion sessions.**
   `ATTManager.execute_team_discussion()` sets `team.is_running` as a status flag,
   but it does not acquire a per-team session lock. Concurrent calls can reset the
   same migration counter, consume the same inbox, execute proposals, audit
   overlapping transcripts, and clear `is_running` while another session is still
   active. A team must either serialize discussion sessions or reject a second
   session deterministically.

2. **Model token-limit admission is not atomic.**
   `generate_with_retry()` checks current usage before awaiting the model and only
   records consumption after the response. Concurrent requests can all pass the
   same check and exceed a hard budget. Prompt tokens need an atomic reservation
   before the call, followed by response-token reconciliation and a defined refund
   policy for failures and cancellation. The current post-call update is serialized
   by a normal single event loop, but it is not protected for cross-thread access.

3. **LLM governance approval accepts truthy non-boolean values.**
   The proxied communication, ancestor-approval migration, and lineage-path
   migration policies use `bool(data.get("approved", False))`. For example, the
   JSON value `"false"` is therefore treated as approval. These authorization
   boundaries must accept only the literal JSON boolean `true`; malformed types
   must fail closed.

4. **State restore can leave a partially replaced live manager.**
   `_apply_state_snapshot()` mutates configuration and registries, clears live
   agents/libraries/teams, and rewrites DocLib contents before the complete snapshot
   has been validated. A later error leaves mixed old/new runtime state and partial
   filesystem contents. Missing team members are silently omitted, and persisted
   depth caches are trusted instead of recomputed. Restore needs complete referential,
   topology, model-binding, and file validation before an atomic commit.

5. **DocLib containment does not defend against symbolic links.**
   `_resolve_path()` uses lexical `abspath`/`commonpath` checks, so a symlink below
   the library root can redirect reads or writes outside that root. In addition,
   `replace_all_files()` is documented as atomic but deletes the live directory and
   rebuilds it in place. Restore must reject symlink traversal and publish staged
   directory contents with a crash-safe directory swap.

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
   thresholds, and model token limits accept invalid zero or negative values, and
   runtime assignment is not validated. Team-size enforcement also uses `assert`,
   which disappears under `python -O`. `strict_state_persistence` is persisted but
   currently has no behavioral effect and should either be implemented or removed.

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
   The suite covers incremental writes and a slow-write heartbeat, but not corrupted
   snapshots with rollback assertions, process interruption during restore, symbolic
   link attacks, competing managers/processes, cancellation propagation, bounded
   queue behavior, or long-duration persistence stress.

## Future Plans

1. **Visual Lineage Dashboard**: Build a lightweight web-based viewer to render the active dynamic Agent Team lineages tree, agent roles, real-time thinking states, and debate transcripts.
2. **Human-in-the-Loop Interception Hook**: Extend the tool auditor callback system to support asynchronous human approval prompts before executing destructive or high-cost tools.
