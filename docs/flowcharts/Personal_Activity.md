# Continuing Personal Activity

```mermaid
flowchart TD
    Input["Host admission or eligible addressed arrival"] --> Owner["Resolve one continuing Agent and requested scope"]
    Owner --> Existing{"Activity already admitted?"}
    Existing -- "Yes" --> Coalesce["Merge input without replacing captured scope"]
    Existing -- "No" --> Admit["Commit admission and register personal worker"]
    Coalesce --> Frame
    Admit --> Frame["Build bounded current frame and available tool view"]
    Frame --> Request["Atomic quota reservation and bounded provider request"]
    Request --> Batch["Complete captured tool batch or ordinary answer"]
    Batch --> Checkpoint["Commit personal context and checkpoint"]
    Checkpoint --> Intent{"Explicit personal intent"}
    Intent -- "continuing" --> Fair["Fair scheduling boundary"]
    Fair --> Frame
    Intent -- "idle" --> Idle["Wait for eligible personal activation"]
    Intent -- "sleep" --> Sleep["Wait with mandatory finite safeguard"]
    Sleep -- "Matching eligible condition or finite deadline" --> Frame
    Idle -- "Eligible addressed arrival" --> Frame
    Request -- "Resource unavailable" --> Resource["Retain distinct availability and retry boundary"]
    Resource -- "Eligible retry or Host remediation" --> Frame
    Batch -- "Explicit publication or institutional tool" --> Domain["Apply that domain's live authority and exact receipt"]
    Domain --> Checkpoint
```

An ordinary answer supplies neither an automatic publication nor a ballot, team-wide completion signal, or idle choice.

AgentTeam membership changes relationships while the Agent retains personal identity, memory, private artifacts, and its serial invocation mechanism.

Notification suppression affects ordinary presentation rather than source delivery or explicit read authority, and protected notices retain their separate bypass rules.

See [Personal Activity](../Personal_Activity.md) for sleep, suppression, recovery, lifecycle, and provider-availability details.
