# Supervisory Team

ATT audits completed team discussions with three isolated roles: Integrity, Continuity, and Deadlock auditors. Their two-round committee discussion runs with `skip_audit=True`, so supervision does not recursively audit itself.

## Result model

`audit_team_dialog()` returns an `AuditResult`:

```python
AuditResult(
    status=AuditStatus.HEALTHY,
    reason="The committee reached a valid conclusion.",
    cause=None,
)
```

The status is one of:

- `HEALTHY`: the committee explicitly confirmed a healthy discussion;
- `UNHEALTHY`: the committee explicitly confirmed an anomaly;
- `UNKNOWN`: the LLM call, token budget, response conversion, or JSON
  validation prevented a trustworthy result.

An operational audit failure is never treated as healthy.

## Escalation behavior

`UNHEALTHY` preserves the emergency path: the supervisor sends a
`child_failure_escalation` to the direct parent. An idle parent is woken for
an emergency discussion when emergency wakeups are enabled.

`UNKNOWN` emits an `audit_unknown` system event and sends an
`audit_unknown_escalation` to the parent. Configure its delivery with:

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

## Transcript compression

Large transcripts are summarized before committee debate.

If compression fails, the entire audit result is `UNKNOWN`, with the exception type and message retained in `AuditResult.cause`.
