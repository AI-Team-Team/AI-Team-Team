# ATT Autonomy Suite Flowcharts

This directory contains detailed technical flowcharts and Mermaid sequencing diagrams detailing the operational control flows of the **ATT (AI Team Team) Autonomy & Dynamic Delegation Suite**.

> [!NOTE]
> All flowcharts in this directory are fully updated, aligned with the Python package specifications, and represent the actual runtime execution control flows.

## Flowchart Index

Please refer to the following documents for granular flow diagrams:

1. **[Spawning, Escalation & Migration](Spawning_Escalation.md)**: Details the recursive `AgentTeam` lineages (Level 0 Root AI spawning Level 1 ATs, which recursively spawn deeper sub-teams of Level $N$), closed-loop parent escalation alerts, and LLM-arbitrated parent migrations.
2. **[Gated Paginator Reading](Gated_Reading.md)**: Visualizes the context protection pre-filters, outline warnings, paginated chunk slicing, and the segment-based DocLib ACL path permission resolution.
3. **[Negotiation Broker & Sibling Routing](Negotiation_Broker_Sibling_Routing.md)**: Sequences the dynamic P2P sibling and cross-lineage communication permissions negotiated by the `NegotiationBroker`.
4. **[Supervisory Team Audits & Escalations](Supervisory_Team_Audit.md)**: Diagrams the 3-AI Supervisory Team's dialogue auditing and the recursive parent-ancestor climb escalation process.
5. **[State Persistence & Recovery](State_Persistence.md)**: Visualizes the SQLite-backed auto-saving event triggers and the manager's two-pass deserialization pipeline.
6. **[Discussion & ReAct Execution Loop](Execution_Loop.md)**: Visualizes the master multi-round debate sequence and the granular agent turn ReAct execution step compilation.
7. **[Lineage Migration Arbitration Sequence](Lineage_Migration_Arbitration.md)**: Diagrams the step-by-step Least Common Ancestor (LCA) resolution, representatives harvesting, and LLM arbitration rounds during team migrations.

## Unified High-Level Flow Overview

The ATT Suite coordinates the interaction of these four systems in a decoupled, event-driven pattern:

```mermaid
flowchart TD
    Task["Run Dynamic Committee debate or ReAct task"] --> RootNode["1. Instantiate Root AI (Level 0)"]
    
    RootNode --> Spawning{"2. Spawn dynamic Agent Team (AT)?"}
    Spawning -- "Yes" --> SpawningCheck["Create AgentTeam (N >= 3)\nValidate member_configs / roles\nBind Centralized Tools context\nInstantiate default DocLib"]
    
    SpawningCheck --> ToolCall{"3. Agent executes reasoning step?"}
    
    ToolCall -- "execute_reasoning_step" --> StrategyCheck{"Supports native tool calling?"}
    
    StrategyCheck -- "Yes (Native Mode)" --> NativeStrategy["Native tool calling strategy:<br/>1. Fetch schemas from resolver<br/>2. generate(prompt, tools=schemas)<br/>3. asyncio.gather() parallel execution"]
    StrategyCheck -- "No (Text ReAct Mode)" --> TextReAct["Text ReAct strategy:<br/>1. Thought-Action-Observation loop<br/>2. Parse XML tags or regex Actions<br/>3. Parse arguments via ast.literal_eval"]
    
    NativeStrategy --> ExecTool["Execute bound tool(s)<br/>(Intercepted by pre-execution ToolAuditor)"]
    TextReAct --> ExecTool
    
    ToolCall -- "Library File Access" --> DocLibPermission{"Has READ/WRITE permission?"}
    DocLibPermission -- "No" --> Denied["Return Permission Denied"]
    DocLibPermission -- "Yes (Read)" --> GatedFileReader["GatedFileReader Gated Check"]
    DocLibPermission -- "Yes (Write/Delete)" --> ExecDoc["Modify library files"]
    
    GatedFileReader -- "File exceeds 50KB and No range" --> Outline["Return Outline Warning (first 5 lines + metadata)"]
    GatedFileReader -- "Safe Size OR Window" --> Chunk["Return line-numbered paginated chunk (max 100 lines)"]
    
    ToolCall -- "Peer Sibling Talk" --> NegotiationBroker["NegotiationBroker dispatch"]
    NegotiationBroker -- "Sibling AT" --> SiblingRule{"Parent rules allow_sibling_talk?"}
    NegotiationBroker -- "Cross-Lineage AT" --> ParentNegotiate["Parents negotiate agreement via Policy:<br/>Permissive / RuleGated / Proxied"]
    
    ToolCall -- "Voting Actions" --> Voting{"Democratic Voting Process"}
    Voting -- "Unanimous participation & >= 2/3 Agree" --> ExecVote["Update team membership (add/remove member)<br/>Save to SQLite DB"]
    
    ToolCall -- "Lineage Migration" --> MigrationCheck{"MigrationPolicy evaluation:<br/>Permissive / AncestorApproval / LineagePath"}
    MigrationCheck -- "Approved (LCA representative debate)" --> MigrationExec["1. Restructure tree pointers<br/>2. Save to SQLite DB<br/>3. Inject Context Transition Notice"]
    
    ToolCall -- "Discussion finished" --> SupervisoryTeam["3-AI Supervisory Team (Integrity, Continuity, Deadlock) audits logs"]
    SupervisoryTeam -- "Anomaly found (is_healthy = False)" --> Escalate["Climb lineage up to find healthy parent<br/>Route Failure Alert to Parent Inbox (triggers emergency wakeup)"]
```
