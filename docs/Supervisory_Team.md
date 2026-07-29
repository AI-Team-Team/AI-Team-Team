# Supervisory Team

ATT audits completed team discussions with three isolated roles: Integrity,
Continuity, and Deadlock auditors. Their two-round committee discussion runs
with `skip_audit=True`, so supervision does not recursively audit itself.

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

`wake` immediately schedules an emergency parent discussion. That discussion
skips its own supervisory review for the current wakeup. Identical active
alerts are deduplicated per target team. These two guards prevent an audit
service outage from creating an escalation storm.

`queue` stores the alert in the parent inbox for its next normal discussion.

At the root, both confirmed and unknown failures propagate through
`on_system_event` and `on_emergency_escalation`; the library does not print
alerts directly.

## Transcript compression

Large transcripts are summarized before committee debate. If compression
fails, the entire audit result is `UNKNOWN`, with the exception type and
message retained in `AuditResult.cause`.
