# Phase 4: Registered Execution and Background Detachment

## Scope

The manager-owned `ExecutionService` admits registered operations before dispatch and retains execution ownership independently of a person's foreground wait.

Explicit background initiation and automatic detachment share execution records, attempts, protected payloads, resource coordination, cancellation evidence, owner-only queries, and notifications.

The running persistence schema is [14](Schema_14.md), without migration of schema 13 or earlier.

This phase does not implement institutional round removal, ordinary-Agent retained death, or the complete Phase 6 suppression and recovery matrix.

## Ownership and Scope

A background worker has a captured owner, original personal or AgentTeam scope, actual invocation reference where applicable, registered tool, and runtime generation.

Host admission has explicit actor provenance and a nullable invocation reference rather than a fabricated model invocation.

Workers start in a fresh context with only their execution authority and captured actor bindings, not a caller's personal Session, auto-save batch, unfinished Native exchange, or invocation dependency chain.

They never append to an owner's Working Context or invoke another model-driven copy of that owner.

Changing membership does not rewrite identity, memory, model binding, Private DocLib ownership, or task ownership.

Personal artifacts remain personal even when the initiating provenance names a team, while team operations still require the captured team's current membership and live ACLs.

## Admission and Dispatch

Argument validation, registered executor checks, resource resolution, scope validation, and cooldown checks precede execution admission.

Execution identity and a protected or redacted input record commit before a worker can dispatch.

The ordinary tool auditor and classified retry executor still run, and auditor denial creates no fictitious dispatched attempt.

An owner lifecycle gate protects admission against concurrent retirement.

One scheduler coordinates executor capacity and conflicting resources without creating a waiting Task for every queued operation.

Resource-blocked work does not prevent unrelated eligible resources from using available capacity.

The strict `ATTConfig.executions` group provides the following settings.

| Field | Default | Meaning |
| --- | --- | --- |
| `automatic_detachment_seconds` | `120.0` | Positive finite elapsed time from actual executor start, including retry and backoff but excluding initial queue and preflight time. |
| `max_concurrent_executions` | `8` | Positive executor capacity, independent of model and personal-activity capacity. |
| `cancellation_grace_seconds` | `2.0` | Nonnegative finite bound on external stop-hook waiting, not a persistence deadline. |
| `retain_results_after_source_revocation` | `True` | Owner access to already lawfully committed results after source revocation, with current-source revalidation when disabled. |

## Detachment and Provider Exchanges

The foreground observer waits for actual completion or the detachment threshold without cancelling the worker merely because the threshold elapsed.

Completion and promotion serialize their authoritative transitions so an original call gets either its normal result or one `BackgroundTaskHandle`, never two observations.

Automatic detachment preserves execution and attempt identity instead of dispatching a second copy.

A Native batch combines fast results and task handles before another model request begins.

A later background completion commits its terminal fact, protected result, attention state, and owner notification in one transaction rather than append another observation for the old provider call ID.

Every personal model request receives a lightweight task summary in its system instructions, without displacing addressed mail or tool observations in the personal message sequence.

Counts distinguish uncertainty from verified live execution and omit acknowledged terminal history without deleting it.

## Tool and Executor Contracts

`ToolExecutionContract` continues to require an explicit background declaration, effects, scope, mutation safety, cancellation capability, and supported health signals.

Unspecified custom contracts remain foreground-only, and retry safety cannot grant detachment permission.

Undeclared foreground tools retain the current personal Session but acquire conservative global resource exclusion shared with independent executors.

All registered foreground-only tools use the same admission, resource resolution, executor binding, attempt evidence, and result acceptance as background-capable tools while retaining the original personal Session.

A self-modification effect never exempts another declared effect or explicit resource claim from these checks.

Pure self-modification controls do not implicitly reserve shared resources or acquire managed file access; their unresolved source provenance remains opaque unless the Host explicitly supplies a source-free resolver.

Foreground tools that coordinate personal model activity must explicitly declare their self-modifying execution contract; no shared resource reservation may remain held across a nested personal model wait and deadlock downstream tools.

A source-free coordination call keeps its own personal Session, while a nested person's actual invocation owns a separate tool-resource context; the parent execution's revocable authority and dependency edges remain intact.

Built-in file and metadata operations have reviewed declarations, while transitional institutional tools remain foreground-only until their Phase 5 replacements remove nested discussion execution.

`register_executor(name, executor)` binds a runtime-only object implementing `async execute(call)`.

The call carries the execution ID, owner ID, captured scope, validated arguments, registered Tool, and an evidence-reporting callback.

A declared provider or isolated cancellation capability requires a `cancel(execution_id)` hook, whose literal `True` return confirms the declared operation stopped.

The default callable binding cannot promise cooperative cancellation for a synchronous thread.

Host resource resolvers are synchronous, side-effect-free bindings returning strict `ResourceClaim` values.

Unresolved resource independence uses conservative global exclusion rather than inferring safety from a function name.

Tools may select `result_storage="transient"` to keep bodies out of durable execution payloads.

Runtime bindings, callables, coroutine stacks, and external connections are never serialized or reconstructed from historical task records.

## Resources and Privacy

Canonical library/path claims include physical managed-link targets, both move paths, and directory-descendant conflicts.

Admission binds both the resource reservation and source provenance, including link chains inspected by directory listing or link creation.

Bindings are checked after dispatch receipts settle and at actual managed filesystem access and mutation boundaries, where the physical library and path must also fit the accepted reservation.

Retargeting an alias cannot silently substitute an unclaimed source or destination, including a temporary remapping that has already returned to its original spelling.

Physical DocLib operations retain reentrant path exclusion, atomic publication, symlink protections, archive checks, and final live authority checks.

Unrelated writes in the same library can stage concurrently instead of holding an entire-library lock through `fsync`.

Serialization does not detect semantic overwrites derived from older reads, which remain permitted by the confirmed design.

Results acquired and accepted under valid source permissions remain owner-readable by default after a later revocation.

Disabling retained-result access requires current source authority under the original execution scope and cannot borrow later memberships.

Opaque external sources fail closed in restrictive mode because a historical runtime binding is not current source authorization; an explicit empty resource resolution may declare a source-free operation.

Nonempty custom global claims are opaque external provenance too, not evidence that the operation is source-free.

Result preparation revalidates source authority at authoritative acceptance, and a source revoked before that acceptance cannot create a newly retained protected result.

This check applies equally to successful output and exception-derived failure bodies; only a framework-generated constant denial can be accepted without the revoked source content.

Result reads use the existing content-token gate, version checks, and Unicode character continuation, with authority checked again before returning content.

Generic task metadata, summaries, callbacks, and health evidence contain no result body or raw arguments.

Private-file inputs are redacted in execution evidence, and private-read bodies remain transient rather than acquire a new durable copy through task storage.

## Health Observation Ordering

Every genuine health transition receives an ordered observation, even when it returns to an earlier state with the same evidence.

Only consecutive identical nonhealthy reports coalesce; notification suppression cannot leave the current health projection pointing to an intervening error.

Healthy heartbeat and progress samples refresh independently, and a successfully accepted observation updates its live sample even if its caller is cancelled before receiving the receipt.

Timeout decisions and accepted samples share one ordering lock, so a queued timeout cannot overrule a newer accepted heartbeat using an obsolete deadline.

The monitor retains the next unchecked deadline across awaited observation commits and rearms from refreshed samples without clearing a newer update signal.

## Cancellation, Close, and Recovery

A queued cancellation prevents dispatch and can be confirmed immediately.

Running cancellation records a request separately from acknowledgement, and a later factual completion can resolve an earlier unconfirmed stop.

An accepted stop is owned by a cancellation-resistant protocol task, so losing its observer cannot lose queued-stop handoff or a supported provider stop hook.

Once an executor has returned an outcome, local preparation and persistence are finalization rather than external execution; cancellation cannot replace that known result with a speculative cancelled outcome.

Cancelling a synchronous wait does not stop its thread or release its resource reservation before the actual callable returns.

Late synchronous failures use the same typed classification and actual attempt count as immediate failures, without replay, while authoritative framework failures remain observable and propagate from `close()`.

Fatal framework errors from immediate or late stop hooks also propagate rather than become ordinary provider uncertainty, including synchronous stop threads that outlive their observer's grace period.

An unconfirmed stop remains recorded as uncertain, and a factual concurrent completion is retained independently of a failed stop hook.

Unacknowledged executions lose permission to start new ATT-managed mutations and remain explicitly uncertain.

Shutdown rejects new admission, invokes supported stop mechanisms, bounds external waiting, and seals late outcomes before disposing the persistence writer.

Already accepted local commits and required finalizers settle without an arbitrary flush timeout.

Restore refuses live local executors or pending synchronous workers, restores retained facts without executable bindings, and marks unfinished evidence unconfirmed.

Affected owners receive protected recovery notices through the same personal runtime, including owners whose tasks were admitted by the Host while idle.

No restored execution is automatically replayed, reconnected, or polled.

## Verification

Run `./venv/bin/python -m unittest discover -s test/test_att/test_background_tasks -t .` for the focused Phase 4 gate.

The previously red Native-detachment specification now runs in ordinary discovery alongside Text, resource, privacy, cancellation, health, persistence, and recovery cases.

The full regression suite, Ruff, both consumer type contracts, branch coverage, distribution builds, and installed-wheel verification remain required for acceptance.

Local verification on 2026-10-20 used Python 3.13.16 and passed all 890 ordinary-discovery tests, including the 103-test background-task package.

The 31 additional adversarial regressions cover resource-binding changes at dispatch and physical IO boundaries, failure-body source authorization, accepted stop handoff, known-outcome settlement, conservative foreground exclusion, late typed failures, transient-result cleanup, and ordered health transitions.

Another 24 regressions cover foreground mixed-effect reservations and source checks, provider dispatch with the original personal Session, nested invocation resource boundaries, opaque global provenance, immediate and late fatal stop hooks, concurrent factual completion, and heartbeat/progress deadline races across slow commits.

The original five frozen runtime specifications, the dependency inventory, Ruff, both mypy consumer contracts, and `git diff --check` passed.

A separate branch-enabled full-suite run also passed all 890 tests and measured 83.97 percent coverage against the unchanged 70 percent minimum.

Failover fixtures close every created manager before their event loop shuts down; neither final full-suite run emitted pending-task, unobserved-exception, or cross-context generator-cleanup warnings.

Both sdist and wheel built successfully, and an isolated installed-wheel import exercised background execution, private artifacts, owner-only result reads, attention acknowledgement, save, and schema 14 recovery without replay or restored executable bindings.

The installed wheel's 264 Python source files matched the verified workspace sources byte for byte.

The verification created no repository-root `.att_doc_libs` directory, and the source and test checksums remained unchanged throughout the final suite, coverage, and distribution checks.

These local checks do not substitute for the repository's Python and operating-system CI matrix.
