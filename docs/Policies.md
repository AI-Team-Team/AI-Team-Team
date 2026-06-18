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
- **When to Use**: For dynamic, self-organizing systems where communication channels must be justified and approved by supervisory AIs at runtime.

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
