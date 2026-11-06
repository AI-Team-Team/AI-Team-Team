# Recovery and Runtime Publication

ATT restores a validated checkpoint and separately settles evidence of interrupted personal activity and executions.

## Preflight and Staging

Restoration acquires database ownership and the runtime admission boundary, settles accepted writes, and rejects live operations that could mutate the generation being replaced.

This includes admitted lifecycle, countdown, formation, governance, migration, resource, audit, and unfinished read-delivery handoffs even while they wait for their domain locks.

The restoration start time anchors saved countdown remainders.

Read and validate all identities, lifecycle states, stable active-model bindings, ownership, source references, intervals, view projections, cases, ballots, cooldowns, quotas, and publication evidence before publication.

Missing private libraries, participants, or historical references are corruption rather than a reason to fabricate replacement identities.

Required interruption changes are derived in a detached manager without making external execution or status calls.

Stage restored DocLib contents on the managed filesystem without admitting model activity.

## Recoverable Publication

A fsynced namespace journal and durable publication manifest link the source checkpoint, previous/target generation, staged directories, and required recovery transaction.

Managed access is gated while file materialization is provisional, and directory readers continue to see the last complete registry snapshot.

Required interruption updates and recovery notices commit with the publication decision before the synchronous live-registry switch.

No await, observer dispatch, or new public registry exposure occurs between that accepted decision and the registry publication step.

SQLite and several filesystem renames are coordinated recoverable operations rather than one operating-system atomic instruction.

The namespace writer lease serializes publishers but is not a cross-process executor coordinator for arbitrary Host filesystem edits.

## Failure Boundaries

Validation or staging failure preserves the original manager and files.

A failure before publication completes restores the old registries, directories, timer admission, and provisional SQL changes, or retains a fail-closed resource fence if safe rollback cannot complete.

Manifest before-images restore prior versions of existing request, quota, and other whitelisted recovery rows as well as remove new provisional additions.

Crash reconciliation applies the complete inverse graph under deferred restrictive foreign-key checks.

A later startup reconciles prepared, published, and rollback decisions before allowing new managed mutation.

Cleanup or callback failure after committed publication is observational and does not undo the accepted generation.

A post-publication scheduling failure leaves pending notices against the new generation instead of claiming rollback or falsely recording activation.

Old DocLib references and late provider or executor results cannot access a newly published runtime generation.

## Domain Recovery

Ordinary, audit, and optional-index requests retain factual dispatch and outcome independently from token settlement.

Confirmed-unsent claims refund, factual usage settles once, and uncertain potentially spent reservations remain charged.

Communication processing returns to pending after validation, and institutional bookkeeping never supplies missing ballots, invitation attitudes, or consent.

Interrupted parent-resource attempts expire without replaying their original invocation or applying late choices.

Unfinished audits become retained UNKNOWN evidence, audit participants are not recreated, and claimed incidents return to pending with release evidence.

Receipt-owned incident-delivery outboxes resume eligible notification dispatch after publication without rerunning the assessment that produced them.

Optional candidates remain retained artifacts without a detached job to resume.

An already recorded uncertain execution does not repeatedly wake its owner merely because the checkpoint is loaded again.

## Activation and Execution Facts

| Latest committed evidence | Behavior after successful publication |
| --- | --- |
| Continuing or active personal activity | Admit the same eligible person with a protected interruption summary. |
| An owned execution was affected, including while its owner was idle or asleep | Admit the same owner with affected IDs and last-confirmed facts. |
| Unaffected sleep with no other protected arrival | Preserve the saved sleep plan and countdown remainder. |
| Confirmed terminal execution history only | Retain history without a restart-only activation. |
| Retained, archived, dead, or physically absent person | Preserve valid historical evidence without automatic reactivation or reconstruction. |

Recovery activates the person rather than the previous external execution.

Queued and running evidence retains its last-confirmed state and an unconfirmed-current-outcome annotation where applicable.

Cancellation requests do not become acknowledgements, and confirmed terminal outcomes remain terminal.

Historical handles are not automatically replayed, reconnected, polled, or refreshed.

A deliberate later operation receives a distinct identity while the earlier uncertain evidence remains retained.

## Timers, Context, and History

Sleep and timed suppression resume from their latest persisted remaining duration anchored at restoration start, excluding offline time.

If staging consumes that remainder, wake dispatch waits until publication succeeds.

Protected interruption findings may independently require earlier owner activation.

Tool and migration cooldowns use their captured offline-time accounting policy, which counts downtime by default.

Persisted countdown precision includes checkpoint interval, event-loop scheduling, and commit delay rather than an exact final instant before a crash.

Restored personal context must be provider-valid; incomplete Native exchanges remain factual evidence without fabricated successful tool output.

Before publication, the candidate Journal must contain every already committed destination event with the same sequence and JSON contents.

JSON comparison distinguishes booleans from numbers while ignoring object key order.

A stale or divergent checkpoint is rejected rather than written over newer immutable history.

The Host reacquires restored objects from the published manager rather than retaining old object references as current authority.
