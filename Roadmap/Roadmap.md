# ATT (AI-Team-Team) Framework Evolution Roadmap

This document outlines the design blueprints, architectural optimizations, and next-generation evolution paths for the **AI-Team-Team (ATT)** multi-agent orchestration framework.

## 🎯 Overview

The next iterations of the ATT framework focus on:

1. **Robustness & Security Gating**: Hardening parser resilience, isolating exceptions, and enforcing organizational migration limits.

## Next-Gen Evolution Path

### 1. Active Permission Gates in Tool Execution

* **Blue-sky Concept**: Ensure agents operate strictly within the communication bounds defined by their parent teams.
* **Design**:
  * Integrate a pre-execution verification hook in the Tool runner.
  * When an agent calls `send_peer_message` or `dispatch_subagent`, the executor calls `NegotiationBroker.negotiate_communication` beforehand.
  * If unauthorized, instead of raising an error, return a structured observation: `Observation: Error: Permission Denied. Sibling talk is not authorized. You must call set_sibling_talk to request access.` This trains agents to adapt dynamically to permission boundaries.

### 2. Rule-Gated Cross-Lineage Communication (Cross-Lineage Broker Mode)

* **Concept**: Fully support rule-gated cross-lineage communication channels in the `NegotiationBroker`.
* **Design**:
  * Extend `negotiate_peer_talk` tool to accept a `mode` parameter.
  * Implement symmetric rule evaluation (e.g. `allow_all`, `allow_team`, `allow_parent`, `allow_purpose`) and Critic-based dynamic arbitration.
  * For full architectural details, see the detailed design document: [Cross-Lineage Broker Mode Design Plan](Cross_Lineage_Broker_Mode.md).

### 3. State Persistence and Workflow Recovery (State Snapshotting) [COMPLETED]

* **Context:** Previously, all team structures, memory queues, inboxes, and historical proposals were strictly stored in memory and lost on crash.
* **Solution:** Implemented SQLite-backed database persistence via `manager.save_state()` and `manager.load_state()`. The framework serializes the active topology tree, parent-child lineages, agent message queues (multi-turn histories), and Document Library directories/files seamlessly. Auto-save triggers automatically on all state modifications (debates, tool calls, migrations).

### 4. The "Passive Inbox" Trap for Asynchronous Escalations

* **Context:** When the `SupervisoryTeam` detects a deadlock, it triggers `report_anomaly` and appends an escalation warning to the parent team's `message_inbox`.
* **Problem:** The `message_inbox` is only read and processed when `execute_team_discussion(parent)` is explicitly invoked. If the parent team is currently "idle" (not actively running a discussion loop), this critical hierarchy-collapse alert will be left pending indefinitely.
* **Action Item:** Introduce an event-trigger or listener mechanism. When the inbox receives high-priority alerts (such as `type: escalation_spawn` or `child_failure_escalation`), the framework should automatically "wake up" the parent team and force a rapid emergency discussion round to handle the anomaly.
