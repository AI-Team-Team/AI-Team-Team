# 10. Tracked Execution and Background Tasks

[Back to plan index](README.md).

## 10.1 Unified execution identity

Introduce an execution record before side-effect dispatch, with owner Agent, initiating invocation and tool call, original scope, registered tool identity, protected input reference, attempt identity, retry contract, and runtime generation.

A fast foreground operation and its automatically detached continuation use the same execution identity.

The model-visible BackgroundTask projection applies to explicitly background or detached executions rather than turning every quick read into a visible background task.

Retries remain factual attempts of the admitted execution, while an explicit later rerun after uncertainty creates a distinct execution linked to the earlier one.

Historical tool names, inputs, and external handles remain evidence rather than executable instructions during restore.

Each executor contract defines what operation its terminal result confirms, so returning an external job ID alone does not establish that the remote job completed.

Live execution observation follows only explicitly declared executor capabilities, and restored handles never authorize automatic reconnection or polling.

## 10.2 Declared effects and eligibility

Extend `Tool` with a strict execution contract describing effects, required scope, detachment eligibility, executor binding, cancellation capabilities, and supported health evidence.

Keep retry safety independent from background eligibility because a detachable operation is not necessarily safe to replay.

Suggested effect categories are read-only, artifact-write, authoritative-domain mutation, coordinated self-modification, and undeclared host behavior.

Every built-in tool must explicitly declare whether background execution is allowed, with eligibility reviewed rather than inferred from its function name or Python signature.

Use a whitelist: only an affirmative background declaration allows explicit background initiation or automatic detachment.

Externally registered tools must make the same explicit declaration, and no omitted declaration may grant background permission.

Private DocLib writes are eligible artifact operations, with owner validation, archive checks, path protection, library locking, and atomic file behavior intact.

Changes to identity, instructions, model binding, personal window, or lifecycle remain coordinated through personal activity and cannot become detached self-mutations.

A background operation requiring the owner's later judgment creates an addressed request for that same personal runtime rather than invoke another model-driven copy.

Exact registration-error behavior for an omitted external declaration and executor-safety metadata remain interface questions under D08, not permission to detach undeclared tools.

## 10.3 Dispatch and detachment

1. Use the normal tool view, strict argument validation, authorization, auditor, and execution-admission path for explicit and automatic background execution.
2. Commit execution identity, original scope, and required dependencies before a side effect can begin.
3. Start one registered executor and retain its runtime handle independently of the caller's wait.
4. For foreground execution, wait for completion or the configured detachment threshold without cancelling the underlying executor.
5. If the threshold expires, atomically promote the record to background visibility and return a task-handle observation for the original tool call.
6. If completion wins the race, return the actual completed observation instead of manufacturing a detached task.
7. When a detached execution later ends, commit its factual outcome, protected result reference, attention update, and owner notification together.
8. The owner learns of the result at a safe personal boundary and may explicitly inspect it.

The confirmed threshold remains configurable with a default of 120 seconds.

The confirmed D07 contract measures from actual executor start, excludes queueing, argument validation, and preflight authorization, and includes elapsed execution retry and backoff time without resetting the threshold on each retry.

`asyncio.wait_for()` cancels its awaited operation on timeout, whereas `asyncio.wait()` can stop waiting without cancelling pending tasks, so detachment must separate waiting from execution ownership ([Python waiting documentation](https://docs.python.org/3.11/library/asyncio-task.html#waiting-primitives)).

## 10.4 Native and Text observations

Text and Native modes use the same execution service and structured acceptance or result contract.

A detached Native call receives exactly one normal tool observation containing its task reference, not a later second result appended to an already closed batch.

Complete fast results and task handles together close a valid batch before new notifications enter the next request.

A fatal sibling error requests cancellation and settles authoritative local commits without falsely claiming every side effect stopped.

Persist the original batch references and uncertain execution facts when a caller is interrupted.

The recovered window may use explicit factual interruption observations to make provider ordering valid, but must never fabricate successful tool output or erase evidence that an execution was issued.

## 10.5 Authority and worker fencing

Workers retain owner and original team IDs, not authority borrowed from the owner's later activity scope.

Revalidate lifecycle and real-time resource permissions at protected access and commit points.

Do not retain a mutable Agent window, an open caller transaction, or an unfinished Native batch inside a detached worker.

Use explicit operation leases or runtime-generation tokens to validate every ATT-managed mutation, including file publication and state commits before a final result exists.

Ignoring only late task completion is insufficient because a stale worker could already have changed a DocLib.

Undeclared external mutations remain the trusted host's responsibility rather than a false sandbox guarantee.

## 10.6 Cancellation and factual state

Track cancellation request identity, requester authority, request time, executor acknowledgement, and result races separately from the five execution states.

Pause means suspending execution with supported continuation semantics, while cancel means terminating this execution attempt rather than preserving it for an in-place resume.

Cancelling an operation that has not started prevents dispatch, while a running operation can stop only through its declared cooperative or provider-supported capability.

An asynchronous cancellation request can interrupt a running coroutine at its next opportunity, but is not a generic pause or a guarantee that an underlying external operation stopped ([Python cancellation documentation](https://docs.python.org/3.11/library/asyncio-task.html#task-cancellation)).

A queued operation that never started can be confirmed cancelled, while a running operation becomes cancelled only after a meaningful acknowledgement of stopped execution.

A completed result racing with cancellation stays a confirmed completed result rather than become cancelled merely because cancellation was requested first.

Persist unknown outcomes and attention requirements when an executor cannot acknowledge stopping.

If an execution can neither stop nor cancel and its subsequent state cannot be confirmed, prevent further ATT-managed resource operations and report `Unable to stop or cancel; subsequent state unconfirmed` to the Host.

Do not invent paused or cancelled outcomes, silently transfer ownership, or automatically replay such an execution.

Running synchronous thread work cannot be forcibly cancelled through `Future.cancel()`, so its declared executor must support safe fencing, isolation, or an explicit restore restriction ([Python Future documentation](https://docs.python.org/3.11/library/concurrent.futures.html#concurrent.futures.Future.cancel)).

## 10.7 Health, attention, and summary

Keep the confirmed execution, health, and attention dimensions independently inspectable.

| Dimension | Exact values |
| --- | --- |
| Execution | `queued`, `running`, `completed`, `failed`, `cancelled`. |
| Health | `healthy`, `degraded`, `stalled`, `error`, `unknown`. |
| Attention | `none`, `required`, `acknowledged`. |

Only supported evidence can justify a stalled observation, and quiet operations without heartbeat support are not faulty solely because they remain quiet.

Acknowledging attention does not change execution outcome, source-message read state, or historical retention.

Retain timestamped health evidence and deduplicate notices by execution and evidence transition rather than raw elapsed time alone.

Report unconfirmed post-interruption outcomes separately from freshly observed running tasks.

The proposed summary includes live execution counts, unresolved terminal attention, health counts that may overlap execution counts, and a distinct uncertain-outcome count.

Acknowledged terminal history remains queryable without automatically filling the always-visible summary, as confirmed under D09.

Queries default to the owner's tasks across every membership and never enumerate another person's protected execution bodies.

No automatic retention duration, result deletion, or team-sharing grant is introduced by task acknowledgement or summary omission.

## 10.8 Resource-based execution coordination

Coordinate conflicting resource access across all foreground and background executors, including executors owned by different Agents.

Conflicting operations on the same file are serial, while independent operations on unrelated resources may proceed concurrently.

File movement coordinates both source and target, and multi-resource operations use a deterministic acquisition order with managed links resolved to their actual protected resources.

External tools declare coordination for shared external resources, with conservative execution when independence or safety cannot be established.

The initial implementation does not add optimistic read-modify-write version checks or an overwrite-confirmation gate.

A later serialized write may therefore overwrite content derived from the same older read, and this accepted last-writer behavior must not be described as lost-update prevention.

Serialization, atomic publication, live ACL validation, and stale-worker fencing still apply even though semantic overwrite detection is deferred.

Git-backed Team DocLib collaboration is future work recorded in [Future Plans](../Todo_Autonomous_Agent_Activity_Messaging_and_Background_Tasks.md#git-backed-team-doclib-collaboration).
