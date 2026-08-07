# ATT (AI-Team-Team) Framework Evolution Roadmap

This document outlines the design blueprints, architectural optimizations, and next-generation evolution paths for the **AI-Team-Team (ATT)** multi-agent orchestration framework.

## 🎯 Overview

The next iterations of the ATT framework focus on:

1. **Robustness & Security Gating**: Hardening parser resilience, isolating exceptions, and enforcing organizational migration limits.
2. **Sociological Architecture & Self-Evolution**: Expanding the framework from a strict tree topology into a dynamic, self-restructuring society capable of creating its own tools, managing its own resources, and hibernating inactive populations.

## Reliability and Production Hardening Track

This track should precede topology expansion and other next-generation features.
It converts the currently confirmed correctness and operational gaps into staged
architectural work.

### 1. Discussion and Budget Transaction Boundaries

- Add a per-team discussion-session lock that covers session admission, migration
  counter reset, inbox handoff, proposal execution, audit, and final status cleanup.
  Define whether callers wait or receive an explicit `DiscussionAlreadyRunning`
  error.
- Introduce an atomic token ledger per model alias. Reserve prompt/output allowance
  before dispatch, reconcile actual response tokens afterward, and release unused
  reservations on errors or cancellation. Failover candidate selection must read
  the same ledger.
- Parse every LLM authorization response through a strict typed schema. Only a
  literal boolean `true` grants authority; missing, string, numeric, or malformed
  values fail closed and produce an auditable reason.

### 2. Transactional Restore and Filesystem Publication

- Read and validate a snapshot into detached staging objects before changing the
  live manager. Validate all agent/member/creator/parent/library references, unique
  identifiers, cycles, model aliases, and configuration constraints. Recompute
  derived depth values rather than loading caches.
- Stage DocLib contents in sibling temporary directories, reject symlink components
  with no-follow filesystem operations, and atomically rename completed trees into
  place. Keep the old tree recoverable until the manager-state commit succeeds.
- Swap validated registries and filesystem roots as one coordinated commit. On any
  error, retain the original manager, DocLib data, database path, and runtime
  bindings unchanged.

### 3. Bounded and Coordinated Persistence

- Replace the unbounded future list with a bounded admission queue. Coalesce pending
  deltas by database path and entity key, discard completed futures promptly, expose
  queue-depth/latency metrics, and define whether overload waits, rejects, or forces
  a full snapshot.
- Probe schema metadata and version in read-only mode before running any DDL. Only
  initialize tables for a confirmed new database; reject unsupported state files
  without modifying them.
- Configure SQLite deliberately: enable foreign-key enforcement, choose and document
  WAL behavior, set a busy timeout, and test crash recovery. Define writer ownership
  across managers and processes; use a cross-process lock or reject a second writer
  when logical delta ordering cannot be guaranteed.
- Require stable registered model aliases at snapshot time. Never silently collapse
  an unknown runtime client into the default binding.
- Move expensive snapshot serialization/copying off the event-loop thread or build
  immutable state incrementally, while keeping capture ordering deterministic.

### 4. Runtime Context, Shutdown, and Event Delivery

- Replace cached agent ownership with explicit invocation-scoped team context and
  reject ambiguous ownership where a unique team is required.
- Add shutdown deadlines and cancellation propagation for emergency discussions,
  model calls, callbacks, and persistence flushing. Report unfinished work instead
  of waiting forever.
- Classify retryable failures by typed exceptions/provider status rather than error
  strings. Programming, schema, and authorization failures must fail immediately.
- Support async callbacks or dispatch synchronous callbacks through a bounded
  executor/event bus. Preserve callback ordering and isolate callback failures from
  discussion correctness.
- Give queued audit alerts a capacity, TTL, stable fingerprint, acknowledgement
  state, and durable deduplication window. Emit overflow and expiry system events.

### 5. Fault-Injection and Stress Verification

- Add deterministic races for duplicate team discussions and concurrent token
  reservations at the exact quota boundary.
- Corrupt each persisted reference class and verify that failed restore leaves the
  live manager and DocLib trees byte-for-byte unchanged.
- Test symlink substitution, crash points during directory publication, unsupported
  schema files, two-manager/two-process contention, SQLite busy handling, and abrupt
  process termination.
- Test cancellation at every awaited boundary and verify bounded shutdown.
- Run sustained high-frequency mutation tests with a deliberately slow writer and
  assert bounded memory, bounded queue depth, preserved ordering, and event-loop
  latency targets.

## Next-Gen Evolution Path

### 1. Self-Evolving Tool Synthesis (Dynamic Tool Forging)

- **Concept**: Empower AI teams to dynamically generate, test, and register new Python tools at runtime when existing capabilities are insufficient.
- **Implementation Strategy**:
  - Introduce a `ToolLibrary` mechanism, mirroring the ACL structure of `DocLib`.
  - Equip a specialized `ToolMaker` agent with access to an isolated code sandbox.
  - Expose a `manager.forge_tool()` API, which securely compiles (`exec`) LLM-generated code strings into native Callables, attaching them to a designated `ToolLibrary` with READ/WRITE permission tracking.

### 2. Internal Monologue Scratchpad (Subconscious Reasoning)

- **Concept**: Provide agents with a private "scratchpad" to deliberate complex logic without polluting the shared team communication channels or prematurely revealing negotiation strategies.
- **Implementation Strategy**:
  - Introduce an XML-based `<scratchpad>` tag for agent reasoning.
  - The `ATTManager` will intercept and strip `<scratchpad>` content before broadcasting the thought to the public `dialog_history` buffer.
  - The extracted scratchpad content is routed exclusively to the individual agent's private context memory, allowing it to maintain an uninterrupted Chain-of-Thought across multiple discussion rounds.

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
