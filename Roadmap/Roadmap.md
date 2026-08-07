# ATT (AI-Team-Team) Framework Evolution Roadmap

This document outlines the design blueprints, architectural optimizations, and next-generation evolution paths for the **AI-Team-Team (ATT)** multi-agent orchestration framework.

## 🎯 Overview

The next iterations focus on sociological architecture and self-evolution: expanding ATT from a strict tree topology into a dynamic, self-restructuring society capable of creating its own tools, managing resources, and hibernating inactive populations.

## Next-Gen Evolution Path

### 1. Self-Evolving Tool Synthesis (Dynamic Tool Forging)

- **Concept**: Empower AI teams to dynamically generate, test, and register new Python tools at runtime when existing capabilities are insufficient.
- **Implementation Strategy**:
  - Introduce a `ToolLibrary` mechanism, mirroring the ACL structure of `DocLib`.
  - Equip a specialized `ToolMaker` agent with access to an isolated code sandbox.
  - Expose a `manager.forge_tool()` API, which securely compiles (`exec`) LLM-generated code strings into native Callables, attaching them to a designated `ToolLibrary` with READ/WRITE permission tracking.

### 2. Private Agent DocLib (Persistent Personal Workspace) — Implemented

- **Concept**: Give every registered AI one durable private document library for deliberate notes, hypotheses, plans, research summaries, and cross-team experience. It stores user-visible work artifacts and never captures or infers hidden model reasoning.
- **Implemented Architecture**:
  - A stable Agent UUID owns exactly one `PDL-<agent_id>` library across all team memberships.
  - Private access is resolved only from invocation-scoped agent identity; team ACLs, public discovery, metadata APIs, and managed links cannot expose a private library.
  - An AI explicitly reads its own files or copies a selected file into the current team's built-in DocLib. Private content is never automatically inserted into prompts, transcripts, audits, callbacks, or message history.
  - Retain, archive, reactivate, and confirmed permanent-delete policies provide an auditable lifecycle backed by schema 5 persistence and atomic restore validation.

### 3. Multi-Parent DAG Topology (Team Subscription Modeling)

- **Concept**: Evolve the strict Tree lineage topology into a Directed Acyclic Graph (DAG) for task assignment, maximizing resource utilization while preserving organizational safety constraints.
- **Implementation Strategy**:
  - Maintain the strict `parent_team` property for core administrative lifecycle events (e.g., token budgeting, emergency escalation, and lineage migration).
  - Introduce a `subscribed_parents` property to `AgentTeam`, representing "Client" teams that outsource tasks to a shared service team (e.g., a centralized coding or data-analysis team).
  - This allows multiple independent teams to route task payloads into a single highly specialized team's inbox without violating the overall administrative lineage.

### 4. Dynamic Runtime Restructuring (Merging & Headcount Control)

- **Concept**: Provide high-level administrative endpoints to forcefully reshape the organization chart (e.g., merging overlapping teams, injecting rescue agents) without relying on the slow, democratic member-voting pipelines.
- **Implementation Strategy**:
  - Introduce a `manager.merge_teams(target_id, source_id)` API: Safely transfers members, ToolLibs, DocLibs, and active proposals from the source to the target, subsequently garbage collecting the source team.
  - Introduce direct `add_member` and `remove_member` bypass hooks for the Supervisory Team or Root Admin to forcefully adjust headcount in response to production crises.

### 5. Cold Storage & Event-Driven Hibernation

- **Concept**: Support deployments scaling up to tens of thousands of registered AI agents by swapping idle teams out of active memory.
- **Implementation Strategy**:
  - Introduce an `.hibernate()` action for idle teams, serializing their entire memory buffer and state to the SQLite store and removing them from the active Python event loop.
  - Integrate a central Event Bus that triggers a "Wakeup" (`deserialize_and_resume`) only when an external event occurs or a targeted peer message is delivered to their inbox.
