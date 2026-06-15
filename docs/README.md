# AI Autonomy Suite: ATT (AI Team Team) Topology

Welcome to the technical specifications and architectural guide for the **ATT (AI Team Team) Autonomy Suite**.

This directory contains deep-dive design guides, parameters, and operation specs for each module of our self-governing multi-agent framework.

## Document Directory

To understand specific systems in detail, please refer to the following documents:

### 👤 User Guides

1. **[Quickstart Integration Guide](user/Quickstart.md)**: A step-by-step tutorial on how to install, register custom tools, implement LLM client adapters, and run agent debates.
2. **[Public API Reference](user/API_Reference.md)**: A clean, public-only reference for all external integration classes (`ATTManager`, `Agent`, `ATTConfig`, etc.).

### 🛠️ System Specifications & Dev Docs

1. **[Hierarchical Dynamic Delegation](Dynamic_Delegation.md)**: Explains the recursive `Agent` and `AgentTeam` lineages (Level 0 Root AI spawning Level 1 ATs, which recursively spawn deeper sub-teams of Level $N$), ReAct execution loops with safe literal evaluation, and the lineage escalation channels.
2. **[Gated Context Protection & File Reading](Gated_Reading.md)**: Details the size-aware `GatedFileReader`, outline sampling fallbacks for files exceeding 50 KB, paginated line chunking, and streaming tail log reads.
3. **[Supervisor Auditor Team](Supervisory_Team.md)**: Details the dynamic **3-AI Supervisory Team** (Integrity, Continuity, and Deadlock Auditors) which monitors dialogue transcripts for circular deadlocks and performs recursive lineage parent escalations.
4. **[Developer Testing & Mocking Guide](dev/testing.md)**: Guidelines for writing unit tests and mocking sequence responses.
5. **[Developer API Reference](dev/API_Reference.md)**: Reference listing system internals and execution logic.

## 📊 Visual Flowcharts Directory

For visual diagrams sequencing ATT loops, refer to the flowchart index and specific diagrams:

* **[Autonomy Flowcharts Index](flowcharts/README.md)**: Overview diagram of all coordinating processes.
* **[Spawning & Escalation Flowchart](flowcharts/Spawning_Escalation.md)**: Visualizes parent escalation alerts and child team creations.
* **[Gated Reading Slicing Sequence](flowcharts/Gated_Reading.md)**: Visualizes line chunk slicing logic and outline fallbacks.
* **[Negotiation Broker Routing Sequence](flowcharts/Negotiation_Broker_Sibling_Routing.md)**: Sequences sibling and cross-lineage P2P talk approvals.
* **[Supervisory Team Audit Sequence](flowcharts/Supervisory_Team_Audit.md)**: Sequences dialogue auditing and ancestor anomaly routing.

## Core Architecture Overview

The ATT Topology transitions AI agents from passive context-consumers to active, collaborative team groups. It is built on a recursive team model coordinated by the master `ATTManager`:

```plaintext
                     ┌──────────────────────────────┐
                     │    Supervisory Auditor Team  │
                     │       (Exactly 3 AIs)        │
                     └──────────────┬───────────────┘
                                    │ Audits Dialogue Logs
                                    ▼
                     ┌──────────────────────────────┐
                     │         ATT Manager          │
                     └──────────────┬───────────────┘
                                    │ Coordinates Lineages
                      ┌─────────────┴─────────────┐
                      ▼                           ▼
         ┌────────────────────────┐   ┌────────────────────────┐
         │    Agent Team (AT)     │   │    Agent Team (AT)     │
         │      (Size N >= 3)     │   │      (Size N >= 3)     │
         │ ┌────────────────────┐ │   └────────────────────────┘
         │ │ Democratic Voting  │ │
         │ │   (Threshold 2/3)  │ │
         │ └────────────────────┘ │
         └────────────────────────┘
```
