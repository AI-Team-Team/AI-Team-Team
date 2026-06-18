# ATT (AI-Team-Team) Framework Evolution Roadmap

This document outlines the design blueprints, architectural optimizations, and next-generation evolution paths for the **AI-Team-Team (ATT)** multi-agent orchestration framework.

## 🎯 Overview

The next iterations of the ATT framework focus on:

1. **Robustness & Security Gating**: Hardening parser resilience, isolating exceptions, and enforcing organizational migration limits.

## Next-Gen Evolution Path

### 1. The "Passive Inbox" Trap for Asynchronous Escalations

* **Context:** When the `SupervisoryTeam` detects a deadlock, it triggers `report_anomaly` and appends an escalation warning to the parent team's `message_inbox`.
* **Problem:** The `message_inbox` is only read and processed when `execute_team_discussion(parent)` is explicitly invoked. If the parent team is currently "idle" (not actively running a discussion loop), this critical hierarchy-collapse alert will be left pending indefinitely.
* **Action Item:** Introduce an event-trigger or listener mechanism. When the inbox receives high-priority alerts (such as `type: escalation_spawn` or `child_failure_escalation`), the framework should automatically "wake up" the parent team and force a rapid emergency discussion round to handle the anomaly.
