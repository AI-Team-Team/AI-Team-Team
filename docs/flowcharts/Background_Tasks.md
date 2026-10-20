# Registered Execution and Background Tasks

```mermaid
flowchart TD
    Call[Explicit background request or ordinary tool call] --> Validate[Available tool, strict arguments, scope, and declared effects]
    Validate --> Admit[Commit execution identity and protected input]
    Admit --> Queue[Wait for capacity and canonical resources]
    Queue --> Start[Start one registered executor]
    Start --> Wait{Foreground observation}
    Wait -->|Completes first| Result[Return the normal tool result]
    Wait -->|Explicit background or elapsed threshold| Handle[Return one task handle]
    Handle --> Continue[Same Agent may continue other activity]
    Start --> Outcome[Commit factual outcome, protected result, attention, and notification]
    Outcome --> Boundary[Same owner's next eligible personal boundary]
    Boundary --> Inspect[Deliberate owner-only task and result inspection]
    Inspect --> Ack[Optional attention acknowledgement]
    Cancel[Owner requests cancellation] --> Evidence[Record request separately from actual acknowledgement]
    Evidence --> Outcome
```

Automatic detachment starts from actual execution time, excludes initial queueing, and never restarts the operation.

The original provider call receives one observation, while later results use personal notification rather than a second tool reply.

Source and mutation permissions remain live, and interruption recovery never automatically replays or reconnects a historical execution.
