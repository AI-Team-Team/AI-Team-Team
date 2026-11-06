# 5. Personal Activity and Safe Continuation

[Back to plan index](README.md).

## 5.1 Proposed record distinctions

| Record or field group | Purpose |
| --- | --- |
| Personal activity marker | Default ongoing activity or an explicitly chosen idle or sleeping state, independent of Agent lifecycle. |
| Invocation record | One bounded period of model-driven activity with its owner, context version, scope, and interruption evidence. |
| Model-request record | One provider request, its input-frame reference, dispatch evidence, token claim, and factual outcome. |
| Runtime availability | Whether admission is ready, waiting for a model, waiting for a foreground tool, resource-blocked, or closing. |
| Activity intent | The AI's explicit choice to become idle or sleep, applied at a valid boundary without a required continuing declaration. |

Waiting for a model or tool does not turn continuing personal activity into deliberate idle or sleep.

Resource-blocked activity remains distinguishable from the AI choosing to stop.

Invocation budgets bound technical work before a checkpoint and scheduling yield rather than require another person to produce an answer.

## 5.2 Proposed admission protocol

1. Commit the source event and necessary notification references before announcing acceptance.
2. Under the activity admission lock, inspect lifecycle, runtime generation, current personal admission, sleep conditions, and notification eligibility.
3. If the person is already active, record pending information without creating another personal invocation.
4. If the person is eligible and idle, enqueue its identity once using a durable generation or watermark.
5. Claim a bounded notification frame and commit its association with the next valid model context.
6. Execute the same person's activity through the existing identity guard, with an immutable captured operation scope.
7. Refresh eligible notifications and current factual summaries before each subsequent model request, not only at invocation start.
8. Complete every required tool-result sequence before applying an ordinary context update or activity-intent transition.
9. Commit the personal checkpoint and any explicit idle or sleep intent before releasing personal admission.
10. Compare the arrival generation and unpresented eligible records during the active-to-idle transition so an arrival cannot be stranded between checking and releasing admission.

Events arriving after the captured frame remain pending for a later safe frame.

Repeated arrivals may be summarized together, but each source reference and individual provenance remain retrievable.

## 5.3 Default activity and explicit stopping

Personal activity continues by default while the AI is thinking, using tools, or waiting for a model or foreground execution.

The AI does not need to submit a `continuing` declaration to remain active.

Provide a strict control tool for an explicit choice to become idle or sleep, with the candidate name `set_activity_intent()` and exact API naming still subject to interface review.

The choice applies after the current valid tool batch and authoritative transaction boundaries, not halfway through them.

An ordinary model response without a stopping choice does not imply idle, sleep, public message publication, or business completion.

Silent reading and artifact work remain ordinary activity rather than requiring a special continuing state.

Technical request budgets, checkpoints, and fair scheduling yields remain separate from the AI's deliberate stopping choices.

A technical yield must not discard continuing activity or require a new message solely because the AI omitted a continuing declaration.

Scope changes use the separately validated mechanism in Section 6.1 rather than requiring a continuing-state operation.

Duplicate or contradictory control operations in one Native batch require deterministic validation rather than scheduling according to whichever parallel result happens to return first.

## 5.4 Failure isolation

A normal tool failure returns a classified observation without ending or pausing the person's activity.

The AI may correct arguments, choose another path or tool, seek advice, or continue other activity.

Invalid arguments, a missing file, and an operation-specific permission denial do not by themselves indicate that the entire tool is unavailable.

Confirmed execution faults and exhausted transient execution retries are eligible for a tool cooldown, scoped by default to the same `agent_id` and registered tool identity.

The confirmed cooldown duration is ten minutes for eligible execution faults, while exact fault-classification details remain an implementation contract to review.

A cooldown restricts new executions by that Agent using that tool, does not cancel other already admitted healthy executions, and returns the remaining cooldown time instead of executing another call.

A rejected call during cooldown does not extend the cooldown, and expiry restores availability without automatically replaying the failed operation.

A cooldown does not disable other tools, terminate the AgentTeam, or stop unrelated people.

Any protection for a shared failing service must be separately configured rather than inferred as a global tool ban from one person's failed call.

LLM API retry and ordinary tool execution retry are different contracts and must not share an inferred retry allowance or side-effect replay permission.

Retry recoverable LLM API failures with exponential backoff and Full Jitter, without retrying authentication, programming, or validation errors as transient faults.

The confirmed LLM defaults are at most three additional retries after the initial request, a one-second exponential base, and a thirty-second exponential backoff cap.

For retry index `k` starting at one, Full Jitter draws a delay from zero to `min(cap, base * 2 ** (k - 1))` before accounting for provider-required waiting instructions.

Honor valid provider retry-wait instructions as a lower bound, even when the requested wait exceeds the thirty-second exponential backoff cap.

The cap limits ATT's own exponential jitter range, not the provider's stated earliest retry time.

Use a default single-request timeout of 120 seconds, configurable by model, and a default whole-retry-sequence time limit of ten minutes including requests and backoff waits.

After recoverable retries are exhausted, wait a default one minute before admitting a recovery attempt, and never admit it before any still-applicable provider earliest-retry boundary.

If a provider-required wait exceeds the remaining sequence budget, end that retry sequence and retain the earliest-retry evidence rather than wait indefinitely or send early.

Record model unavailability without changing deliberate activity intent or discarding pending information, and require Host remediation for authentication, configuration, or programming faults rather than applying periodic transient recovery to them.

These are model-resource policies, not ordinary tool replay or background-detachment policies.

Provider-adapter retry behavior must fit within the total attempt and elapsed budgets rather than multiplying hidden SDK retries by ATT retries.

An unavailable model can prevent that person's next model request, but this is runtime availability rather than voluntary idle, sleep, or a failure of other people.

It cannot close a shared conversation, abort unrelated participants, or become another person's synthetic utterance.

Cancellation, shutdown, persistence failure, invalid ownership, and state-integrity errors remain framework-level signals rather than normal personal answers.

Repeated wake attempts against an unavailable model or exhausted budget must remain pending with observable availability reasons rather than spin, discard accepted notifications, or change the person's model implicitly.

The existing whole-discussion meaning of `turn_failure_policy='abort'` must be removed rather than translated into terminating an AT.

## 5.5 Cooldown time accounting

Migration and tool cooldowns include actual elapsed ATT downtime by default, with validated host configuration able to choose downtime-excluded accounting.

Persist the accounting mode and the evidence needed for the applicable elapsed-time calculation rather than reset a cooldown on load.

The downtime-excluded mode preserves a remaining duration while ATT is offline, whereas the default mode accounts for elapsed offline time.

These rate-control choices are separate from voluntary sleep countdowns, which continue to exclude ATT downtime.
