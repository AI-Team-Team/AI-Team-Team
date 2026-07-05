# 3-AI Supervisory Team Specification

This document details the operational behavior, decision rules, and recursive escalation logic of the **3-AI Supervisory Team** under the ATT framework.

## 1. Design Paradigm: The 3-AI Committee

To avoid circular deadlocks and logical slips within dynamic team debates, every active Agent Team (AT) is audited by a non-participating **Supervisory Team**. The Supervisory Team is composed of exactly 3 specialized AI auditors:

1. **Auditor_Integrity_01** (`Integrity_Auditor`): Verifies database alignment and strict rule adherence.
2. **Auditor_Continuity_02** (`Continuity_Auditor`): Monitors logical timeline and event consistency.
3. **Auditor_Deadlock_03** (`Deadlock_Auditor`): Tracks dialogue progression, repetitive statements, and deadlock scenarios.

The Supervisory Team is entirely non-participating; it does not contribute content, but audits the multi-agent discussion transcript at the end of each discussion round.

For a detailed control flow of dialogue auditing, see the [3-AI Dialogue Auditing Logic Flowchart](flowcharts/Supervisory_Team_Audit.md#1-3-ai-dialogue-auditing-logic-flowchart).

## 2. Dialogue Health Auditing (The 3-AI Audit Committee Debate)

At the end of a team discussion, the Supervisory Team performs a batch audit of the transcript. Instead of a single direct evaluation call, the Supervisory Team initiates a **non-recursive 2-round debate session** among its 3 specialized auditors.

### Dialogue Auditing Committee Flow

1. **Context Compression**: If the target dialogue transcript is extremely long (exceeding 8,000 characters), it is summarized using a fast LLM context-compression prompt to minimize token window overhead while preserving core reasoning continuity and deadlock indicators.
2. **Transient Committee AT**: The manager creates a transient `AgentTeam` with the 3 auditor agents as members. This team is temporary, stateless, and is not registered in the manager's active topology tree.
3. **Audit Committee Debate & Memory Isolation**: The auditors debate the health of the target transcript for exactly 2 rounds. This debate runs with `skip_audit=True` to break the recursion loop at depth 1. Architecturally, all supervisory agents perform a mandatory `messages.clear()` operation immediately prior to injecting the audit prompt. This hard memory boundary ensures that infinite, long-running server sessions never leak memory or breach token limits.
4. **Consensus Synthesis**: The debate transcript is passed to a consensus synthesis prompt that extracts their combined consensus.

### Audit Output Format

The Supervisory Team produces a strict JSON health evaluation:

```json
{
  "is_healthy": true | false,
  "reason": "Detail reasoning regarding communication efficiency and continuity..."
}
```

### Graceful Fallback & Fault Tolerance

To ensure that transient LLM client API failures or JSON parsing errors do not halt active team discussions, the auditing mechanism implements a graceful fallback:

* **Default to Healthy**: If any exception or generation failure occurs during the dialogue audit, the Supervisory Team automatically defaults to `is_healthy = True` and logs a warning with the error details.
* **Error Traceability**: The audit reason is set to `"Audit failed: <error message>"` to preserve traceability in logs.

## 3. Asynchronous Parent Escalation Channel

If the dialogue audit results in `is_healthy = False` (indicating a deadlock or severe logic violation), the Supervisory Team triggers the **Asynchronous Escalation Protocol**:

```plaintext
                   ┌───────────────────────────────┐
                   │    Failed Child Team (AT)     │
                   └───────────────┬───────────────┘
                                   │ (Supervisory Audit Fails)
                                   ▼
                   ┌───────────────────────────────┐
                   │ Dispatch Alert to Direct      │
                   │ Parent's Message Inbox        │
                   └───────────────┬───────────────┘
                                   │
                                   ▼
                   ┌───────────────────────────────┐
                   │ Audit Parent Team (AT)        │
                   │ wakes up or consumes alert    │
                   │ on next round                 │
                   └───────────────────────────────┘
```

 1. **Direct Escalation**: The Supervisor resolves the direct parent team of the failed team.
 2. **Asynchronous Routing**: The Supervisor dispatches a failure alert (containing the anomaly reason and child team ID) directly into the parent team's `message_inbox`. It returns immediately, preventing synchronous blocking loops that cause API timeouts.
 3. **Context Consumption & Active Wake-up**: If the parent team is idle, this emergency alert automatically wakes up the parent team for a rapid emergency discussion session. If the parent team is already active, it will consume the alert at the start of the next round. If the cascade of errors exceeds the `inbox_summarize_threshold_chars` threshold, it will automatically summarize the inbox context.
 4. **Fallback Gating**: If no parent exists in the lineage tree, the Supervisor escalates a critical system alert directly to the **Level 0 Root AI**.

> [!NOTE]
> Anomaly escalations dynamically follow the current parent-child lineage tree links, even if the failed team has migrated to a different parent branch during discussion rounds.

For the visual flow of how failures cascade up the lineage tree, see the [Parent-Ancestor Escalation Tree Flowchart](flowcharts/Supervisory_Team_Audit.md#2-parent-ancestor-escalation-tree-flowchart).

## 4. Configuration & Usage

The auditing and escalation behaviors are completely automated when the autonomy suite is active. Anomaly transcripts and escalations are logged dynamically to track overall lineage health.
