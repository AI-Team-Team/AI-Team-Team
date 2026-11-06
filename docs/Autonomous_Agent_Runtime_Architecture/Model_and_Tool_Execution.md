# Model, Tool, and Executor Coordination

ATT coordinates provider requests and registered operations through common admission, ownership, accounting, and acceptance boundaries.

## Provider Requests

Ordinary activity, temporary audit participants, and optional indexing share bounded model dispatch and atomic alias-based quota accounting.

Their trusted lifecycle profiles retain distinct provenance rather than impersonating Root or starting another activity for the indexing beneficiary.

The explicit model-input estimate includes prompt content, system instructions, eligible notification content, and transmitted tool definitions and JSON Schema.

Prompt and maximum-output capacity are reserved before dispatch, factual usage settles once, confirmed-unsent requests refund, and unknown sent usage remains charged conservatively.

The framework estimate permits normal differences from provider tokenization while enforcing its detected budget boundary.

One zero-limit alias is disabled even when an estimated request budget happens to be zero.

The provider-neutral client interface receives `list[Tool]`, with adapters translating schemas to the actual SDK protocol.

## Retry and Availability

Defaults are three extra attempts, a one-second exponential base, a thirty-second Full Jitter cap, a 120-second request timeout, a 600-second whole-sequence budget, and a sixty-second recoverable re-admission delay.

For retry index `k` starting at one, ATT draws from `0..min(cap, base * 2 ** (k - 1))`.

A valid provider wait instruction is an independent lower bound and may exceed the jitter cap.

Admission waits, requests, checkpoint work, provider waits, and backoff consume the sequence budget.

A provider wait beyond the remaining budget ends the sequence and preserves earliest-admission evidence rather than sending early.

Typed authentication, configuration, programming, and validation faults require Host remediation instead of periodic transient recovery.

Adapters must represent one upstream attempt or explicitly budget their SDK's retries within ATT's limits.

Timeout and cancellation requests do not prove that a synchronous or cancellation-resistant local provider call stopped.

The dispatcher retains the live local owner/capacity claim until actual completion, fences late results, and does not refund unknown usage unconditionally.

Remote work after lost transport or process lifetime remains uncertain; ATT does not claim physical control of an external provider.

## Registered Operations

Text ReAct and Native share strict parsing, signature/type/schema validation, the auditor, typed outcomes, execution retries, and invocation-scoped identity.

An execution records its owner, actual invocation or authenticated Host origin, captured scope/generation, validated registered operation, source provenance, and protected input before side effects begin.

Auditor denial or invalid arguments create no fictitious dispatched attempt.

Each actual execution retry has its own attempt evidence and follows the separately configured typed retry policy.

Retry safety does not grant background permission.

Self-modifying and undeclared effects cannot detach, and omitted custom contracts remain foreground-only.

Eligible execution faults may create the default ten-minute same-Agent/tool cooldown for new calls only.

Correctable input, missing paths, ordinary denial, and business refusal do not impose that cooldown.

Denied cooling calls neither extend the deadline nor cancel previously accepted healthy executions, and expiry does not replay a failed operation.

A rejected new call during cooldown must report the remaining duration without executing the tool or extending the deadline.

The current implementation reports `error_kind="tool_cooldown"` but omits that duration.

This [tracked implementation gap](../../todo.md#tool-cooldown-remaining-time) remains unresolved; the existing denial must not be interpreted as a remaining-time response.

Concurrent same-Agent/tool faults serialize their cooldown record versions, and the candidate monotonic deadline becomes live only after its matching accepted receipt.

Observer cancellation after acceptance preserves that boundary, while rejected persistence cannot replace it with an unaccepted cooldown.

## Detachment and Resources

Explicit background admission and automatic detachment use the same original execution, attempts, result, and ownership.

The configurable default threshold is 120 seconds from actual executor start, including retries/backoff and excluding initial preflight/queueing.

Absolute monotonic deadlines prevent delayed timer scheduling from restarting that interval.

Completion and promotion serialize their accepted transitions so a Native call receives either its completed result or one task-handle observation.

A later outcome is an accepted protected result and owner notice, not a second observation for the old provider call ID.

Detached workers start with deliberately seeded execution authority and cannot inherit mutable personal windows, unfinished batches, caller transactions, or stale dependency chains.

Cross-owner resource reservations serialize conflicting physical paths, directory descendants, managed-link targets, and both move endpoints in deterministic order.

Independent resources may proceed concurrently, and a blocked queue entry does not prevent unrelated eligible work from using executor capacity.

Unresolved external independence uses conservative exclusion or an explicitly trusted Host responsibility rather than inferred safety.

Live ACL, lifecycle, generation, binding, and reserved-resource checks apply at protected access and final publication.

Resource serialization and atomic publication permit semantic last-writer overwrite; they do not detect every modification derived from an older read.

## Outcomes and Controls

The five execution states remain independent of health, attention, suspension/cancellation requests, acknowledgements, and uncertainty.

Cancelling queued work prevents dispatch, while a running operation needs a meaningful declared acknowledgement before it can be recorded as stopped.

A known returned outcome owns local finalization and cannot be replaced by speculative cancellation merely because persistence is still settling.

Synchronous work retains its reservation until actual return; cancelling a Future does not stop its thread.

Unacknowledged work loses managed mutation authority and produces factual uncertainty and Host risk evidence.

Shutdown bounds external waits while accepted local outcomes and commits settle without an arbitrary persistence deadline.

See [Tool System](../Tool_System.md) for parser and retry configuration and [Background Tasks](../Background_Tasks.md) for executor registration, result access, attention, and cancellation APIs.
