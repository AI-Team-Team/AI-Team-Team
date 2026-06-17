# AI-Team-Team (ATT)

A lightweight, generic, hierarchical dynamic multi-agent collaboration framework in Python.

Instead of treating AI as isolated chatbots, ATT treats them as members of a living organization.

AI can freely form teams, define how they discuss things with each other, how AI teams discuss things, and create all sorts of incredibly complex hierarchical (or dynamic) relationships.

Hundreds, thousands, even tens of thousands of AIs work together in an orderly manner.

<details>
<summary>More</summary>
ATT empowers AI agents to transition from passive context consumers to active, self-governing groups. It organizes agents into dynamic, tree-like recursive lineages with built-in consensus debates, ReAct reasoning loops, communication permission gating, size-aware file context protection, and supervisory health auditing.
</details>

Many thanks to Gemini and GPT for their help!

> [!NOTE]
> The project already features a lot of really fun and innovative designs, with an even more groundbreaking architecture in the works. \
> (It’s still a little rough around the edges though 👀)

> [!TIP]
> If you notice any issues or have any suggestions and have the time, \
> please leave them in the Issues section. Thank you.

[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue.svg)](#)
[![License](https://img.shields.io/badge/license-Apache%202.0-green.svg)](LICENSE.txt)
[![Documentation](https://img.shields.io/badge/docs-specification-orange.svg)](docs/README.md)
[![Unit Tests](https://img.shields.io/badge/tests-passing-brightgreen.svg)](#)

## 🚀 Key Features

* **[Tree-like Lineage Spawning](docs/Dynamic_Delegation.md)**: Spawns hierarchical dynamic agent teams (`AgentTeam`) recursively to arbitrary depths, strictly governed by depth limits.
* **[Autonomous Member Configurations](docs/Dynamic_Delegation.md#1-dynamic-spawning-&-lineage-hierarchy)**: Defines dynamic child team memberships using structured `member_configs` mapping custom roles, individual system instructions, and model aliases to shape custom agent behaviors.
* **[Democratic Voting & Governance](docs/Dynamic_Delegation.md#5-team-governance-&-democratic-voting-system)**: Introduces an optional asynchronous voting system to democratically manage team memberships. Voting requires unanimous active member participation and a $\ge 2/3$ agreement threshold to auto-execute.
* **Dynamic presets & Committees**: Allows runtime registration of custom agent committees (role configurations and system prompts) like planning, writing, database management, etc.
* **[Model Registry & Global Generator Callback](docs/user/Quickstart.md#7-model-registry-and-global-generator-callback)**: Maps dynamic agent roles to registered model configurations (containing metadata and descriptions), delegating all LLM invocation logic to a centralized global callback handler to keep the library keyless and lightweight.
* **Bounded ReAct Loops**: Agents execute reasoning steps using standard ReAct (Thought/Action/Observation) protocols, supported by a safe literal argument parser.
* **[Negotiation Broker](docs/Dynamic_Delegation.md#4-consolidated-autonomy-tools)**: Gates sibling and cross-lineage peer-to-peer communication through dynamic permission rules and broker contracts.
* **[Dynamic Lineage Migration](docs/Dynamic_Delegation.md)**: Allows active teams to dynamically request parent-hierarchy migrations, arbitrated by the System Critic with cycle checks and related team alerts.
* **[Hierarchical Topology Map](docs/Dynamic_Delegation.md)**: Injects a structured ASCII indented tree map representing all active teams (displaying team purposes and progress in real-time) in the agent context.
* **Tool Auditor Interception Hook**: Allows host applications to register pre-execution callback hooks to audit, approve, or reject specific tool calls (e.g. database safety query vetting).
* **[Supervisory Dialogue Audits](docs/Supervisory_Team.md)**: A 3-AI Supervisory Team audits dialogue transcripts for logical deadlocks, circular reasoning, and anomalies, recursively escalating alerts up the ancestry lineage.
* **UI/Logging Decoupling**: Exposes clear runtime event hooks (`on_status_change`, `on_activity_added`, `on_log_append`) to update terminal dashboards and write logs without framework pollution.
* **[Gated Context Protection](docs/Gated_Reading.md)**: Employs `GatedFileReader` to paginate file reading, cap line window requests, and fallback to outline warnings on large documents.
* **[Collaborative Document Library (DocLib)](docs/Gated_Reading.md#5-document-libraries-doclib)**: Equips each Agent Team with a built-in document library to manage nested directories/files, with fine-grained team-level permissions (READ/WRITE), discoverability listing, and dynamic parent-to-child context passing.

## 📦 Installation

To install in editable mode for local developer workspace sync, it is recommended to set up a virtual environment:

```bash
# Clone the repository
git clone https://github.com/AI-Team-Team/AI-Team-Team.git
cd AI-Team-Team

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install in editable/dev mode (quotes are required in zsh/macOS)
pip install -e ".[dev]"
```

To install directly as a Git dependency in your own project:

```bash
pip install git+https://github.com/AI-Team-Team/AI-Team-Team.git@main
```

## 🏛️ System Architecture

The master `ATTManager` coordinates the lifecycle, communications, and supervision of dynamic agent teams:

```mermaid
graph TD
    %% Lineage Spawning
    Root[Root Agent - Level 0] -->|create_agent_team| TeamA[Agent Team A - Level 1]
    Root -->|create_agent_team| TeamB[Agent Team B - Level 1]
    
    subgraph Lineage ["Hierarchical Team Lineage (Arbitrary Depth)"]
        TeamA -->|dispatch_subagent\nmember_configs| SubTeamA1[Sub-Agent Team A.1 - Level 2]
        SubTeamA1 -->|dispatch_subagent| SubTeamN[Sub-Agent Team N - Level N]
    end

    %% Document Library
    TeamA --- DocLibA[(DocLib A)]
    SubTeamA1 --- DocLibA1[(DocLib A.1)]
    SubTeamN --- DocLibN[(DocLib N)]
    TeamB --- DocLibB[(DocLib B)]
    
    DocLibA1 -.->|Request access / Grant READ| DocLibB

    %% Communication Permission Gating
    SubTeamN -.->|negotiate_communication| TeamB
    Broker[NegotiationBroker] -->|Evaluate Sibling Rules & Lineage Contracts| SubTeamN
    Broker -.->|Approve / Deny Tunnel| TeamB

    %% Supervisory Dialogue Audits & Escalation
    Supervisor[3-AI SupervisoryTeam] -->|audit_team_dialog| TeamA
    Supervisor -->|report_anomaly escalation| Root

    %% Democratic Voting System
    SubTeamA1 -->|initiate_membership_vote| Voting{Democratic Voting\nThreshold: >= 2/3}
    Voting -->|Approved: add/remove| SubTeamA1
    
    %% Styles
    style Root fill:#d4e1f5,stroke:#3b5998,stroke-width:2px;
    style TeamA fill:#e1f5fe,stroke:#0288d1,stroke-width:2px;
    style TeamB fill:#e1f5fe,stroke:#0288d1,stroke-width:2px;
    style SubTeamA1 fill:#ede7f6,stroke:#5e35b1,stroke-width:2px;
    style SubTeamN fill:#f3e5f5,stroke:#ab47bc,stroke-width:2px;
    style Supervisor fill:#ffe0b2,stroke:#f57c00,stroke-width:2px;
    style Voting fill:#ffebee,stroke:#e53935,stroke-width:2px;
    style DocLibA fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px;
    style DocLibA1 fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px;
    style DocLibN fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px;
    style DocLibB fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px;
```

## 🛠️ Getting Started

### 1. Initialize Configuration & Manager

```python
from ai_team_team import ATTManager, Agent, ATTConfig, GatedFileReader

# 1. Configure the framework
config = ATTConfig(
    enable_dynamic_delegation=True,
    max_delegation_depth=2,
    min_subagent_team_size=3,
    subagent_discussion_rounds=2,
    react_max_steps=5
)

# 2. Setup Root Agent (client is dynamically resolved if omitted)
root_agent = Agent(name="Root_AI", role="Architect")

# 3. Create Manager (critic client is optional, falls back to handler callback if None)
manager = ATTManager(root_ai=root_agent, config=config)

# 4. Register a global generator callback handler
# All LLM invocation logic is delegated here, keeping the framework keyless and SDK-independent
async def my_handler(
    model_name: str,
    prompt: str,
    system_instruction: Optional[str] = None,
    temperature: float = 0.3,
    require_json: bool = False
) -> str:
    # 1. Inspect model_name to call the correct provider/SDK
    # 2. If require_json=True is requested, return valid JSON string
    return "Final Answer: Processed successfully."

manager.register_generator_handler(my_handler)
```

#### 🔌 LLM Client Interface (`LLMClientProto`)

To integrate custom LLM backends (e.g., Google GenAI, OpenAI, Anthropic, or local inference engines), the supplied client must conform to the following signature:

```python
from typing import Optional, Protocol

class LLMClientProto(Protocol):
    async def generate(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        require_json: bool = False,
        temperature: float = 0.0,
        **kwargs
    ) -> str:
        """
        Generates a text completion.
        When require_json=True is requested by SupervisoryTeam consensus audits,
        the model must return a valid, parsable JSON string.
        """
        ...
```

### 2. Register Presets & Custom Tools

Presets and custom tools are registered dynamically at runtime to keep the package generic:

```python
# Register custom presets
manager.register_preset(
    name="analysts",
    description="Refines requirements and specs",
    system_instructions="Deconstruct tasks into clear constraints.",
    roles=[
        ("Integrity_Analyst", "Checks logic compliance"),
        ("Structural_Planner", "Optimizes flow and layouts"),
        ("Arbitrator", "Synthesizes final answer")
    ]
)

# Register custom tools
def query_db(sql_command: str):
    # App database retrieval logic here
    return "Query result..."

# IMPORTANT: Always specify parameter names and types in the description
# so that ReAct agents can parse and supply arguments correctly!
manager.register_tool(
    name="query_db",
    description="Run safe SQL commands directly on the DB. Arguments: sql_command (str)",
    func=query_db
)
```

#### 💡 Tool Argument Convention & Parameter Discovery

ReAct agents learn about available tools by inspecting the registered `description`. To ensure agents pass arguments correctly:

1. Include explicit argument name and type guidelines in the description string (e.g., `Arguments: query_text (str), limit (int)`).
2. The framework parses ReAct actions using `ast.literal_eval`. Agents can output actions using standard Python argument syntax:
   * `Action: query_db(sql_command="SELECT * FROM characters")`
   * `Action: search_faiss("Iris character profile", limit=3)`

#### 🔗 Sibling Talk & Lineage Communication

Dynamic teams support horizontal peer messaging and vertical escalations via framework-supplied tools:

* **Sibling Gating**: By default, sibling teams (teams spawned by the same parent) cannot communicate. Parent teams can dynamically enable sibling talk:

  ```python
  # Programmatically set allow_sibling_talk on child team
  child_team.communication_rules["allow_sibling_talk"] = True
  ```

  Or parent agents can run:
  `Action: set_sibling_talk(child_id="AT-abc123", allow=True)`
* **Inter-Team Messaging**: Peer teams can route messages directly to other teams' message inboxes using their global registry Team ID:
  `Action: send_peer_message(team_id="AT-xyz789", message="Verify character status of Iris")`
* **Parent Escalation**: If an agent hits a depth gate or lacks permissions, they escalate issues upward:
  `Action: delegate_escalation(objective="Failed to verify rule consistency", rationale="Depth limit reached")`
  The parent team automatically consumes and summarizes these inbox alerts during their next active turn.

### 3. Bind Tool Auditor (Security Hook)

Intercept tool execution transparently before running to check rules or safety:

```python
def audit_db_query(*args, **kwargs) -> tuple[bool, str]:
    sql = args[0] if args else kwargs.get("sql_command")
    if "DROP" in sql.upper():
        return False, "Dangerous DROP command blocked."
    return True, "Safe query"

manager.register_tool_auditor("query_db", audit_db_query)
```

### 4. Setup Event Hooks (UI / Logging)

Connect your terminal console dashboard (e.g. `rich.live`), custom file loggers, and team migration updates using callbacks:

```python
# Wire status display updates
manager.on_status_change = lambda name, status: my_dashboard.update_agent_status(name, status)
manager.on_activity_added = lambda name, act_type, content: my_dashboard.add_log(name, act_type, content)

# Wire logging callback
def my_log_callback(team_id, title, content, chapter_num):
    my_file_logger.write(f"[{team_id}] {title}\n{content}")
    
manager.on_log_append = my_log_callback

# Wire team migration callback
def my_migration_callback(team_id, old_parent_id, new_parent_id):
    print(f"Team {team_id} moved from {old_parent_id} to {new_parent_id}")

manager.on_team_migration = my_migration_callback
```

### 5. Spawn Team & Execute Discussion

```python
# Spawn dynamic level 1 team using analysts preset
team = manager.create_agent_team(
    creator=root_agent,
    member_count=3,
    preset_name="analysts"
)

# Run cooperative multi-round debate
transcript = manager.execute_team_discussion(
    team=team,
    prompt="Audit the system logic mapping for project A.",
    rounds=2
)
print("Debate result:", transcript)
```

### 6. Dynamic Team Migration & Topology Tree

ATT supports dynamic lineage migration, allowing active teams to request hierarchy updates at runtime. You can also print the active tree hierarchy:

```python
# Print the current active lineage hierarchy as an indented ASCII tree
tree_representation = manager.render_topology_tree()
print(tree_representation)
# Outputs:
# - [Root AI: Root_AI] (Level 0)
#   ├── AT-abc123 (Purpose: Spec Review) [Level 1]
#   │    └── AT-def456 (Purpose: Security Check) [Level 2]
#   └── AT-xyz789 (Purpose: Docs Generation) [Level 1]
```

## ⚙️ Advanced Configuration

### `ATTConfig` Parameters

Configure `ATTConfig` to fine-tune the multi-agent debate loop, depth boundaries, and latency profiles:

| Configuration Property | Type | Default Value | Description |
| :--- | :--- | :--- | :--- |
| `enable_dynamic_delegation` | `bool` | `True` | Whether to allow agents to spawn child sub-teams (Level $N$ panels). |
| `max_delegation_depth` | `int` | `2` | The maximum hierarchy depth limit of recursive dynamic subagent spawning lineages. |
| `min_subagent_team_size` | `int` | `3` | The minimum number of members allowed when initiating a dynamic team panel. |
| `subagent_discussion_rounds` | `int` | `2` | The number of debate discussion rounds executed during dynamic child subagent calls. |
| `react_max_steps` | `int` | `5` | The reasoning step limit capped per agent turn to prevent infinite ReAct loops. |
| `inbox_summarize_threshold_chars` | `int` | `1500` | The text character threshold above which unread inbox alerts are summarized. |
| `model_registry` | `dict` | `{}` | Mapping of specialized agent roles to specific LLM models or endpoints. |
| `max_migrations_per_team_discussion` | `int` | `1` | The maximum hierarchy migration requests a team can execute during a single discussion session. |
| `enable_membership_voting` | `bool` | `False` | Whether to enable the optional democratic membership voting system. |
| `llm_max_retries` | `int` | `3` | The maximum retry attempts for LLM generation failures. |
| `llm_retry_backoff_factor` | `float` | `1.5` | The exponential backoff multiplier for retrying LLM calls. |

### `GatedFileReader` Parameters

Configure file reading gates to safeguard the prompt context from massive logs or code databases:

| Configuration Property | Type | Default Value | Description |
| :--- | :--- | :--- | :--- |
| `large_threshold_kb` | `int` | `50` | File size limit triggering an outline warning if no line boundaries are provided. |
| `max_chunk` | `int` | `100` | Capped line slice count returned per paginated chunk request. |

## 🧪 Developer Testing

For guidelines on test structure and instructions on mocking multi-round sequential agent discussions, consult the developer guide:

* **[Developer Testing & Mocking Guide](docs/dev/testing.md)**

## 📄 License

Distributed under the Apache License 2.0. See `LICENSE.txt` for details.
