# AI Autonomy Suite: ATT (AI Team Team) Topology

Welcome to the technical specifications and architectural guide for the **ATT (AI Team Team) Autonomy Suite**.

This directory contains deep-dive design guides, parameters, and operation specs for each module of our self-governing multi-agent framework.

## Document Directory

To understand specific systems in detail, please refer to the following documents:

### 👤 User Guides

1. **[Quickstart Integration Guide](user/Quickstart.md)**: A step-by-step tutorial on how to install, register custom tools, implement LLM client adapters, and admit continuing personal activity.
2. **[Public API Reference](user/API_Reference.md)**: A clean, public-only reference for all external integration classes (`ATTManager`, `Agent`, `ATTConfig`, etc.).
3. **[Continuing Personal Activity](Personal_Activity.md)**: Admission, answers, checkpoints, scope, sleep, reminder preferences, resource availability, and retained lifecycle.
4. **[Personal and AgentTeam Conversations](Personal_Conversations.md)**: Deliberate Markdown publication, previews, read state, edits, withdrawal, contact controls, and personal archives.
5. **[Registered Execution and Background Tasks](Background_Tasks.md)**: Whitelist declarations, same-owned detachment, resources, factual outcomes, attention, protected results, and stop limits.

### 🛠️ System Specifications & Dev Docs

1. **[Hierarchical Dynamic Delegation](Dynamic_Delegation.md)**: Explains explicit-parent organizational forests, nonblocking creation and consent, bounded personal tool protocols, and authorized escalation.
2. **[Token-Based File Reading](Gated_Reading.md)**: Details effective-model token budgets, line and character continuation, collaborative team DocLib ACLs, and persistent Private Agent DocLib boundaries.
3. **[Supervisory Team](Supervisory_Team.md)**: Details the short-lived, registered supervisory AgentTeam created for each audit, its fresh auditors on the common runtime, durable evidence, and persistent incident handling.
4. **[State Persistence & Personal Memory](State_Persistence.md)**: Explains the asynchronous single-writer SQLite design, incremental deltas, validated recovery, personal memory, and source-linked context compaction.
5. **[Selective Episodic Memory](Selective_Episodic_Memory.md)**: Defines the optional Agent-owned Memory Catalog, immutable Journal boundary, isolated indexing, ephemeral recall, tool capture policy, and current-schema recovery rules.
6. **[Consensual Existing-Agent Team Formation](Consensual_Team_Formation.md)**: Defines persistent Agent identity inboxes, revision-bound invitation attitudes, immutable proposal history, optional initiator-authored candidates, accepted-subset creation, late joining, trusted bootstrap, and the invariant that membership never mutates Agent-owned state.
7. **[Team Governance & Communication Policies](Team_Governance.md)**: Details configuration-owned communication, actual AgentTeam or Agent principals, durable Requests and Agreements, migration policies, token-budget failover, and explicit incident handling.
8. **[Tool Execution & Development System](Tool_System.md)**: Explains Text ReAct and Native tool calling, strict schema validation, classified tool outcomes, tool registration, and `ToolAuditor` pre-execution hooks.
9. **[Core Objects Model](Core_Objects_Model.md)**: A deep-dive architectural data dictionary defining the internal memory mechanics and states of `ATTManager`, `AgentTeam`, and `Agent`.
10. **[Developer Testing & Mocking Guide](dev/testing.md)**: Guidelines for writing unit tests and mocking sequence responses.
11. **[Developer API Reference](dev/API_Reference.md)**: Reference listing system internals and execution logic.
12. **[Agent and AgentTeam Discovery](Agent_and_AgentTeam_Discovery.md)**: Defines on-demand public directory listing, case-insensitive OR keyword search, stable-ID inspection, inclusive entity-position ranges, lifecycle scope, and independent authorization boundaries.
13. **[Performance Measurement](dev/Performance_Measurement.md)**: Defines reproducible persistence and runtime measurements, instrumentation boundaries, and correctness gates.

### Design Blueprints & Implementation Plans

The [Design Blueprints index](blueprints/README.md) separates target behavior, engineering delivery, and deferred features from the current-runtime guides above.

* **[Autonomous Agent Activity, Messaging, and Background Tasks](blueprints/Autonomous_Agent_Activity_Messaging_and_Background_Tasks/README.md)**: The governing design for continuing personal activity, explicit communication, background execution, and recovery.
* **[Implementation Plan](blueprints/Implementation_plan_Autonomous_Agent_Activity_Messaging_and_Background_Tasks/README.md)**: Confirmed decisions, engineering contracts, implementation phases, and acceptance gates.
* **[Future Plans](blueprints/Todo_Autonomous_Agent_Activity_Messaging_and_Background_Tasks.md)**: Deferred features outside the initial replacement scope, not an implementation-progress checklist.
* **[Autonomous Activity Implementation](dev/autonomous_activity/README.md)**: Engineering contracts, phase-specific implementation and verification records, schema profiles, and dependency inventories.

Use the current guides above for integration and the numbered phase profiles for historical implementation evidence.

## 📊 Visual Flowcharts Directory

For visual diagrams sequencing ATT loops, refer to the flowchart index and specific diagrams:

* **[ATT System Architecture](flowcharts/System_Architecture.md)**: Maps module relationships, personal activity, institutional authority, knowledge, supervision, and durability.
* **[Autonomy Flowcharts Index](flowcharts/README.md)**: Index of the system architecture and topic diagrams.
* **[Lineage Tree Mutations](flowcharts/Lineage_Tree_Mutations.md)**: Visualizes child creation, membership voting, and explicitly governed migration.
* **[Token-Based File Reading Sequence](flowcharts/Gated_Reading.md)**: Visualizes effective-model counter resolution, token-safe continuation, and DocLib authorization.
* **[Autonomous Communication Governance](flowcharts/Autonomous_Communication_Governance.md)**: Sequences configuration selection, explicit-principal approval, Agreement creation, delivery, and revocation.
* **[Supervision and Emergencies](flowcharts/Supervision_and_Emergencies.md)**: Sequences typed health evidence, fresh temporary audits, and explicit incident attention.
* **[State Persistence Flowchart](flowcharts/State_Persistence.md)**: Sequences incremental SQLite commits, staged recovery, and atomic runtime and file publication.
* **[Tooling and Execution](flowcharts/Tooling_and_Execution.md)**: Sequences personal admission, provider protocols, common tool execution, and receipt boundaries.
* **[Selective Episodic Memory](flowcharts/Selective_Episodic_Memory.md)**: Visualizes optional indexing, owner-only search and recall, and Journal ownership.
* **[Registered Execution and Background Tasks](flowcharts/Background_Tasks.md)**: Visualizes execution admission, detachment, protected results, and cancellation evidence.
* **[Personal Conversations](flowcharts/Personal_Conversations.md)**: Visualizes explicit publication, contact controls, independent read state, and frozen departure archives.
* **[Continuing Personal Activity](flowcharts/Personal_Activity.md)**: Visualizes personal admission, captured invocation scope, explicit intent, checkpoints, and resource availability.
