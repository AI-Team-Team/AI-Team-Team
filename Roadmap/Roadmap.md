# ATT (AI-Team-Team) Framework Evolution Roadmap

This document outlines the design blueprints, architectural optimizations, and next-generation evolution paths for the **AI-Team-Team (ATT)** multi-agent orchestration framework.

## 🎯 Overview

The next iterations of the ATT framework focus on:

1. **Robustness & Security Gating**: Hardening parser resilience, isolating exceptions, and enforcing organizational migration limits.

## 1. Next-Gen Evolution Path

### 1.1 Active Permission Gates in Tool Execution

* **Blue-sky Concept**: Ensure agents operate strictly within the communication bounds defined by their parent teams.
* **Design**:
  * Integrate a pre-execution verification hook in the Tool runner.
  * When an agent calls `send_peer_message` or `dispatch_subagent`, the executor calls `NegotiationBroker.negotiate_communication` beforehand.
  * If unauthorized, instead of raising an error, return a structured observation: `Observation: Error: Permission Denied. Sibling talk is not authorized. You must call set_sibling_talk to request access.` This trains agents to adapt dynamically to permission boundaries.

### 1.2 Rule-Gated Cross-Lineage Communication (Cross-Lineage Broker Mode)

* **Concept**: Fully support rule-gated cross-lineage communication channels in the `NegotiationBroker`.
* **Design**:
  * Extend `negotiate_peer_talk` tool to accept a `mode` parameter.
  * Implement symmetric rule evaluation (e.g. `allow_all`, `allow_team`, `allow_parent`, `allow_purpose`) and Critic-based dynamic arbitration.
  * For full architectural details, see the detailed design document: [Cross-Lineage Broker Mode Design Plan](Cross_Lineage_Broker_Mode.md).
