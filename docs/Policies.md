# Policy-Based Governance & Decoupled Rules

This document details the policy-based governance mechanism of the ATT (AI-Team-Team) framework. This architecture decouples inter-team communication tunnels and dynamic topology migrations from hardcoded execution layers into configurable, strategy-pattern policy components.

## 1. Overview

In hierarchical agent groups, regulating how teams interact (communication) and change positions (migration/restructure) is crucial for governance. The ATT framework provides a policy-driven configuration model using the `communication_policy` and `migration_policy` settings in `ATTConfig`.

```plaintext
                    ┌────────────────────────────────┐
                    │           ATTConfig            │
                    │   - communication_policy       │
                    │   - migration_policy           │
                    └───────────────┬────────────────┘
                                    │ Resolves strategies
                                    ▼
       ┌────────────────────────────┴────────────────────────────┐
       ▼                                                         ▼
┌──────────────────────────────┐                          ┌──────────────────────────────┐
│  BaseCommunicationPolicy     │                          │     BaseMigrationPolicy      │
├──────────────────────────────┤                          ├──────────────────────────────┤
│ - Permissive                 │                          │ - Permissive                 │
│ - RuleGated                  │                          │ - AncestorApproval (Default) │
│ - Proxied                    │                          │ - LineagePath                │
└──────────────────────────────┘                          └──────────────────────────────┘
```

## 2. Inter-Team Communication Policies

Inter-team communication is triggered when an agent in one team attempts to establish a tunnel or message another team (e.g., using `establish_peer_agreement()`). The allowed strategy is resolved from `communication_policy`:

### A. Permissive Policy (`"permissive"`)

- **Behavior**: Freely permits any team to message or establish tunnels with any other team.
- **When to Use**: Ideal for cooperative workspaces where agents do not require privacy or audit checks.

### B. Rule-Gated Policy (`"rule_gated"`)

- **Behavior**: Evaluates communication rules defined inside the parent teams of the sender and recipient. Both directions must satisfy the rules.
- **Rule Syntax**:
  Parent teams can define specific strings under `team.communication_rules["rules"]`:
  - `allow_all` or `allow_any`: Grants access to all opposing teams.
  - `allow_team:<team_id>`: Restricts access to a specific team ID.
  - `allow_parent:<parent_team_id>`: Restricts access to teams spawned under a specific parent team.
  - `allow_purpose:<regex>`: Matches the opposing team's purpose against a regular expression pattern.
- **When to Use**: Best for static, policy-constrained enterprise structures (e.g., restricting marketing AIs from contacting financial databases unless explicitly configured).

### C. Proxied Policy (`"proxied"`)

- **Behavior**: Instead of static rules, the parent team leaders of both the sender and recipient are consulted dynamically. The representatives evaluate the request details and rationale via their own **LLM client** and return a JSON approval (`{"approved": true|false, "reason": "..."}`).
  - *Note*: If either team is a Level 1 team (direct descendant of the Root AI with no parent `AgentTeam`), the `Root_AI` is treated as its parent representative and queried for approval.
- **When to Use**: For dynamic, self-organizing systems where communication channels must be justified and approved by supervisory AIs at runtime.

### D. Guided Observation Feedback

When a communication attempt via `send_peer_message` is blocked by a non-permissive communication policy (such as `proxied` or `rule_gated`), instead of raising an execution error, the tool returns a structured observation guiding the caller agent on how to request authorization:

- **Sibling Block** (if sender parent matches target parent):
  `"Error: Permission Denied. Sibling talk is not authorized. You must call set_sibling_talk(child_id='<target_team_id>', allow=True) via your parent to request access."`
- **Cross-Lineage Block** (if sender parent does not match target parent):
  `"Error: Permission Denied. Cross-lineage agreement does not exist. You must call negotiate_peer_talk(target_team_id='<target_team_id>', rationale='...') first to establish a tunnel."`

This mechanism actively trains agents to dynamically adjust and call the correct permissions-resolution tools when encountering policy gates.

## 3. Migration & Reorganization Policies

Dynamic parent-hierarchy migrations are triggered when a team requests to move under a new parent (e.g., `negotiate_and_execute_migration()`). The strategy is resolved from `migration_policy`:

### A. Permissive Policy (`"permissive"`)

- **Behavior**: Restructures the hierarchy immediately without requesting approvals or running audits.
- **When to Use**: Lightweight debug sessions or simple flat topologies.

### B. Ancestor Approval Policy (`"ancestor_approval"`) - *Default*

- **Behavior**: Requests evaluations and approvals from:
  1. The representative of the team's current parent.
  2. The representative of the proposed target parent.
  3. The Least Common Ancestor (LCA) team representative in the ancestry lineage.
  - *Note*: If any of these parent levels resolves to `None` (representing the root coordination layer), the `Root_AI` represents that layer in the arbitration.
- **Arbitration**: If any representative rejects the restructure via their LLM client, the migration fails and an alert is logged.
- **When to Use**: Standard enterprise hierarchies where changes require consent from both parent domains and their common supervisor.

### C. Lineage Path Policy (`"lineage_path"`)

- **Behavior**: Similar to `ancestor_approval`, but queries **every team representative** along the traversal path from the current parent up to the LCA, and from the target parent up to the LCA.
- **When to Use**: High-security topologies where passing through any intermediate team's boundary requires explicit approval from every node in the chain.

## 4. Code Example

To configure the communication and migration policies, define them during the `ATTConfig` initialization:

```python
from ai_team_team import ATTManager, Agent, ATTConfig

# 1. Configure the policies
config = ATTConfig(
    # Set inter-team communication to rule-gated
    communication_policy="rule_gated",
    
    # Set parent migration to lineage-path-approval
    migration_policy="lineage_path"
)

# 2. Instantiate the manager
root_agent = Agent(name="Root_AI", role="Architect")
manager = ATTManager(root_ai=root_agent, config=config)

# 3. Define rule constraints on a parent team
parent_team = manager.create_agent_team(
    creator=root_agent,
    preset_name="generic",
    team_purpose="Research Domain"
)

# Allow sibling teams under this parent to communicate with teams having 'analyst' in their purpose
parent_team.communication_rules["rules"] = [
    "allow_purpose:.*analyst.*"
]
```

## 4. Token Budget & Failover Policies

To ensure stability in long-running or high-overhead multi-agent environments, the ATT framework provides token budgeting circuit breakers and dynamic model failover strategies.

### A. Token Budget Configuration

Budgets are tracked at a session level in `ATTManager` and configured in `ATTConfig`:

- `model_token_limits`: Dictionary mapping model registry aliases (e.g., `"default"`, `"gpt-5.5"`, `"claude-4.8"`) to their session token budget limits.
- `model_tokenizer_configs`: Dictionary mapping model registry aliases to local tokenizer path names or HF hub repository strings to count prompt/response tokens using Hugging Face `tokenizers`.
  - *Note*: If the tokenizer fails to load or runs offline, the system safely falls back to a character count BPE estimation (`len(text) // 4`) to prevent crash lockups.

Before any API request is sent, a **pre-flight** token check calculates prompt tokens and raises `TokenLimitExceededError` if the budget is exhausted. After a successful API resolution, a **post-flight** token count updates the model's session usage.

### B. Failover Routing Strategies

When an agent's client hits a token limit, the framework catches the exception and resolves it via `failover_policy` in `ATTConfig`:

1. **Auto-Fallback (`"auto"`)**
   - **Behavior**: Automatically scans registered model clients, identifies the first alternative model that is under budget and supports the required tool calling mode, hot-swaps the agent's client, and retries the turn.
2. **Parent-Representative Delegation (`"parent"`)**
   - **Behavior**: To prevent deadlocks (which would occur if a child team suspended and waited for a blocked parent team's next round), the child team **synchronously queries the parent team's representative LLM** (e.g., its creator or leader) for a recommendation, parses the JSON response (`{"selected_model": "name"}`), hot-swaps the client, and retries.
   - *Note*: If no parent team is resolved, it automatically falls back to `"auto"`.

### C. System Callback Notification (`on_system_event`)

When a failover or budget limit event occurs, the manager triggers a callback allowing host projects to receive structured JSON notifications to log alerts (e.g., via Slack or emails):

```python
def my_system_event_handler(event_type: str, details: dict):
    print(f"System Alert [{event_type}]: {details}")

manager.on_system_event = my_system_event_handler
```

### D. Code Example

```python
from ai_team_team import ATTManager, Agent, ATTConfig

# 1. Define limits, tokenizers and policy
config = ATTConfig(
    model_token_limits={
        "default": 10000,
        "gpt-5.5": 50000,
        "gemini-3.5": 100000
    },
    model_tokenizer_configs={
        "default": "gpt2",
        "gpt-5.5": "cl100k_base"
    },
    failover_policy="parent"  # Query parent for failover model decisions
)

# 2. Instantiate and run
root_agent = Agent(name="Root_AI", role="Architect")
manager = ATTManager(root_ai=root_agent, config=config)
```
