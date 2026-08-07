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

The ATT framework organizes dynamic multi-agent topologies into clean, recursive lineages with robust governance, safety gates, and state persistence:

### 🧬 Topology & Lineage Control

* **[Tree-like Lineage Spawning](docs/Dynamic_Delegation.md)**: Spawns recursive child agent teams (`AgentTeam`) at runtime to arbitrary depths, strictly bounded by depth limits to prevent stack overflow.
* **[Autonomous Member Configs](docs/Dynamic_Delegation.md#1-dynamic-spawning-&-lineage-hierarchy)**: Defines dynamic child memberships mapping role presets, custom system instructions, and LLM aliases to shape custom agent personalities.
* **[Dynamic Lineage Migration](docs/Dynamic_Delegation.md)**: Permits active teams to request parent-hierarchy migrations, arbitrated by modular strategies with loop/cycle detection and parent notification logs.
* **[Hierarchical Topology Map](docs/Dynamic_Delegation.md)**: Injects an ASCII-drawn indented tree map of active teams (displaying purposes, status, and progress metrics in real-time) directly into the agent prompt context.
* **[Global Expert Discovery](docs/State_Persistence.md)**: Automatically appends a directory of all active system experts (names, roles, and profiles) into the agent's identity context to facilitate peer discovery.
* **Shared-Agent Continuity**: One `Agent` may participate in several teams with one identity and complete memory. Invocation-scoped team/discussion context keeps prompts and team-sensitive tools correctly scoped while the agent's own model calls remain serialized.
* **[Resilient Failover Routing](docs/Team_Governance.md#5-token-budget--failover-policies)**: Dynamically hot-swaps exhausted or failing model clients. Supports `"auto"` selection and asynchronous `"parent"` representative selection.

### 🧠 ReAct Loops & Execution Engine

* **Bounded ReAct Loops**: Executes standard Thought/Action/Observation reasoning cycles, capped by max steps to prevent runaway API tokens.
* **Robust Argument Parser**: A safe literal lexical parser (`ast.literal_eval`) with multiline XML support, code block stripping, and a comma-merging heuristic to handle unquoted complex strings (like SQL queries).
* **[Bounded Memory Compression](docs/State_Persistence.md)**: Automates memory pruning by extracting early conversation turns, calling the agent's LLM to generate a `*** HISTORICAL SUMMARY ARCHIVE ***`, and retaining a bounded high-fidelity window.
* **[LLM Adapter Architecture](docs/Tool_System.md)**: Unifies sync, async, and streaming LLM payloads from various providers (Google, OpenAI, Anthropic) into standard `LLMResponse` and `ToolCall` formats via the `ManagerDefaultClientAdapter`.
* **[Atomic Token Budget Circuit Breakers](docs/Team_Governance.md#5-token-budget--failover-policies)**: Enforces hard per-model quotas by atomically reserving prompt and maximum output capacity before each request, settling provider usage, refunding unused capacity, and routing failover through the same ledger.

### 🗳️ Governance & Inter-Team Communication

* **[Democratic Voting System](docs/Dynamic_Delegation.md#5-team-governance-&-democratic-voting-system)**: Features an asynchronous voting pipeline to add or remove members, requiring unanimous participation and a $\ge 2/3$ agreement majority.
* **Anonymous Voting**: Enforces voter anonymity via `cast_vote(..., public=False)` which masks voter names as `"Anonymous Voter"` in the team prompt context.
* **[Proxied Negotiation Broker](docs/Team_Governance.md)**: Regulates P2P messaging and cross-lineage tunnels. The `"proxied"` policy identifies Representative Agents (Team Leaders) of both the Sender and Recipient parents, orchestrating parallel LLM evaluations to jointly authorize secure Peer-to-Peer messaging.

### 🔒 Context Protection & Safety Gates

* **[Gated Context Protection](docs/Gated_Reading.md)**: Restricts direct large file reads; falls back to Outline Warnings with a 5-line sample of files exceeding 50 KB, prompting agents to make paginated, sliced chunk requests.
* **[Collaborative DocLib Storage](docs/Gated_Reading.md#5-document-libraries-doclib)**: Equips teams with built-in document libraries. Access is governed by prefix path ACL permissions (`READ`/`WRITE`) that inherit recursively downward to subdirectories.
* **Tool Auditor Interception**: Registers pre-execution interception hooks to audit, vet, approve, or reject specific tool calls (e.g. database safety query check).

### 💾 Persistence & Diagnostics

* **[Asynchronous SQLite Persistence](docs/State_Persistence.md)**: Serializes changed topology, memory, DocLib, ACL, and governance records through an exclusive cross-process writer lease with one active and one coalesced pending delta, explicit flush, and transactional restore validation.
* **[Supervisory Dialogue Audits](docs/Supervisory_Team.md)**: A non-participating 3-AI Supervisory Team executes parallel LLM evaluations (Integrity Auditor, Continuity Auditor, Deadlock Auditor) to review round transcripts, recursively escalating anomalies up the tree lineage.
* **Decoupled Dashboards**: Dispatches synchronous or asynchronous runtime callbacks (`on_status_change`, `on_activity_added`, `on_log_append`) in order on an isolated background channel, so slow or failing observers cannot block discussions.

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
    %% Coordinator Layer
    subgraph Coordinator ["ATT Coordinator Layer"]
        Manager[ATTManager] <-->|Auto-Save & Restore state| SQLite[(SQLite Database)]
        SQLite -.->|"Versioned incremental transactions"| SQLite
        Manager -->|Resolve Model Configs| ModelRegistry[Model Registry & Presets]
        ModelRegistry -->|Route Requests| Generator[Global Generator Handler]
        Manager -->|Tracks Subscribed Callbacks| EventHooks["Event Callbacks: on_status_change, on_activity_added, on_log_append, on_team_migration, on_emergency_escalation"]
    end

    %% Lineage Spawning
    Root["Root Agent (Level 0)"] -->|"create_agent_team(creator)"| TeamA_Node["Agent Team A (Level 1)"]
    Root -->|"create_agent_team(creator)"| TeamB["Agent Team B (Level 1)"]
    
    Manager -->|Manages Lineages| Root
    
    subgraph Lineage ["Hierarchical Team Lineage (Arbitrary Depth)"]
        subgraph TeamA_Node ["Agent Team A - Level 1 (N >= 3 Members)"]
            Agent_A1["Agent A1"] <-->|True Multi-Turn Memory| A1_Memory[(Agent Messages Buffer)]
            A1_Memory -->|Turns > Max + 2| MemoryPruning["Memory Pruning & LLM Summarization<br/>(Preserves latest context bounds)"]
            Agent_A1 -->|execute_reasoning_step| StrategySelector{Strategy Selector}
            
            %% Strategy routes
            StrategySelector -->|"Config Mode: 'auto' / supports_native_tool_calling"| Strategy{Pluggable Reasoning Strategy}
            Strategy -->|Text ReAct Strategy| TextReactStrategy["TextReactReasoningStrategy<br/>(Sequential Thought-Action-Observation)"]
            Strategy -->|Native Strategy| NativeStrategy["NativeReasoningStrategy<br/>(Structured Parallel Tool Calling)"]
        end
        
        TeamA_Node -->|"dispatch_subagent(member_configs)"| SubTeamA1["Sub-Agent Team A.1 (Level 2)"]
        SubTeamA1 -->|"dispatch_subagent(member_configs)"| SubTeamN["Sub-Agent Team N (Level N)"]
    end

    %% Tool Execution & Auditing Hook
    subgraph ToolExecution ["Tool Execution Gating"]
        ToolRegistry[Tool Registry: default & custom tools] -->|Intercepts & Vets| ToolAuditor[ToolAuditor Hook]
        
        %% Text ReAct Flow
        TextReactStrategy -->|"1. Parse response for XML Action tags"| SafeASTParser["Safe AST Parser<br/>(ast.literal_eval arguments)"]
        SafeASTParser -->|"2. Execute Action"| ToolRegistry
        
        %% Native Flow
        NativeStrategy -->|"1. Fetch native Tool objects"| ThoroughAbstraction["Thorough Abstraction Paradigm"]
        ThoroughAbstraction -->|"2. generate(prompt, tools=List[Tool])"| Generator
        Generator -->|"3. returns LLMResponse(text, tool_calls)"| NativeStrategy
        
        NativeStrategy -->|4. Run ToolCalls concurrently| ParallelExecute["asyncio.gather parallel execution"]
        ParallelExecute -->|5. execute| ToolRegistry
        ToolRegistry -->|6. return ToolResult| ParallelExecute
        ParallelExecute -->|7. Append ToolResult messages| A1_Memory
    end
    
    Manager -->|Registers Tools & Auditors| ToolRegistry
    A1_Memory <-->|Save/Restore state| SQLite

    %% Document Library & Gated Reading
    subgraph DocStorage ["Gated Document Storage (DocLib)"]
        GatedReader["GatedFileReader"] -->|"Size Filters / Outline Warnings / Paginated Chunking"| DocLibA[(DocLib A)]
        GatedReader -->|Slices Context Lines| DocLibA1[(DocLib A.1)]
        GatedReader -->|Restricts Tokens| DocLibN[(DocLib N)]
        GatedReader -->|"Path ACL Segment Inheritance"| DocLibB[(DocLib B)]
        
        %% Outline Warnings & Chunking loops
        GatedReader -.->|"Size > 50KB & No range: Outline Warning (first 5 lines)"| Agent_A1
        Agent_A1 -.->|"Request slice: start_line, end_line (max 100 lines)"| GatedReader
    end
    
    ToolRegistry -->|"Built-in Lib Read/Write"| GatedReader
    
    TeamA_Node --- DocLibA
    SubTeamA1 --- DocLibA1
    SubTeamN --- DocLibN
    TeamB --- DocLibB
    
    DocLibA1 -.->|"Request Access / Grant READ-WRITE"| DocLibB

    %% Communication Permission Gating
    subgraph CommunicationGating ["P2P Communication Gating"]
        Broker[NegotiationBroker] -->|Consults Strategy| CommPolicy["Communication Policy:<br/>Permissive / RuleGated / Proxied"]
        CommPolicy -->|Evaluate Sibling Rules & Lineage Contracts| SubTeamN
        CommPolicy -.->|"Approve / Deny Tunnel"| TeamB
        
        %% Proxied flow
        Broker -.->|"Proxied: LLM evaluations by both Parent Reps"| Broker
        Agent_A1 -.->|"set_sibling_talk(child_id, allow)"| Broker
    end
    
    Manager -.->|Coordinates Tunnels| Broker
    ToolRegistry -->|P2P Messaging| Broker

    %% Lineage Reorganization & Context Transition
    subgraph LineageMigration ["Lineage Migration Arbitration"]
        MigrationPolicy["Migration Policy:<br/>Permissive / AncestorApproval / LineagePath"] -->|"Tree Restructuring (Update Pointers)"| Manager
        MigrationPolicy -.->|Hires Shared Agent| TransitionNotice["Context Transition Notice<br/>(Inject system warning update)"]
        
        %% LCA and Arbitration details
        MigrationPolicy -->|Resolve LCA| LCAResolver["Least Common Ancestor (LCA) Resolver"]
        MigrationPolicy -->|"LLM debate / vote"| LLMArbitration["LLM Representative Arbitration Loop<br/>(Harvest old/new/LCA parent reps)"]
    end
    
    SubTeamN -->|request_migration| MigrationPolicy
    TransitionNotice -.->|Appends Notice to Memory| A1_Memory
    ToolRegistry -->|Migration Actions| MigrationPolicy

    %% Supervisory Dialogue Audits & Escalation
    subgraph Supervision ["Lineage Supervision & Emergency Wakeup"]
        Supervisor["3-AI SupervisoryTeam"] -->|audit_team_dialog| TeamA_Node
        
        %% 3 Auditors split
        Supervisor -->|Consensus analysis| IntegrityAuditor["Integrity Auditor (logic safety)"]
        Supervisor -->|Consensus analysis| ContinuityAuditor["Continuity Auditor (progress)"]
        Supervisor -->|Consensus analysis| DeadlockAuditor["Deadlock Auditor (loop detection)"]
        
        Supervisor -->|"report_anomaly escalation"| ParentInbox["Parent Team Inbox / Escalation Alert"]
        ParentInbox -->|Injected into Discussion| TeamA_Node
        Supervisor -->|Fallback Escalation| Root
        
        %% Emergency wakeup
        ParentInbox -->|Message received & idle| WakeupGate{"enable_emergency_wakeup?"}
        WakeupGate -- "Yes" --> EmergencyWakeup["execute_emergency_discussion<br/>(Reads deferred ParentInbox alerts & triggers debate)"]
    end
    
    Manager -.->|Orchestrates Audits| Supervisor

    %% Democratic Voting System
    subgraph TeamGovernance ["Democratic Team Governance"]
        SubTeamA1 -->|initiate_membership_vote| Voting["Democratic Voting<br/>Threshold: >= 2/3"]
        Voting -->|Creates Proposal| VotingProposal["Voting Proposal<br/>(VP-xxxx in SQLite DB)"]
        VotingProposal -->|cast_vote| Voting
        
        %% Anonymous voting
        Voting -->|"public=False"| AnonymousBallot["Anonymous Ballot<br/>(Mask voter name as 'Anonymous Voter')"]
        AnonymousBallot --> Voting
        
        Voting -->|"Approved: add/remove member"| SubTeamA1
    end
    
    ToolRegistry -->|Voting Actions| Voting

    %% Styles
    style Coordinator fill:#eceff1,stroke:#37474f,stroke-width:2px;
    style Manager fill:#cfd8dc,stroke:#37474f,stroke-width:2px;
    style SQLite fill:#ffffff,stroke:#455a64,stroke-width:1px;
    style ModelRegistry fill:#ffffff,stroke:#455a64,stroke-width:1px;
    style Generator fill:#ffffff,stroke:#455a64,stroke-width:1px;
    style EventHooks fill:#ffffff,stroke:#455a64,stroke-width:1px;
    style Root fill:#d4e1f5,stroke:#3b5998,stroke-width:2px;
    style TeamA_Node fill:#e1f5fe,stroke:#0288d1,stroke-width:2px;
    style TeamB fill:#e1f5fe,stroke:#0288d1,stroke-width:2px;
    style SubTeamA1 fill:#ede7f6,stroke:#5e35b1,stroke-width:2px;
    style SubTeamN fill:#f3e5f5,stroke:#ab47bc,stroke-width:2px;
    style Supervisor fill:#ffe0b2,stroke:#f57c00,stroke-width:2px;
    style ParentInbox fill:#ffe0b2,stroke:#f57c00,stroke-width:2px;
    style Voting fill:#ffebee,stroke:#e53935,stroke-width:2px;
    style DocStorage fill:#f1f8e9,stroke:#558b2f,stroke-width:2px;
    style GatedReader fill:#ffffff,stroke:#558b2f,stroke-width:1px;
    style DocLibA fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px;
    style DocLibA1 fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px;
    style DocLibN fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px;
    style DocLibB fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px;
    style ToolExecution fill:#fffde7,stroke:#fbc02d,stroke-width:2px;
    style ToolRegistry fill:#ffffff,stroke:#fbc02d,stroke-width:1px;
    style ToolAuditor fill:#ffffff,stroke:#fbc02d,stroke-width:1px;
    style StrategySelector fill:#ffffff,stroke:#0288d1,stroke-width:1px;
    style TextReactStrategy fill:#ffffff,stroke:#0288d1,stroke-width:1px;
    style NativeStrategy fill:#ffffff,stroke:#0288d1,stroke-width:1px;
    style SchemaResolver fill:#ffffff,stroke:#fbc02d,stroke-width:1px;
    style ParallelExecute fill:#ffffff,stroke:#fbc02d,stroke-width:1px;
    style SafeASTParser fill:#ffffff,stroke:#fbc02d,stroke-width:1px;
    style IntegrityAuditor fill:#ffffff,stroke:#ffe0b2,stroke-width:1px;
    style ContinuityAuditor fill:#ffffff,stroke:#ffe0b2,stroke-width:1px;
    style DeadlockAuditor fill:#ffffff,stroke:#ffe0b2,stroke-width:1px;
    style EmergencyWakeup fill:#ffffff,stroke:#ffe0b2,stroke-width:1px;
    style VotingProposal fill:#ffffff,stroke:#ffebee,stroke-width:1px;
    style AnonymousBallot fill:#ffffff,stroke:#ffebee,stroke-width:1px;
    style LCAResolver fill:#ffffff,stroke:#ab47bc,stroke-width:1px;
    style LLMArbitration fill:#ffffff,stroke:#ab47bc,stroke-width:1px;
```

## 🛠️ Getting Started

### 1. Initialize Configuration & Manager

```python
from typing import Union, List, Dict, Optional
from ai_team_team import ATTManager, Agent, ATTConfig

# 1. Configure the framework
config = ATTConfig(
    enable_dynamic_delegation=True,
    max_delegation_depth=2,
    min_subagent_team_size=3,
    subagent_discussion_rounds=2,
    react_max_steps=5,
    enable_memory_compression=True,       # Retains a bounded recent-message window
    failover_policy="auto",               # Automatically hot-swaps LLM client on TokenLimitError
    enable_emergency_wakeup=True,         # Enables deferred inbox processing for emergencies
    tool_calling_mode="auto",             # Auto-detects Pluggable Reasoning Strategy (Native or TextReAct)
    audit_unknown_escalation_mode="wake" # Or "queue"
)

# 2. Setup Root Agent (client is dynamically resolved if omitted)
root_agent = Agent(name="Root_AI", role="Architect")

# 3. Create Manager with SQLite State Snapshotting enabled
# All actions, tool calls, and debates will auto-save to this file
manager = ATTManager(root_ai=root_agent, config=config, db_path="att_state.db")

# 4. Register a global generator callback handler before loading state
# All LLM invocation logic is delegated here, keeping the framework keyless and SDK-independent
async def my_handler(
    model_name: str,
    prompt: Union[str, List[Dict[str, str]]],
    system_instruction: Optional[str] = None,
    max_output_tokens: Optional[int] = None,
    temperature: float = 0.3,
    require_json: bool = False
) -> str:
    # 1. Inspect model_name to call the correct provider/SDK
    # 2. If require_json=True is requested, return valid JSON string
    return "Final Answer: Processed successfully."

manager.register_generator_handler(my_handler)

# 5. Persistence APIs are asynchronous
# if os.path.exists("att_state.db"):
#     await manager.load_state("att_state.db")
# await manager.save_state("att_backup.db")
# await manager.flush_state()
# await manager.close()
```

Direct client objects must have one stable identity binding before state is saved.

A client's `model_name` attribute is not accepted unless that same object is registered under the name:

```python
manager.register_llm_client("analysis", analysis_client)
```

#### 🔌 LLM Client Interface (`LLMClientProto`)

To integrate custom LLM backends (e.g., Google GenAI, OpenAI, Anthropic, or local inference engines), the supplied client must conform to the following signature:

```python
from typing import Optional, Protocol, Union, List, Dict, Any

class LLMResponse:
    text: str
    tool_calls: Optional[List[Dict[str, Any]]]

class LLMClientProto(Protocol):
    async def generate(
        self,
        prompt: Union[str, List[Dict[str, Any]]],
        system_instruction: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        max_output_tokens: Optional[int] = None,
        temperature: float = 0.7,
        require_json: bool = False
    ) -> LLMResponse:
        """
        Generates a text completion or returns structured tool calls.
        When require_json=True is requested by SupervisoryTeam consensus audits,
        the model must return a valid, parsable JSON string via the LLMResponse.text property.
        """
        ...

    def supports_native_tool_calling(self) -> bool:
        """
        Returns True if the client/model configuration natively supports structured function calling.
        """
        ...

    def supports_output_token_limit(self) -> Union[bool, str]:
        """Returns the supported hard-quota parameter name when available."""
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
# The manager supports automatic name and description derivation:
# 1. Automatic derivation from function name and docstring (recommended):
def query_db(sql_command: str):
    """Run safe SQL commands directly on the DB. Arguments: sql_command (str)"""
    return "Query result..."

manager.register_tool(query_db)

# 2. Or explicit/manual registration:
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

# Wire emergency escalation callback
def my_emergency_callback(team_id, alert_type, alert_reason):
    print(f"[EMERGENCY ALERT] Team {team_id} encountered {alert_type}: {alert_reason}")

manager.on_emergency_escalation = my_emergency_callback

# Callbacks may also be async. Tests and hosts that need an observation barrier
# can explicitly wait for all callbacks queued so far.
await manager.flush_callbacks()
```

### 5. Spawn Team & Execute Discussion

```python
# Spawn dynamic level 1 team using analysts preset
team = manager.create_agent_team(
    creator=root_agent,
    member_count=3,
    preset_name="analysts",
    team_purpose="Audit the system logic mapping for project A."
)

# Run cooperative multi-round debate
transcript = await manager.execute_team_discussion(
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
#   ├── AT-abc123 (Purpose: Audit the system logic mapping for project A.) [Level 1]
#   │    └── AT-def456 (Purpose: Security Check) [Level 2]
#   └── AT-xyz789 (Purpose: Docs Generation) [Level 1]
```

### 7. Rule-Gated P2P Communication

When using `config.communication_policy = "rule_gated"`, you can explicitly define regex-based routing rules allowing teams to open P2P tunnels based on target ID, parent ID, or regex purpose matching:

```python
# 1. Enable Rule-Gated Policy
config = ATTConfig(communication_policy="rule_gated")

# 2. Assign Regex/ACL Rules to a Team
team.communication_rules = {
    "allow_sibling_talk": False,
    "rules": [
        "allow_purpose:^Audit.*",  # Allow messaging any team whose purpose starts with "Audit"
        "allow_team:AT-def456",    # Directly allow messaging a specific Team ID
        "allow_parent:AT-xyz789"   # Allow messaging any team spawned by Parent AT-xyz789
    ]
}
```

### 8. Native Strategy (Structured Tool Calling)

By default, ATT uses `tool_calling_mode="auto"`, which falls back to Text-ReAct XML parsing. If your LLM supports native JSON schema function calling (e.g., OpenAI `tools` array), you can force Native parallel execution:

```python
# 1. Force native structured tool calling
config.tool_calling_mode = "native"

# 2. Ensure your model is registered as supporting native tools
manager.register_model("gpt-4o", {
    "supports_native_tool_calling": True
})

# Under the hood, ManagerDefaultClientAdapter will route tools as JSON schemas
# and execute returned ToolCalls concurrently via asyncio.gather.
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
| `llm_max_retries` | `int` | `3` | Number of retries after the initial LLM attempt. `0` performs one attempt without retrying. |
| `llm_retry_backoff_factor` | `float` | `1.5` | Initial exponential-backoff delay. `0` retries immediately. Only typed/provider-classified transient failures are retried. |
| `enable_memory_compression` | `bool` | `True` | Whether to enable automatic dialogue compression/pruning of early conversation turns. |
| `max_memory_turns` | `int` | `20` | The maximum number of conversation messages (turns) retained as high-fidelity context before summarizing older turns. |
| `communication_policy` | `str` | `"permissive"` | The strategy used for inter-team communication gating. Options: `"permissive"`, `"rule_gated"`, `"proxied"`. |
| `migration_policy` | `str` | `"ancestor_approval"` | The strategy used for dynamic lineage migration authorization. Options: `"permissive"`, `"ancestor_approval"`, `"lineage_path"`. |
| `enable_emergency_wakeup` | `bool` | `True` | Whether to trigger active wake-up discussion on idle parent teams upon receiving high-priority child anomalies. |
| `emergency_discussion_rounds` | `int` | `1` | The number of emergency discussion rounds executed when a team is woken up. |
| `tool_calling_mode` | `str` | `"auto"` | Strategy for invoking tools. `"native"`, `"react"`, or `"auto"`. |
| `max_tool_rounds` | `int` | `5` | Max depth of native parallel tool calls during a reasoning step. |
| `max_tool_retries` | `int` | `3` | Number of tool retries after the initial failed attempt. `0` disables retries. |
| `model_token_limits` | `dict` | `None` | Mapping of model aliases to hard token quotas; `0` disables that model's quota entirely. |
| `model_max_output_tokens` | `dict` | `None` | Per-model maximum output reservation/request cap used by the atomic hard-quota ledger. |
| `default_max_output_tokens` | `int` | `1024` | Default maximum output reservation when a model-specific cap is absent. |
| `failover_policy` | `str` | `"auto"` | Fallback strategy on token exhaustion: `"auto"` (next available) or `"parent"` (LLM debate proxy). |
| `audit_unknown_escalation_mode` | `str` | `"wake"` | Handling for indeterminate audits: immediately `"wake"` the parent or only `"queue"` the alert. |
| `audit_unknown_soft_threshold` | `int` | `100` | Soft operational warning threshold for unique UNKNOWN alerts; alerts are never dropped or expired automatically. |

### `GatedFileReader` Parameters

Configure file reading gates to safeguard the prompt context from massive logs or code databases:

| Configuration Property | Type | Default Value | Description |
| :--- | :--- | :--- | :--- |
| `large_threshold_kb` | `int` | `50` | File size limit triggering an outline warning if no line boundaries are provided. |
| `max_chunk` | `int` | `100` | Capped line slice count returned per paginated chunk request. |

## 📊 Architecture & Control Flow Diagrams

For visual flowcharts and sequencing diagrams detailing the runtime loops, gated checks, and state serialization flows, refer to:

* **[ATT Autonomy Suite Flowcharts Index](docs/flowcharts/README.md)**
* **[Tooling & Execution (Adapters, ReAct, Memory Compression)](docs/flowcharts/Tooling_and_Execution.md)**
* **[State Persistence (SQLite Recovery & ORM Deletions)](docs/flowcharts/State_Persistence.md)**
* **[Lineage Tree Mutations (Spawning, Voting, Proxied Negotiation)](docs/flowcharts/Lineage_Tree_Mutations.md)**
* **[Supervision & Emergencies (3-AI Audits, Emergency Wakeup)](docs/flowcharts/Supervision_and_Emergencies.md)**
* **[Gated Paginator Reading & DocLib ACL Traversal](docs/flowcharts/Gated_Reading.md)**

## 📄 License

Distributed under the Apache License 2.0. See `LICENSE.txt` for details.
