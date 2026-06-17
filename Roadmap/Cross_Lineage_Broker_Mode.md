# Rule-Gated Cross-Lineage Communication Plan

This document details the architecture, design patterns, rule syntax, and implementation steps for fully supporting rule-gated cross-lineage communication channels in the `NegotiationBroker`.

## 1. Context & Gaps

Under the AI Team Team (ATT) framework, communication between two dynamic teams can either be:

* **Sibling Communication**: Sibling teams (sharing the same direct parent team) communicate under rules set by their common parent. Checked via `parent.communication_rules["allow_sibling_talk"]`.
* **Cross-Lineage Communication**: Teams belonging to different sub-branches in the hierarchy (different parent teams) must negotiate a communication tunnel.

Currently, `NegotiationBroker._run_parent_negotiation_loop` is stubbed out to automatically return `True` for all modes:

```python
async def _run_parent_negotiation_loop(self, p1: AgentTeam, p2: AgentTeam, mode: str) -> bool:
    if mode in {"proxied", "indirect", "rule_gated"}:
        return True
    return False
```

Furthermore, the `negotiate_peer_talk` tool in `src/ai_team_team/tool.py` does not accept a `mode` parameter, forcing all peer negotiations to default to `"proxied"` mode.

## 2. Design of Communication Modes

To resolve these limitations, we implement distinct, robust gating behaviors for the three supported negotiation modes:

```plaintext
                           [Cross-Lineage Peer Request]
                                        │
                         Resolve sender & recipient parents
                                        │
                     Determine Negotiation Mode ("proxied", "rule_gated", "indirect")
                                        │
             ┌──────────────────────────┼──────────────────────────┐
             ▼                          ▼                          ▼
      ["proxied"]                 ["rule_gated"]             ["indirect"]
             │                          │                          │
   Invoke Critic LLM            Evaluate static rules      Evaluate routing permissions
   Arbitration Debate           in parents' `rules` lists  or run fallback validation
             │                          │                          │
             └──────────────────────────┼──────────────────────────┘
                                        │
                               [Approve / Deny]
```

### 2.1 Rule-Gated Mode (`"rule_gated"`)

Decides communication permission statically by parsing configuration rules stored in the `communication_rules["rules"]` list of parent/ancestor teams.
For security and context protection, authorization must be **symmetric** (both parent lineages must explicitly authorize the connection).

#### Supported Rule Patterns

Parents can configure the following string rules in their `communication_rules["rules"]` list:

1. **`allow_all` / `allow_any`**: Unrestricted access. Permits communication with any peer team.
2. **`allow_team:<team_id>`**: Explicit team permission. Allows communication with the specific target team ID.
3. **`allow_parent:<parent_team_id>`**: Lineage permission. Allows communication with any team spawned under the specified parent team ID.
4. **`allow_purpose:<regex>`**: Dynamic semantic matching. Allows communication with any team whose `team_purpose` matches the specified regular expression (e.g. `allow_purpose:.*search.*`).

### 2.2 Proxied Mode (`"proxied"`)

Uses the system's `critic_client` to arbitrate communication requests dynamically. The Critic LLM acts as an architect to verify if opening a channel is beneficial and safe, evaluating:

* Sender and recipient team purposes.
* The explicit rationale provided in `negotiate_peer_talk`.

The Critic must return a JSON response matching:

```json
{
  "approved": true,
  "reason": "Arbitration reason detailing safety and utility check."
}
```

### 2.3 Indirect Mode (`"indirect"`)

Checks that the message can be safely routed through parent/intermediary nodes, enforcing strict hierarchy. If direct peer-to-peer is required, it falls back to a Critic verification step or a simplified rule check.

## 3. Implementation Plan

### 3.1 Expose `mode` in `negotiate_peer_talk`

Modify the `negotiate_peer_talk` tool signature and docstring in `src/ai_team_team/tool.py` to accept an optional `mode` string:

```python
async def negotiate_peer_talk(target_team_id: str, rationale: str, mode: str = "proxied") -> str:
    """Requests parents to negotiate a cross-lineage communication channel with a target team.
    Arguments: target_team_id (str), rationale (str), mode (str)
    """
    ...
    success = await att_manager.broker.establish_peer_agreement(actual_team, target, mode)
```

### 3.2 Update `NegotiationBroker`

1. Update `establish_peer_agreement` to pass the negotiation `mode` to the loop:

   ```python
   success = await self._run_parent_negotiation_loop(sender_parent, recipient_parent, mode, sender=sender, recipient=recipient, rationale=rationale)
   ```

2. Implement `_run_parent_negotiation_loop`:
   * Extract rule list from `p1` and `p2`.
   * Evaluate `rule_gated` logic: Check if `p1` authorizes `recipient` (by checking `p1`'s rules) and `p2` authorizes `sender` (by checking `p2`'s rules).
   * Evaluate `proxied` logic: Dispatch a structured arbitration request to `critic_client` (similar to migration arbitration).
   * Evaluate `indirect` logic: Allow or validate based on parent rules.

## 4. Verification Plan

### 4.1 Automated Tests

Add test cases in `test/test_att.py` to cover:

1. **Rule-Gated Success & Denial**: Verify `allow_all`, `allow_team`, `allow_parent`, and `allow_purpose` rules.
2. **Symmetric Check Verification**: Ensure that if only one parent team authorizes communication, the channel is denied.
3. **Critic Arbitration (Proxied Mode)**: Mock `critic_client` responses to verify successful tunnel creation and denial flows.
4. **Invalid Mode Exception handling**: Verify that unsupported modes return `False` safely.
