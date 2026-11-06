# 13. Suspected Stalls and Evidence-Based Health

[Back to blueprint index](README.md).

## Confirmed Direction

The task mechanism can report that execution may require attention rather than quietly assuming that a long wait is normal or declaring business work unsuccessful.

Candidate signals include missing heartbeat, absent output progress, external-worker disconnection, resource unavailability, deadline expiry, and a provider-reported stall.

```text
Task #918 may be stalled:

- Running for 47 minutes.
- No heartbeat for 10 minutes.
- No output change for 18 minutes.

Background task may require attention.
```

The example is illustrative and does not establish default stall thresholds.

Missing output is not conclusive evidence of failure when the operation legitimately produces no intermediate output.

An executor that does not support heartbeat reporting must not be treated as broken solely because it has no heartbeat.

The recommended classification uses `unknown` when supported evidence is insufficient and `stalled` for suspected lack of progress rather than rewriting the execution state as `failed` without an actual terminal failure.

The automatic-detachment threshold is separate from a deadline, and deadline expiry is meaningful only if an actual deadline exists.

Suspected stall notifications should retain their evidence and uncertainty.

Health observations must not automatically replay, restart, or cancel an operation whose side effects or external status are unknown.

Observations may use evidence already returned during execution, but recovery must not automatically poll an external service or reconnect to obtain fresh health information.

Exact signal support, classification rules, escalation, and stall-notification deduplication remain to be decided.

For current execution-health and supervisory boundaries, refer to the [implementation plan](../Implementation_plan_Autonomous_Agent_Activity_Messaging_and_Background_Tasks/10_Background_Tasks.md) and its [health-supervision chapter](../Implementation_plan_Autonomous_Agent_Activity_Messaging_and_Background_Tasks/12_Health_Supervision.md).
