# Supervisory Team

ATT audits completed team discussions with three isolated roles: Integrity, Continuity, and Deadlock auditors. Their two-round committee discussion runs with `skip_audit=True`, so supervision does not recursively audit itself.

## Result model

`audit_team_dialog()` returns an `AuditResult`:

```python
AuditResult(
    status=AuditStatus.HEALTHY,
    reason="The committee reached a valid conclusion.",
    cause=None,
    operational_status=OperationalStatus.HEALTHY,
    operational_reason="All member turns completed.",
)
```

Content status is one of:

- `HEALTHY`: the committee explicitly confirmed a healthy discussion.
- `UNHEALTHY`: the committee explicitly confirmed an anomaly.
- `UNKNOWN`: the LLM call, token budget, incomplete committee discussion, response conversion, or JSON validation prevented a trustworthy result.

Operational status is independent:

- `HEALTHY`: every member turn completed and the selected authority found no runtime degradation.
- `DEGRADED`: at least one member turn was incomplete or the selected supervisor authority explicitly found degraded execution.
- `UNKNOWN`: supervisor-owned runtime evaluation could not form a valid result.

A discussion can be content `UNHEALTHY` and operationally `DEGRADED` at the same time.

The supervisor receives the complete transcript, incomplete placeholders, and privacy-safe failure metadata without tool arguments, private bodies, or sensitive observations.

`operational_status_decision_mode="framework"` lets structured turn results determine runtime health while the committee evaluates content.

`"supervisor"` requires strict JSON for both axes and produces operational `UNKNOWN` if supervision fails.

`"framework_then_supervisor"` allows committee review but preserves the framework runtime result if supervision fails.

## Escalation behavior

`UNHEALTHY` preserves the emergency path: the supervisor sends a `child_failure_escalation` to the direct parent.

An idle parent is woken for an emergency discussion when emergency wakeups are enabled.

`UNKNOWN` emits an `audit_unknown` system event and sends an `audit_unknown_escalation` to the parent. Configure its delivery with:

```python
ATTConfig(audit_unknown_escalation_mode="wake")   # default
ATTConfig(audit_unknown_escalation_mode="queue")
```

`wake` immediately schedules an emergency parent discussion. That discussion skips its own supervisory review for the current wakeup.

Identical alerts use a stable persisted fingerprint and merge their occurrence count, first-seen time, and last-seen time. These guards prevent an audit service outage from creating an escalation storm.

`queue` stores the same durable alert record in the parent inbox for its next normal discussion. An injected alert moves from `pending` to `processing`.

It is removed only after the parent discussion succeeds; failure or cancellation returns it to `pending`.

Alerts have no TTL and no hard count limit.

The optional `audit_unknown_soft_threshold` emits operational warnings without rejecting or deleting unique alerts.

Hosts may explicitly acknowledge or clear records:

```python
manager.acknowledge_unknown_alert(team_id, fingerprint)
manager.clear_unknown_alerts(team_id)                 # all UNKNOWN alerts
manager.clear_unknown_alerts(team_id, {fingerprint}) # selected alerts
```

At the root, both confirmed and unknown failures propagate through `on_system_event` and `on_emergency_escalation`; the library does not print alerts directly.

Operational `DEGRADED` always emits a structured `operational_degraded` system event.

`operational_degraded_escalation_mode="none"` is the default and does not notify a parent; `"queue"` creates a durable parent inbox alert; `"wake"` additionally schedules a serialized emergency discussion.

Operational alerts use the same stable fingerprint, occurrence count, first/last timestamps, processing state, success acknowledgement, failure requeue, and wake deduplication rules as UNKNOWN alerts.

A wake caused by either alert type skips that emergency discussion's audit cycle to prevent recursive supervision storms.

## Transcript compression

Large transcripts are summarized before committee debate.

If compression fails, the entire audit result is `UNKNOWN`, with the exception type and message retained in `AuditResult.cause`.
