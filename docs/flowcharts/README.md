# ATT Autonomy Suite Flowcharts

This directory contains technical flowcharts and Mermaid sequence diagrams for the ATT autonomy, governance, persistence, and dynamic delegation systems.

## Flowchart Index

1. **[Autonomous Communication Governance](Autonomous_Communication_Governance.md)**: Shows configuration-owned communication policy, explicit governance principals, request lifecycle, agreements, revocation, and durable peer delivery.
2. **[Lineage Tree Mutations](Lineage_Tree_Mutations.md)**: Shows dynamic AgentTeam spawning, tool binding, membership voting, explicit-principal migration governance, and atomic topology mutation.
3. **[Gated FileReader Size Limits](Gated_Reading.md)**: Shows the `read_file` size protection, outline fallback, and line-window behavior.
4. **[Tooling & Execution Engines](Tooling_and_Execution.md)**: Shows tool auditing, multi-round ReAct execution, native tool calling, and parallel tool execution.
5. **[State Persistence & Recovery](State_Persistence.md)**: Shows task-local batching, the coalescing single-writer queue, incremental commits, and validated atomic restore.
6. **[Supervision & Emergencies](Supervision_and_Emergencies.md)**: Shows supervisory audits, UNKNOWN alert lifecycle, parent escalation, and emergency wakeups.

## Unified High-Level Flow Overview

The ATT suite coordinates these systems through invocation-scoped authority, serialized local decisions, and asynchronous incremental persistence.

```mermaid
flowchart TD
    Task["Run AgentTeam discussion or reasoning task"] --> Root["Instantiate Root AI Agent"]
    Root --> Spawn{"Spawn dynamic AgentTeam?"}
    Spawn -- "Yes" --> Identity["Create AgentTeam<br/>Register stable Agent identities<br/>Create team and private DocLibs<br/>Bind manager-owned tools"]
    Identity --> ToolCall{"Agent invokes a tool?"}
    ToolCall --> Context["Resolve active Agent and AgentTeam ContextVars"]
    Context --> Files{"DocLib operation?"}
    Files -- "Team DocLib" --> ACL["Check real-time path ACL"]
    Files -- "Private DocLib" --> Owner["Check active Agent ownership"]
    ACL --> Persist["Incremental single-writer commit"]
    Owner --> Persist
    Context --> Peer{"Peer communication?"}
    Peer --> CommPolicy{"ATTConfig.communication policy"}
    CommPolicy -- "permissive" --> Delivery["Durable direct delivery"]
    CommPolicy -- "parent or lineage approval" --> Request["Persist Request and explicit principals"]
    Request --> Decision["AgentTeam ballots or explicit Agent decision"]
    Decision --> Agreement["Create directional Agreement"]
    Agreement --> Delivery
    Delivery --> Persist
    Context --> Migration["Migration policy"]
    Migration --> Governance["Explicit AgentTeam or Root Agent decisions"]
    Governance --> Topology["Lock, revalidate, and atomically mutate topology"]
    Topology --> Persist
    ToolCall --> Strategy{"Native tools or Text ReAct?"}
    Strategy --> Executor["Shared parser, schema validator, auditor, and classified ToolExecutor"]
    Executor --> Turn["AgentTurnResult: completed or incomplete"]
    Turn --> Discussion["Serialized AgentTeam discussion with concurrent member turns"]
    Discussion --> Detailed["DiscussionResult: completed or partial"]
    Detailed --> Audit["Independent content and operational health"]
    Audit -- "healthy" --> Done["Return structured result or transcript wrapper"]
    Audit -- "content anomaly, unknown, or configured degradation" --> Escalate["Persist, deduplicate, and route parent/root event"]
```
