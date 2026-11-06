# 6. Context, Memory, and Model Requests

[Back to plan index](README.md).

## 6.1 Team scope

The confirmed contract captures one personal or current-team scope for each invocation and applies an explicitly requested scope transition at the next safe boundary.

Every model request clearly identifies that scope while preserving the same person's instructions and memory.

Team tools continue to obtain their actor and authority from invocation ContextVars rather than accept a sender or approver override.

Selecting a team requires current membership and registered identity checks, and a captured team ID is not a permanent permission grant.

A Native batch keeps its captured scope for every member even if the AI requests a later scope change.

Authorized historical-chat inspection by a former member is a personal entitlement query rather than restoration of current team authority.

The AI may request a validated scope switch for subsequent execution without changing personal identity or memory.

Already admitted foreground or background executions retain their original captured scope, and exact tool names remain an API-design detail rather than an unresolved scope principle.

## 6.2 Working Context and Journal

Remove discussion-round provenance and introduce explicit activity, invocation, message, governance-case, and execution references where applicable.

Keep personal Working Context, append-only Journal evidence, optional memory catalogs, and deliberately retained memory references separate.

Explicit team publication records both the shared source message and its personal provenance without broadcasting unrelated personal context.

Background workers publish result evidence but never directly append to their owner's model window.

A person's next activity may deliberately inspect an authorized result or document rather than receive the entire body through a generic summary.

Existing transient private reads and recall results retain their redaction and cleanup guarantees.

No provider-hidden reasoning or inferred internal monologue is captured or persisted.

## 6.3 Checkpoint boundaries

- Before dispatching a model request, persist the input-frame checkpoint, relevant notification references, and the request's admission evidence.
- After receiving a model response, persist its personal observation and required Journal dependencies before relying on it for later authoritative effects.
- Before a side-effecting tool begins, commit its execution admission and scope.
- After a valid Native batch closes, commit the complete provider-valid window rather than an invalid partial conversation.
- Before voluntary idle or sleep, commit the latest personal window, intent, and notification progress.
- During continuing activity, use bounded checkpoints rather than an indefinite outer auto-save suppression batch.

An input-frame checkpoint refers to sanitized committed context and authorized transient-content references rather than automatically storing the complete submitted prompt.

Explicit private reads and episodic recall bodies keep their existing transient treatment even when they are present in a live model request.

Recovery retains redacted factual evidence of such observations without automatically rereading private files or injecting old private bodies into another scope.

Optional indexing commits must still capture insert-only identity and provenance dependencies without rewriting unrelated Agent or team rows.

## 6.4 Model cost and cancellation

Reuse the atomic token ledger and continue estimating the actual explicit prompt, personal and team instructions, notification frame, and transmitted tool definitions.

This remains framework detection with ordinary estimator error, not a promise of exact provider token identity.

Extend request evidence and accounting so a crash or cancellation cannot silently make potentially spent quota available again.

Confirmed unsent requests release reservations, known usage settles them once, and sent requests with unknown usage retain a documented conservative accounting treatment.

The precise persistent representation of such accounting is part of the new schema review rather than resetting all reservations on load.

Fence late provider responses before they can append memory, change availability, or perform an authoritative commit.

Do not admit overlapping live personal requests in one runtime merely because cancellation was requested.

Remote processing that outlives a network or process failure remains uncertain evidence rather than a guarantee that ATT can enforce physical exclusivity inside an external provider.

Measure a dispatched model attempt against its request timeout and the remaining whole-sequence budget, and fence a late result rather than accept it into a newer personal context.

Timeout alone is not proof of remote cancellation, stopped local execution, or zero usage, so it does not justify an overlapping live request or unconditional quota refund.

A later recovery admission uses the same Agent's validated current context and is not automatic replay of an old external tool action or restored transport request.
