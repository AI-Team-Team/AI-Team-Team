# ATT Autonomy Suite Flowcharts

This directory contains technical flowcharts and Mermaid sequence diagrams for the ATT autonomy, governance, persistence, and dynamic delegation systems.

## Flowchart Index

1. **[ATT System Architecture](System_Architecture.md)**: Shows the complete system map across host integration, identity, topology, personal activity, governance, knowledge, supervision, persistence, and recovery.
2. **[Autonomous Communication Governance](Autonomous_Communication_Governance.md)**: Shows configuration-owned communication policy, explicit governance principals, request lifecycle, agreements, revocation, and durable peer delivery.
3. **[Lineage Tree Mutations](Lineage_Tree_Mutations.md)**: Shows dynamic AgentTeam spawning, tool binding, membership voting, explicit-principal migration governance, and atomic topology mutation.
4. **[Token-Based File Reading](Gated_Reading.md)**: Shows effective-model counter resolution, token-safe range continuation, and DocLib authorization.
5. **[Tooling & Execution Engines](Tooling_and_Execution.md)**: Shows tool auditing, bounded personal invocations, native tool calling, and parallel tool execution.
6. **[State Persistence & Recovery](State_Persistence.md)**: Shows task-local batching, the coalescing single-writer queue, incremental commits, and validated atomic restore.
7. **[Selective Episodic Memory](Selective_Episodic_Memory.md)**: Shows the optional personal-invocation segmentation, isolated indexing, owner-only search, ephemeral recall, retention, forget, and Journal boundaries.
8. **[Supervision & Emergencies](Supervision_and_Emergencies.md)**: Shows supervisory audits, typed thresholds, fresh temporary audit ATs, and explicit incident handling.
9. **[Registered Execution & Background Tasks](Background_Tasks.md)**: Shows admission, same-execution detachment, owner-only results, notifications, and cancellation evidence.

## Unified High-Level Flow Overview

The ATT suite coordinates these systems through invocation-scoped authority, serialized local decisions, and asynchronous incremental persistence.

```mermaid
flowchart TD
    Task["Admit personal activity or explicitly create an organization"] --> Root["Instantiate Root AI Agent"]
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
    CommPolicy -- "permissive or independent pair" --> Delivery["Durable direct delivery"]
    CommPolicy -- "parent or lineage approval" --> Request["Persist Request and explicit principals"]
    Request --> Decision["Complete exact-case ballots from eligible people"]
    Decision --> Agreement["Create directional Agreement"]
    Agreement --> Delivery
    Delivery --> Persist
    Context --> Migration["Migration policy"]
    Migration --> Governance["Exact actual-principal cases and voluntary personal ballots"]
    Governance --> Topology["Lock, revalidate, and atomically mutate topology"]
    Topology --> Persist
    ToolCall --> Strategy{"Native tools or Text ReAct?"}
    Strategy --> Executor["Shared parser, schema validator, auditor, and classified ToolExecutor"]
    Executor --> Checkpoint["Committed personal checkpoint and sanitized Journal"]
    Checkpoint --> MemoryGate{"Optional episodic memory enabled?"}
    MemoryGate -- "yes" --> Catalog["Background invocation-segment indexing and owner-only recall"]
    Checkpoint --> Continue["Continue, explicit idle or finite sleep"]
    Checkpoint --> Evidence["Typed structural health observations"]
    Evidence -- "Configured threshold" --> Audit["Fresh restricted AT on the same runtime"]
    Audit --> Findings["Complete explicit findings and strict majority"]
    Findings --> Incidents["Retained incidents and explicit handling, not business intervention"]
```
