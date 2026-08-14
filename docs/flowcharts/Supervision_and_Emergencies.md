# Supervision and Emergency Flow

```mermaid
flowchart TD
    Discussion["Team discussion completes with structured turn results"] --> Framework["Framework derives operational status from completed and incomplete turns"]
    Framework --> Skip{"skip_audit?"}
    Skip -- "Yes" --> Return["Return DiscussionResult and transcript"]
    Skip -- "No" --> Committee["Three-auditor committee"]
    Committee --> DecisionMode{"operational status decision mode"}
    DecisionMode -- "framework" --> Content["Supervisor decides content status; framework operational status is retained"]
    DecisionMode -- "supervisor" --> Both["Supervisor strictly decides content and operational status"]
    DecisionMode -- "framework_then_supervisor" --> Review["Supervisor reviews both axes; supervision failure retains framework operational status"]
    Content --> Audit["AuditResult"]
    Both --> Audit
    Review --> Audit
    Audit --> Result{"content status"}
    Audit --> Operational{"operational status"}
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
    Operational -- "HEALTHY" --> Return
    Operational -- "UNKNOWN" --> Event
    Operational -- "DEGRADED" --> OpMode{"degraded escalation mode"}
    OpMode -- "none" --> OpEvent
    OpMode -- "queue" --> OpAlert["Persist deduplicated operational alert in parent inbox"]
    OpMode -- "wake" --> OpDedupe{"Identical operational wake already active?"}
    OpDedupe -- "Yes" --> OpAlert
    OpDedupe -- "No" --> OpWake["Emergency discussion with skip_audit=True"]
    OpEvent --> Return
    Inbox --> Processing["Parent discussion marks processing"]
    Processing --> Success{"Discussion succeeds?"}
    Success -- "Yes" --> Ack["Acknowledge and remove"]
    Success -- "No/cancel" --> Inbox
    OpAlert --> OpProcessing["Parent discussion marks processing"]
    OpProcessing --> OpSuccess{"Discussion succeeds?"}
    OpSuccess -- "Yes" --> OpAck["Acknowledge and remove"]
    OpSuccess -- "No/cancel" --> OpAlert
```

Content health and operational health are independent, so an unhealthy discussion may also be operationally degraded.

Root-level escalations use callbacks and structured system events.

Unknown audit and degraded operational wakeups are durably deduplicated and skip one supervisory cycle to prevent recursive audit storms.

Alerts have no TTL or hard drop limit; a soft threshold only emits operational events.
