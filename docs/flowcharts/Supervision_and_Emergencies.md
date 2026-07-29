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
    Unknown --> Mode{"unknown mode"}
    Mode -- "queue" --> Inbox["Keep in parent inbox"]
    Mode -- "wake" --> Dedupe{"Identical wake already active?"}
    Dedupe -- "Yes" --> Inbox
    Dedupe -- "No" --> Wake["Emergency discussion with skip_audit=True"]
    Emergency --> WakeNormal["Emergency discussion"]
```

Root-level escalations use callbacks and structured system events. Unknown
audit wakeups are deduplicated and skip one supervisory cycle to prevent
recursive audit storms.
