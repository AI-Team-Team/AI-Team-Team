# 16. State Restoration and Unfinished-Activity Recovery

[Back to blueprint index](README.md).

## Confirmed Direction

Persistence and recovery are a required part of this update rather than a later addition to messaging and background execution.

Restoring stored state and addressing unfinished activity are related but separate contracts.

Restoration recovers the same person's committed identity, memory, relationships, artifacts, and technical records.

Recovery identifies interruption effects, persists annotations, and informs that person without automatically deciding how its business activity should continue.

ATT does not automatically inspect an external service, reconnect to its execution, or replay an external operation during recovery.

The AI may deliberately use its available tools to investigate or act after receiving the recovery notice.

No promise is made to serialize arbitrary Python coroutine stacks, `asyncio.Task` objects, Futures, closures, clients, or hidden model reasoning.

## Design-Review Findings and Checkpoint Coverage

Completion of a technical interaction is distinct from completion of business work.

That distinction does not require a structured WorkItem or framework acceptance contract.

A checkpoint assessment found Journal evidence in persisted state while the latest live Working Context remained in an unsubmitted discussion batch.

Consequently, saving historical evidence alone does not guarantee that the restored model window reflects the person's latest live activity or resumes an interrupted invocation.

The observed gap concerns context that had not yet been submitted, not evidence that restoration discarded an already committed Working Context record.

The new activity mechanism needs bounded, consistent checkpoints throughout activity rather than waiting for an indefinitely running conversation to finish.

Reading the Journal is not a substitute for correctly checkpointing Working Context, pending operations, and notifications.

## Required Persistence Coverage

The following coverage is required, while exact models, tables, field names, and indexes remain implementation research.

For current persistence groups and reference requirements, refer to the [implementation plan](../Implementation_plan_Autonomous_Agent_Activity_Messaging_and_Background_Tasks/14_Persistence_and_Recovery.md).

- Stable Agent identities, lifecycle, model aliases, personal instructions, committed Working Context, Journal provenance, optional memory catalogs, and private artifacts.
- Per-person runtime activity markers distinguishing continuing activity from deliberate idle or sleep, without treating silence as inactivity.
- AgentTeam memberships and their historical intervals, conversation identities, message sequence and author provenance, and retained history entitlements.
- Per-person read and unread state, preview preferences, pending notifications, and notification presentation records.
- Bilateral friendship, each person's block decision, requests and refusals, and stranger-message accounting for the applicable relationship period.
- Voluntary sleep plans, admitted event conditions, finite latest-wake conditions, remaining countdowns, and temporary do-not-disturb preferences.
- Background execution IDs, attempt identity, initiating Agent and operation scope, tool or executor references, descriptions, labels, and last-confirmed execution facts.
- Available results or protected result references, observations and their timestamps, attention state, interruption annotations, and external handles already recorded before interruption.
- Important system notices and durable recovery annotations that identify the affected person and execution without exposing private body content in generic logs.

AI-authored work plans and judgments remain files in the existing DocLib persistence mechanism rather than requiring a new work-management database.

Runtime callables, clients, and executor connections remain host bindings rather than serialized live objects.

Historical tool names and external handles are evidence, not permission to invoke them automatically after load.

Any necessary retained execution inputs or outputs must use owner-authorized storage or protected references rather than automatically publishing sensitive parameters or private body content through recovery notices and callbacks.

## Checkpoints and Commit Boundaries

The engineering design must establish consistent checkpoints for personal activity admission, deliberate sleep, message publication, read-state changes, relationship changes, execution admission, and receipt of a result.

Before starting a side-effecting execution, persist its identity, owner, scope, and admission record so recovery can identify a potentially outstanding operation.

A persisted intent still does not prove that the external side effect actually happened.

Persist observed results and attention or notification changes together with their required identity and provenance dependencies.

Do not acknowledge durable message delivery or a committed state change to the AI before the corresponding required write succeeds.

Use immutable versioned records and domain deltas rather than reading changing live objects from a worker or flushing unrelated state for every event.

Native tool-call/result ordering must remain valid at checkpoints and when interrupted activity is presented to the restored person.

A missing result must not be replaced with fabricated success or hidden by dropping evidence that an action was issued.

Exactly how an interrupted native batch is represented in the next valid model window is an implementation research item.

The original asynchronous single-writer ownership, backpressure, strict error propagation, schema validation, and all-or-nothing DocLib publication guarantees remain required.

## Restoration Sequence

The following sequence describes the required ordering rather than a selected implementation algorithm.

1. Acquire the applicable persistence ownership and restore gate, read a supported state version, and validate all authoritative references and state combinations.
2. Hydrate a detached staging state and stage DocLib files without starting personal activity or issuing external operations.
3. Derive interruption annotations from the latest committed activity and execution evidence, preserving confirmed terminal results and identifying uncertainty.
4. Restore membership history, chat entitlements, read state, block state, notification state, sleep plans, and remaining timer durations.
5. Atomically publish validated runtime state and DocLib directories, with required recovery records committed before dispatching activations or observational notices.
6. Schedule affected individuals through their one personal activity mechanism and activate the retained wake rules for unaffected sleeping individuals.

Validation, staging, or publication failure must leave the original manager and original DocLib state intact.

Missing identities or corrupt references remain restoration errors rather than ordinary interruption annotations.

Required model bindings and existing lifecycle protections must be respected without substituting another Agent or silently changing models.

## When Recovery Activates the Individual

| Latest committed pre-interruption evidence | Recovery behavior |
| --- | --- |
| The person was working or active. | Schedule that same person immediately after successful restoration, with an interruption summary. |
| A task owned by the person was affected, including while the person slept. | Schedule the owner immediately and identify the affected executions. |
| The person was sleeping, had no background task, and has no important system notice requiring activation. | Preserve sleep and its own wake rules rather than waking it merely because ATT restarted. |
| Only already confirmed terminal historical task records remain. | Those records alone do not constitute interrupted tasks or require restart-only activation. |

Immediate activation means admission to the person's serial activity mechanism after successful publication rather than a concurrent duplicate invocation.

The same identity, committed personal memory, and runtime model binding participate in that activation.

Recovery activation and its important notice cannot be suppressed by the person's temporary do-not-disturb settings.

Recovery activates the person, not the previous external tool execution.

The AI remains free to inspect the evidence, continue other work, investigate the affected task, or decide not to pursue it.

The latest durable activity marker is the recovery evidence rather than a claim that ATT can reconstruct an unrecorded final instant before a crash.

Repeated recovery processing must not create several concurrent activities or duplicate the same incident notice for one person.

## What Counts as an Affected Task

An ATT-side interruption can affect a task even when its external operation may still exist.

Examples include an execution admitted but not completed, a lost local wait for an external result, an uncommitted outcome, or a cancellation request whose acknowledgement was not retained.

ATT need not prove that the external service stopped before informing the owner that its local observation or execution continuity was interrupted.

An already confirmed completed or failed record is not changed merely because ATT restarted.

The framework does not automatically restore a lost external connection to determine which possibility is true.

## Preserve Facts and Label Uncertainty

| Persisted evidence | Recovery representation |
| --- | --- |
| A definite completed or failed result was committed. | Preserve the terminal state and result or result reference without rerunning the execution. |
| An execution was queued without a recorded start. | Preserve the queued evidence, annotate the affected pending execution, and let the notified owner decide whether to proceed. |
| An execution was last observed running without a confirmed outcome. | Retain the last-confirmed state and observation time, label the current outcome unconfirmed, and request the owner's attention. |
| A cancellation request exists without a committed cancellation acknowledgement. | Preserve the request and last-confirmed facts without claiming that the execution is cancelled. |
| A previous record contains an external operation ID. | Retain it for deliberate investigation rather than using it to poll or reconnect automatically. |

Recovery annotations such as interrupted observation or unconfirmed outcome are separate from the five execution states and must not silently turn them into false terminal results.

An unconfirmed record must not contribute to a prompt count as though ATT has freshly verified that the external execution is still running.

The exact display and aggregate-count treatment of last-confirmed but uncertain records must be explicit in the implementation contract.

No new business-success judgment is created by these annotations.

## Recovery Notice and Deliberate Follow-Up

The durable system notice identifies the affected activity or task IDs, last-confirmed facts, and available evidence references.

The prompt may show a bounded summary such as "Two executions have unconfirmed outcomes after interruption" rather than automatically exposing every parameter and output.

The AI uses task inspection and existing document tools to retrieve the details it is authorized to access.

Reading the notice, changing its read state, and acknowledging task attention remain separate actions.

A notice must not repeatedly activate the same person merely because it chose not to act on it.

If the AI explicitly requests another execution, retain the previous uncertain attempt and record a distinct new attempt rather than rewriting history to imply the old execution never happened.

Any deliberate follow-up still uses ordinary tool validation, authorization, execution-retry policy, and safeguards against duplicate side effects.

The prohibition on automatic recovery replay does not silently replace the configured retry contract of a currently running execution.

Stored message publication, relationship decisions, and received results must not be repeated simply because their notices are presented again.

## Sleep and Timer Restoration

ATT offline time does not consume a sleeping person's remaining wake countdown.

Time-based conditions and the finite latest-wake safeguard resume from their saved remaining durations using restoration start as the new timing anchor.

For example, a saved two-hour remainder remains a two-hour countdown after a six-hour outage rather than automatically becoming overdue.

The corresponding wake is dispatched only against a successfully published runtime state.

An affected task or other important system notice may independently require immediate activation even while the ordinary timer still has time remaining.

Durable checkpoints bound the error in a remaining duration, but an unexpected interruption cannot guarantee a write at its exact final instant.

Checkpoint granularity and handling of invalidated event conditions remain implementation research, with no permission to silently strand the person or replace its plan with wall-clock catch-up behavior.

## Existing Specialized Recovery Must Remain Valid

Formal communication, formation, governance, migration, and memory-indexing workflows retain their domain-specific validation and authoritative decision records.

A chat read state, recovery annotation, or wake notice must not supply missing consent, a ballot, or a tool result.

Generic interruption labels do not replace those protocols or make an incomplete approval successful.

The implementation review must separate resuming internal bookkeeping and delivering durable personal notices from automatically reissuing ordinary external business execution.

Historical identity and ownership references remain valid after ordinary participation changes without reconstructing another person.

## Remaining Engineering Research

For current recovery contracts and verification dependencies, refer to the [implementation plan](../Implementation_plan_Autonomous_Agent_Activity_Messaging_and_Background_Tasks/14_Persistence_and_Recovery.md).

- Precise checkpoint boundaries, dependency capture, and atomic publication of recovery annotations and notifications.
- Interrupted native-tool batch representation without invented output or invalid provider message order.
- Manager shutdown, surviving local workers, late results, cancellation acknowledgement, and protection against stale workers mutating restored state.
- Timer persistence granularity, restoration clock anchoring, and invalidated event-condition handling.
- Stable incident and execution identities for idempotent notices and explicit later attempts.
- Display and aggregation of uncertain outcomes, including last-confirmed rather than freshly observed execution state.
- Retention and archival of historical references without making them automatically visible or executable.
