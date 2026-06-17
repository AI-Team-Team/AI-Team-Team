# ATT (AI-Team-Team) Framework Evolution Roadmap

This document outlines the design blueprints, architectural optimizations, and next-generation evolution paths for the **AI-Team-Team (ATT)** multi-agent orchestration framework.

## 🎯 Overview

The next iterations of the ATT framework focus on:

1. **Concurrency & RT Reduction**: Resolving synchronous ReAct blocking bottlenecks using async execution.
2. **Robustness & Security Gating**: Hardening parser resilience, isolating exceptions, and enforcing organizational migration limits.

## 1. Core Architectural Optimizations

### 1.1 Async/Await ReAct Loops (Concurrency)

* **Problem**: Currently, the discussion loop inside `execute_team_discussion` and `execute_react_step` is entirely synchronous and single-threaded. In multi-agent panels, this leads to $N \times R \times S$ (Members $\times$ Rounds $\times$ Steps) sequential blocking LLM requests, causing latency overheads of several minutes.
* **Solution**:
  * Transition all execution chains (`execute_team_discussion`, `execute_react_step`, and `generate` adapters) to native Python `asyncio` (`async def` and `await`).
  * Introduce parallel execution blocks where independent agents (such as initial analysts or validation nodes) run their ReAct loops concurrently, significantly reducing response times.

## 2. Next-Gen Evolution Path

### 2.1 Active Permission Gates in Tool Execution

* **Blue-sky Concept**: Ensure agents operate strictly within the communication bounds defined by their parent teams.
* **Design**:
  * Integrate a pre-execution verification hook in the Tool runner.
  * When an agent calls `send_peer_message` or `dispatch_subagent`, the executor calls `NegotiationBroker.negotiate_communication` beforehand.
  * If unauthorized, instead of raising an error, return a structured observation: `Observation: Error: Permission Denied. Sibling talk is not authorized. You must call set_sibling_talk to request access.` This trains agents to adapt dynamically to permission boundaries.
