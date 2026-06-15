# ATT Autonomy Suite Flowcharts

This directory contains detailed technical flowcharts and Mermaid sequencing diagrams detailing the operational control flows of the **ATT (AI Team Team) Autonomy & Dynamic Delegation Suite**.

> [!NOTE]
> All flowcharts in this directory were largely written by Gemini and the content described at present is incomplete, \
> so it is for reference only.

## Flowchart Index

Please refer to the following documents for granular flow diagrams:

1. **[Spawning, Escalation & Migration](Spawning_Escalation.md)**: Details the recursive `AgentTeam` lineages (Level 0 Root AI spawning Level 1 ATs, which recursively spawn deeper sub-teams of Level $N$), closed-loop parent escalation alerts, and LLM-arbitrated parent migrations.
2. **[Gated Paginator Reading](Gated_Reading.md)**: Visualizes the context protection pre-filters, outline generation samples, and paginated line-numbered chunk slicing logic.
3. **[Negotiation Broker & Sibling Routing](Negotiation_Broker_Sibling_Routing.md)**: Sequences the dynamic P2P sibling and cross-lineage communication permissions negotiated by the `NegotiationBroker`.
4. **[Supervisory Team Audits & Escalations](Supervisory_Team_Audit.md)**: Diagrams the 3-AI Supervisory Team's dialogue auditing and the recursive parent-ancestor climb escalation process.

## Unified High-Level Flow Overview

The ATT Suite coordinates the interaction of these four systems in a decoupled, event-driven pattern:

```mermaid
flowchart TD
    Task["Run Dynamic Committee debate or ReAct task"] --> RootNode["1. Instantiate Root AI (Level 0)"]
    
    RootNode --> Spawning{"2. Spawn dynamic Agent Team (AT)?"}
    Spawning -- "Yes" --> SpawningCheck["Create AgentTeam (N >= 3)\nValidate member_configs / roles\nBind Centralized Tools context"]
    
    SpawningCheck --> ToolCall{"3. Agent executes ReAct step?"}
    
    ToolCall -- "Action: tool(args)" --> SafeParser["Parse args using ast.literal_eval"]
    SafeParser --> ExecTool["Execute bound tool"]
    
    ToolCall -- "Read File" --> GatedFileReader["GatedFileReader Gated Check"]
    GatedFileReader -- "File exceeds 50KB and No Slice" --> Outline["Return File Outline Sample"]
    GatedFileReader -- "Safe Size OR Window" --> Chunk["Return Paginated Lines Chunk"]
    
    ToolCall -- "Peer Sibling Talk" --> NegotiationBroker["NegotiationBroker dispatch"]
    NegotiationBroker -- "Sibling AT" --> SiblingRule{"Parent rules allow?"}
    NegotiationBroker -- "Cross-Lineage AT" --> ParentNegotiate["Parents agreement debate"]
    
    ToolCall -- "Voting Actions" --> Voting{"Democratic Voting Process"}
    Voting -- "Unanimous participation & >= 2/3 Agree" --> ExecVote["Update team membership (add/remove)"]
    
    ToolCall -- "Discussion finished" --> SupervisoryTeam["3-AI Supervisory Team audits dialogue logs"]
    SupervisoryTeam -- "Anomaly found (is_healthy = False)" --> Escalate["Climb lineage up to find healthy parent\nRoute Failure Alert to Parent Inbox"]
```
