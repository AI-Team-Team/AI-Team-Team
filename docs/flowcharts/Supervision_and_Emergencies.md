# Supervision and Incident Flow

Health detection requests inspection rather than deciding that a person is unhealthy.

```mermaid
flowchart TD
    Evidence["Typed runtime observation or confirmed guard evidence"] --> Kind{"Evidence kind"}
    Host["Explicit Host assessment request with authorized evidence"] --> Admission
    Kind -- "Confirmed permission/integrity fault" --> Protect["Apply deterministic protection immediately"]
    Protect --> Incident["Persist or merge stable incident"]
    Kind -- "Protocol failure" --> Protocol["Default: three consecutive failures in 600 seconds"]
    Kind -- "Same-tool argument category" --> Tool["Default: five consecutive failures in 600 seconds"]
    Kind -- "Semantic suspicion" --> Semantic{"Host enabled detector and authorized evidence?"}
    Kind -- "Silence, waiting, denial, provider outage" --> NoBlame["No automatic Agent-health accusation"]
    Semantic -- "No" --> NoBlame
    Semantic -- "Yes" --> Detector["Run Host detector on explicitly authorized evidence"]
    Detector -- "Literal true" --> Admission
    Detector -- "Other result" --> NoBlame
    Protocol --> Threshold["Commit threshold observation and detector state"]
    Tool --> Threshold
    Threshold --> InitialIncident["Commit threshold incident before audit admission"]
    InitialIncident --> Admission["Admit fresh real privileged audit AT"]
    InitialIncident -. "Recorded incident metadata" .-> Event
    Admission --> Deadline["Total 600-second default deadline includes queueing"]
    Deadline --> Runtime["Same personal scheduler, provider service, ToolExecutor and quota ledger"]
    Runtime --> Findings["Each predefined auditor explicitly submits own structured finding"]
    Findings --> Complete{"All findings valid and timely?"}
    Complete -- "No, failure, cancellation or deadline" --> Unknown["UNKNOWN"]
    Complete -- "Yes" --> Majority["Strict majority, with independent operational axis"]
    Majority --> Result["HEALTHY, UNHEALTHY or UNKNOWN"]
    Unknown --> Retain
    Result --> Retain["Commit scoped evidence and dissolve temporary identities"]
    Retain -- "Non-healthy or operationally degraded result" --> Incident
    Incident --> Delivery{"Configured attention"}
    Delivery -- "none" --> Event["Metadata-only system event"]
    Delivery -- "queue or wake" --> Handler{"Actual organizational handler exists?"}
    Handler -- "No" --> Event
    Handler -- "Yes, queue" --> Mail["Addressed attention, no forced activation"]
    Handler -- "Yes, wake" --> Personal["Request ordinary personal activity, no scope or intent override"]
    Mail --> Claim["Explicit current-authority claim"]
    Personal --> Claim
    Claim --> Handled{"Explicit current-generation acknowledgement?"}
    Handled -- "Yes" --> Ack["Acknowledge attention, retain evidence"]
    Handled -- "Failure, cancellation or restart" --> Pending["Release claim to pending"]
    Pending --> Claim
```

A valid provider response resets the protocol streak, while a successful call resets the same tool's argument streak.

The configured observation window, 600 seconds by default, never becomes an incident TTL.

Audit findings grant no implicit repair, membership, file, permission, or model authority.

Temporary audit activity does not recursively trigger new assessments.

Parent failover has a separate default 120-second resource deadline.
