# Supervision and Incident Flow

Health detection requests inspection rather than deciding that a person is unhealthy.

```mermaid
flowchart TD
    Evidence["Typed observation or explicit Host evidence"] --> Kind{"Evidence kind"}
    Kind -- "Confirmed permission/integrity fault" --> Protect["Apply deterministic protection immediately"]
    Protect --> Incident["Persist or merge stable incident"]
    Kind -- "Protocol failure" --> Protocol["Three consecutive failures in 600 seconds"]
    Kind -- "Same-tool argument category" --> Tool["Five consecutive failures in 600 seconds"]
    Kind -- "Semantic suspicion" --> Semantic{"Host enabled detector and authorized evidence?"}
    Kind -- "Silence, waiting, denial, provider outage" --> NoBlame["No automatic Agent-health accusation"]
    Semantic -- "No" --> NoBlame
    Semantic -- "Yes" --> Threshold["Retain authorized detector evidence"]
    Protocol --> Threshold
    Tool --> Threshold
    Threshold --> Incident
    Threshold --> Admission["Admit fresh real privileged audit AT"]
    Admission --> Deadline["Total 600-second default deadline includes queueing"]
    Deadline --> Runtime["Same personal scheduler, provider service, ToolExecutor and quota ledger"]
    Runtime --> Findings["Each predefined auditor explicitly submits own structured finding"]
    Findings --> Complete{"All findings valid and timely?"}
    Complete -- "No, failure, cancellation or deadline" --> Unknown["UNKNOWN"]
    Complete -- "Yes" --> Majority["Strict majority, with independent operational axis"]
    Majority --> Result["HEALTHY, UNHEALTHY or UNKNOWN"]
    Unknown --> Retain
    Result --> Retain["Commit scoped evidence and dissolve temporary identities"]
    Retain -- "Attention required" --> Incident
    Incident --> Delivery{"Configured attention"}
    Delivery -- "none" --> Event["Metadata-only system event"]
    Delivery -- "queue" --> Mail["Addressed attention, no forced activation"]
    Delivery -- "wake" --> Personal["Request ordinary personal activity, no scope or intent override"]
    Mail --> Claim["Explicit current-authority claim"]
    Personal --> Claim
    Claim --> Handled{"Explicit current-generation acknowledgement?"}
    Handled -- "Yes" --> Ack["Acknowledge attention, retain evidence"]
    Handled -- "Failure, cancellation or restart" --> Pending["Release claim to pending"]
    Pending --> Claim
```

A valid provider response resets the protocol streak, while a successful call resets the same tool's argument streak.

The 600-second observation window never becomes an incident TTL.

Audit findings grant no implicit repair, membership, file, permission, or model authority.

Temporary audit activity does not recursively trigger new assessments.

Parent failover has a separate default 120-second resource deadline.
