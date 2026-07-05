# Team Governance, Policies & Protocols

This document details how the ATT (AI-Team-Team) framework governs inter-team communication, hierarchical restructuring, dynamic token budgeting, and preemptive emergency wakeups via configurable policy objects.

## 1. The Team Inbox & Communication Protocols

The ATT framework relies heavily on asynchronous event queues to decouple multi-agent systems and prevent blocking locks. Inter-team communication is entirely achieved through the **Inbox Queue** and the **NegotiationBroker**.

Every `AgentTeam` maintains an internal `message_inbox (List[Dict])`. This acts as a mailbox for incoming payloads. Messages are never forced directly into an agent's memory window mid-thought, preventing catastrophic ReAct logic interruptions.

Instead, the `manager.execute_team_discussion()` cycle polls the inbox at the very beginning of a debate round. If messages exist, the manager compiles them into a unified alert and appends them to the team's system prompt context.

### Inbox Overflows & Summarization

To prevent prompt length limits, the inbox utilizes `inbox_summarize_threshold_chars`. If unread messages exceed this threshold during polling, the `ATTManager` utilizes its `critic_client` to automatically compress the raw payloads into a dense, bulleted summary before injecting it into the debate.

## 2. Peer-to-Peer Communication & Negotiation Broker

Dynamic sub-teams often need to collaborate across lineage boundaries. Calling `send_peer_message(team_id, message)` routes the payload to the target team's inbox. However, all cross-team communication is gated by the **NegotiationBroker**, ensuring isolated execution chains cannot maliciously interact without parent authorization.

### Sibling Routing (Common Parents)

If `Team_A` messages `Team_B` and they share the exact same `parent_team`, the Broker routes the check upwards to the shared parent. It evaluates the parent's `allow_sibling_talk` rule.

### Cross-Lineage Negotiation

If `Team_A` messages `Team_C` located in an entirely different subtree, the Broker checks the SQLite-backed `peer_talk_agreements` registry. If no bidirectional tunnel exists, `Team_A` must explicitly call `negotiate_peer_talk()`, triggering the parent representatives to utilize the configured Communication Policy to negotiate an agreement.

## 3. Inter-Team Communication Policies

The specific strategy the Negotiation Broker uses to approve or deny requests is configured via `communication_policy` in `ATTConfig`:

### A. Permissive Policy (`"permissive"`)

- **Behavior**: Freely permits any team to message or establish tunnels with any other team.

### B. Rule-Gated Policy (`"rule_gated"`)

- **Behavior**: Evaluates communication rules defined inside the parent teams of the sender and recipient. Both directions must satisfy the rules.
- **Rule Syntax**:
  Parent teams can define specific strings under `team.communication_rules["rules"]` (e.g., `allow_all`, `allow_team:<team_id>`, `allow_parent:<parent_id>`, `allow_purpose:<regex>`).

### C. Proxied Policy (`"proxied"`)

- **Behavior**: Instead of static rules, the parent team leaders of both the sender and recipient are consulted dynamically. The representatives evaluate the request details and rationale via their own **LLM client** and return a JSON approval (`{"approved": true|false, "reason": "..."}`).

### D. Guided Observation Feedback

When a communication attempt is blocked by a non-permissive policy, instead of raising a terminal error, the tool returns a structured observation guiding the caller agent on how to correctly request authorization (e.g. instructing them to call `negotiate_peer_talk()`).

## 4. Migration & Reorganization Policies

Dynamic parent-hierarchy migrations are triggered when a team requests to move under a new parent (e.g., `negotiate_and_execute_migration()`). The strategy is resolved from `migration_policy`:

### A. Permissive Policy (`"permissive"`)

- **Behavior**: Restructures the hierarchy immediately without requesting approvals or running audits.

### B. Ancestor Approval Policy (`"ancestor_approval"`) - *Default*

- **Behavior**: Requests evaluations and approvals from the current parent, the target parent, and the Least Common Ancestor (LCA) representative. If any reject the restructure, the migration fails.

### C. Lineage Path Policy (`"lineage_path"`)

- **Behavior**: Similar to `ancestor_approval`, but queries **every team representative** along the traversal path from the current parent up to the LCA, and from the target parent up to the LCA.

## 5. Token Budget & Failover Policies

To ensure stability in high-overhead multi-agent environments, the framework provides token budgeting circuit breakers and dynamic model failover strategies.

### A. Failover Routing Strategies

When an agent's client hits a token limit, it resolves via `failover_policy`:

1. **Auto-Fallback (`"auto"`)**: Automatically hot-swaps to the first alternative registered model that is under budget and supports the required tool calling mode.
2. **Parent-Representative Delegation (`"parent"`)**: The child team synchronously queries the parent team's representative LLM for a model recommendation, hot-swaps the client, and retries.

## 6. Code Configuration Example

To configure the communication and migration policies, define them during the `ATTConfig` initialization:

```python
from ai_team_team import ATTManager, Agent, ATTConfig

# 1. Configure the policies
config = ATTConfig(
    communication_policy="rule_gated",
    migration_policy="lineage_path",
    failover_policy="parent",
    model_token_limits={"gpt-5.5": 50000}
)

# 2. Instantiate the manager
root_agent = Agent(name="Root_AI", role="Architect")
manager = ATTManager(root_ai=root_agent, config=config)

# 3. Define rule constraints on a parent team
parent_team = manager.create_agent_team(creator=root_agent, preset_name="generic")
parent_team.communication_rules["rules"] = ["allow_purpose:.*analyst.*"]
```

## 7. Emergency Wakeup Protocol

The ATT framework implements a preemptive event-driven "Emergency Wakeup" system. This ensures that critical child failures or supervisory anomalies can instantly interrupt an idle parent team, forcing them to resolve the issue before continuing standard operations.

### A. The Trigger Condition

Emergency Wakeups are triggered when a team's asynchronous `receive_message` method ingests a payload with a type of either:

- `"child_failure_escalation"`
- `"escalation_spawn"`

If the global configuration flag `enable_emergency_wakeup` is set to `True`, the system evaluates the target team's execution state:

1. **If the team is currently in a discussion loop (`is_running == True`)**: The alert simply waits in the `message_inbox`. The manager will automatically parse it during the next ReAct cycle.
2. **If the team is idle (`is_running == False`)**: The system initiates an immediate preemptive `asyncio` context switch to wake the team up by scanning the inbox post-discussion:

   ```python
   emergency_msg = next((msg for msg in team.message_inbox if msg.get("type") in {"child_failure_escalation", "escalation_spawn"}), None)
   ```

### B. Event-Loop Execution vs Deferred Queuing

Waking up a team requires triggering `manager.execute_emergency_discussion()`, which is an `async` coroutine. Because ATT supports both strict asynchronous runtime environments (like FastAPI) and synchronous blocking scripts, the protocol handles both gracefully:

- **Active Event Loop (`asyncio.create_task`)**: If an event loop is currently active in the thread, the manager schedules the wakeup immediately:

  ```python
  asyncio.create_task(self.execute_emergency_discussion(team, emergency_msg))
  ```

- **Blocked/Missing Event Loop (`deferred_emergency_tasks`)**: If the event loop is blocked (e.g., executing a synchronous SQLite serialization) or not running, scheduling a task will throw a `RuntimeError`. The manager safely traps this and defers the coroutine into an `asyncio.Queue`:

  ```python
  except RuntimeError as e:
      self.deferred_emergency_tasks.put_nowait(
          self.execute_emergency_discussion(team, emergency_msg)
      )
  ```

  The manager guarantees these deferred tasks will be flushed and executed sequentially the next time a safe boundary is reached via `manager.flush_deferred_tasks()`.

### C. The Emergency Discussion Round

When the wakeup executes, it bypasses standard ReAct scheduling and initiates a dedicated, high-priority debate round defined by `emergency_discussion_rounds` (default: 1).

The agents are injected with a system override prompt detailing the anomaly:

```text
EMERGENCY MEETING: An anomaly or escalation was reported from your child team or supervisor.
Alert details: {alert_reason}
Please evaluate this issue and decide on corrective actions or escalate further.
```

If the team fails to resolve the emergency, the 3-AI Supervisory Team will catch the deadlock during the post-discussion audit and cascade the emergency alert one level higher up the lineage tree, eventually escalating to the `Root_AI` if the entire tree collapses.
