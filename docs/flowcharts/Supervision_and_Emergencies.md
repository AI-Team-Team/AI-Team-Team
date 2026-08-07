# Supervision and Emergency Flow

```mermaid
flowchart TD
    Discussion["Team discussion completes"] --> Skip{"skip_audit?"}
    Skip -- "Yes" --> Return["Return transcript"]
    Skip -- "No" --> Committee["Three-auditor committee"]
    Committee --> Result{"AuditResult.status"}
    Result -- "HEALTHY" --> Return
    Result -- "UNHEALTHY" --> Emergency["Send child_failure_escalation"]
    Result -- "UNKNOWN" --> Event["Emit audit_unknown system event"]
    Event --> Unknown["Send audit_unknown_escalation"]
    Unknown --> Fingerprint["Persist stable fingerprint, count and timestamps"]
    Fingerprint --> Mode{"unknown mode"}
    Mode -- "queue" --> Inbox["Keep pending in parent inbox"]
    Mode -- "wake" --> Dedupe{"Identical wake already active?"}
    Dedupe -- "Yes" --> Inbox
    Dedupe -- "No" --> Wake["Emergency discussion with skip_audit=True"]
    Emergency --> WakeNormal["Emergency discussion"]
    Inbox --> Processing["Parent discussion marks processing"]
    Processing --> Success{"Discussion succeeds?"}
    Success -- "Yes" --> Ack["Acknowledge and remove"]
    Success -- "No/cancel" --> Inbox
```

Root-level escalations use callbacks and structured system events. Unknown audit wakeups are durably deduplicated and skip one supervisory cycle to prevent recursive audit storms. Alerts have no TTL or hard drop limit; a soft threshold only emits operational events.
