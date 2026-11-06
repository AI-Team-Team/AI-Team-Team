# ATT (AI-Team-Team) Framework Evolution Roadmap

This document outlines the design blueprints, architectural optimizations, and next-generation evolution paths for the **AI-Team-Team (ATT)** multi-agent orchestration framework.

## 🎯 Overview

The next iterations explore organizational autonomy, tool evolution, resource management, and large-population storage beyond the implemented explicit-parent forest.

Except where marked implemented, these are research proposals rather than current APIs or confirmed permissions.

The [autonomous Agent runtime architecture](../docs/Autonomous_Agent_Runtime_Architecture/README.md), [database architecture](../docs/Database/README.md), and current [user guides](../docs/README.md) define the implemented system.

## Next-Gen Evolution Path

### 1. Self-Evolving Tool Synthesis (Dynamic Tool Forging)

- **Concept**: Empower AI teams to dynamically generate, test, and register new Python tools at runtime when existing capabilities are insufficient.
- **Implementation Strategy**:
  - Introduce a `ToolLibrary` mechanism, mirroring the ACL structure of `DocLib`.
  - Equip a specialized `ToolMaker` agent with access to an isolated code sandbox.
  - Expose a `manager.forge_tool()` API, which securely compiles (`exec`) LLM-generated code strings into native Callables, attaching them to a designated `ToolLibrary` with READ/WRITE permission tracking.

### 2. Private Agent DocLib (Persistent Personal Workspace) — Implemented

- **Concept**: Give every registered AI one durable private document library for deliberate notes, hypotheses, plans, research summaries, and cross-team experience.
  It stores user-visible work artifacts and never captures or infers hidden model reasoning.
- **Implemented Architecture**:
  - A stable Agent UUID owns exactly one `PDL-<agent_id>` library across all team memberships.
  - Private access is resolved only from invocation-scoped agent identity; team ACLs, public discovery, metadata APIs, and managed links cannot expose a private library.
  - An AI explicitly reads its own files or copies a selected file into the current team's built-in DocLib.
  - Private content is never automatically inserted into prompts, shared conversations, audits, callbacks, or the Journal.
  - Retain, archive, reactivate, confirmed permanent deletion, and terminal retained death use the [current persistence contract](../docs/State_Persistence.md) and atomic restore validation.

### 3. Multi-Parent DAG Topology (Team Subscription Modeling)

- **Concept**: Evolve the strict Tree lineage topology into a Directed Acyclic Graph (DAG) for task assignment, maximizing resource utilization while preserving organizational safety constraints.
- **Implementation Strategy**:
  - Maintain the strict `parent_team` property for core administrative lifecycle events (e.g., token budgeting, emergency escalation, and lineage migration).
  - Introduce a `subscribed_parents` property to `AgentTeam`, representing "Client" teams that outsource tasks to a shared service team (e.g., a centralized coding or data-analysis team).
  - This allows multiple independent teams to route task payloads into a single highly specialized team's inbox without violating the overall administrative lineage.

### 4. Dynamic Runtime Restructuring (Merging & Headcount Control)

- **Concept**: Explore explicit administrative merging and recovery operations with separately confirmed authority, consent, and rollback rules.
- **Status**: Unconfirmed research; no `merge_teams()` API or supervisory membership-bypass permission is supplied by this proposal.
- **Design constraints**: Preserve stable people and their private data, exact institutional decisions, historical memberships and conversations, resource ownership, and atomic publication.

Health findings and Root identity do not themselves authorize membership, file, model, or business changes.

### 5. Cold Storage & Event-Driven Hibernation

- **Concept**: Support deployments scaling up to tens of thousands of registered AI agents by swapping idle teams out of active memory.
- **Implementation Strategy**:
  - Explore reclaiming inactive organizational caches while retaining team records and each person's independently owned persistent state.
  - Define explicit addressed activation and storage-reconstruction boundaries without creating duplicate people or treating a message as institutional consent.

Any future cold-storage design must preserve Agent-owned memory independently of team storage and distinguish reconstruction from the already implemented personal sleep and wake mechanism.

### 6. Operational and Lineage Viewer

Build a lightweight Host-facing viewer for explicit organizational parents, memberships, personal activity, model/tool waits, pending institutional cases, and background execution evidence.

Display actual observable state and authorized messages rather than inferred thinking or automatically generated debate transcripts.

Use current inspection APIs and metadata events while preserving independent identities and existing privacy boundaries.

### 7. Interactive Human Approval for Tools

Explore an interactive Host approval interface over existing synchronous/asynchronous tool auditing for selected destructive or expensive operations.

Define exact operation identity, waiting and cancellation behavior, scope revalidation, and explicit refusal before implementing the interface.

Existing asynchronous auditor support is infrastructure rather than a completed interactive human-approval workflow.

### 8. Structured JSON Actions for Text Mode

Evaluate a provider-neutral JSON Action protocol that can replace or take precedence over Python-call and XML text syntax.

Preserve strict nested validation, typed observations, argument-correction feedback, invocation scope, and Native/Text semantic parity.

### 9. Topics, Channels, and Threads

Explore optional organization of the current simple team and direct streams into topics, channels, or threads.

Define hierarchy, participation, source-reference visibility, navigation, notification, and archival rules before adding a new API.

Preserve personal read state, author-only revisions and withdrawal, frozen departure views, and absence-period exclusions.

### 10. Immediate Communication-Approval Handling

Research an explicit communication request-delivery `wake` mode, while the implemented institution continues to use voluntary personal mail through `queue`.

Define interaction with sleep, permanent/timed suppression, active invocation ownership, unavailable providers, and unanswered ballots.

Immediate handling cannot fabricate a decision, select another principal or voter, or start a concurrent copy of the person.

Protected system notices and ordinary timer wake already have their own implemented contracts and are not deferred by this proposal.

### 11. Long-Lived Supervisory Teams

Explore preconfigured long-lived ATT-managed audit teams as an alternative to the implemented fresh restricted team per assessment.

Specify audit-to-audit memory isolation, permitted evidence, restricted tools, reset/replacement, concurrency, shutdown, and recovery before reusing any audit identity.

Use the common Manager and AgentTeam mechanisms and retain health-only assessment, structured full participation, and the absence of implicit repair authority.

### 12. Git-Backed Team DocLib Collaboration

Explore authorized clone, branch, and push workflows for team libraries, with explicit private/shared workspaces, branch authority, merge handling, and live ACL mapping.

Force operations require authorization of the exact operation through the configured institution; electorate, threshold, affected references, and scope require separate design.

Friendship, membership consent, and repository access remain independent authorities.

The current implementation serializes conflicting resources and permits semantic last-writer overwrite without optimistic read-modify-write checks or overwrite confirmation.

## Existing Health Assessment

Evidence-specific detection, retained incidents, real temporary audit teams, independent health dimensions, and strict findings are implemented in [Supervisory Team](../docs/Supervisory_Team.md).

The old generic future-health item is superseded by that implemented contract rather than a remaining single-turn failure mechanism.

Any broader detector research needs a separately defined signal and authority contract without capturing hidden reasoning or assessing business progress.

## Historical Research Sources

The [original Todo](../docs_archive/todo.md) and [deferred autonomous-activity proposals](../docs_archive/blueprints/Todo_Autonomous_Agent_Activity_Messaging_and_Background_Tasks.md) remain preserved unchanged.

Their relevant unimplemented directions are organized above as research, without changing current defaults or granting new permissions.
