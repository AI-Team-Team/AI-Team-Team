# Quickstart Guide

Welcome to **AI-Team-Team (ATT)**! This guide will help you integrate ATT into your project, define custom tools, configure LLM client adapters, and run hierarchical multi-agent debates.

## 📦 1. Installation

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

## 🔌 2. Implementing the LLM Client

ATT is backend-agnostic. To connect your LLM provider (e.g., Google GenAI, OpenAI, Anthropic, or a local model), you must provide a client class that implements the `LLMClientProto` protocol.

The adapter class must implement a `generate` method with the following signature:

```python
from typing import Optional, Any

class MyLLMClient:
    def generate(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.3,
        require_json: bool = False,
        **kwargs
    ) -> str:
        """
        Generates text completion.
        
        Args:
            prompt: The user query or discussion history.
            system_instruction: Guidelines and context injected for the agent.
            temperature: Sampling temperature.
            require_json: If True, you MUST return a valid JSON string (used by the 3-AI Supervisory Team).
        """
        # Call your LLM SDK here (e.g., openai.ChatCompletion.create or genai.GenerativeModel.generate_content)
        # Ensure that if require_json is True, the model's output format is strict JSON.
        response_text = ... 
        return response_text
```

## 🛠️ 3. Registering Custom Tools & Presets

You can extend agents' capabilities by registering custom tools and committees.

### Defining Tools

When registering a custom tool, **always specify parameter names and types in the description**. ReAct agents parse this description to discover how to formulate their actions.

```python
from ai_team_team import ATTManager, Agent, ATTConfig

# 1. Initialize configuration
config = ATTConfig(
    enable_dynamic_delegation=True,
    max_delegation_depth=3,      # Support deep recursive spawning
    min_subagent_team_size=3
)

# 2. Initialize manager
llm_client = MyLLMClient()
root_agent = Agent(name="Root_AI", role="Architect", llm_client=llm_client)
manager = ATTManager(root_ai=root_agent, critic_client=llm_client, config=config)

# 3. Register a custom tool
def search_knowledge_base(query: str, limit: int = 3) -> str:
    # Your search logic (e.g., VectorDB lookup)
    return "Search results..."

manager.register_tool(
    name="search_kb",
    description="Search the project knowledge base. Arguments: query (str), limit (int)",
    func=search_knowledge_base
)
```

### Tool Interception Auditing

You can register an auditing callback to check specific tool arguments before execution for safety, logging, or approval:

```python
def audit_search(query: str, limit: int = 3) -> tuple[bool, str]:
    if len(query) < 3:
        return False, "Query is too short"
    return True, "Approved"

manager.register_tool_auditor("search_kb", audit_search)
```

### Registering Committee Presets

Presets allow you to define custom roles and instructions for dynamic sub-teams spawned at runtime:

```python
manager.register_preset(
    name="reviewers",
    description="Validates code and logic alignment",
    system_instructions="Focus strictly on finding logic errors.",
    roles=[
        ("Logic_Reviewer", "Checks algorithmic correctness"),
        ("Security_Reviewer", "Identifies security vulnerabilities"),
        ("Arbitrator", "Synthesizes the final review report")
    ]
)
```

## 🚀 4. Spawning Teams & Executing Debates

Once tools and presets are registered, you can spawn your Level 1 agent team and start a discussion loop:

```python
# Spawn Level 1 team using the 'reviewers' preset
team = manager.create_agent_team(
    creator=root_agent,
    member_count=3,
    preset_name="reviewers",
    team_purpose="Perform security and logic audits on the database schema."
)

# Execute debate discussion (rounds=2 means each member speaks twice)
transcript = manager.execute_team_discussion(
    team=team,
    prompt="Audit the schema details provided in file_schema.sql.",
    rounds=2
)

print("Debate Transcript:\n", transcript)
```

## 📊 5. Hooking up status display & custom logs

ATT decouples implementation logic from user interfaces and file loggers. Use event callbacks to stream activity updates and build terminal dashboards:

```python
# Update agent thinking state on terminal dashboard
def status_callback(agent_name: str, status: str):
    print(f"[STATUS] {agent_name} -> {status}")

manager.on_status_change = status_callback

# Record specific action activities (Thoughts, Tool Actions, Observations)
def activity_callback(agent_name: str, activity_type: str, content: str):
    print(f"[{activity_type}] {agent_name}: {content}")

manager.on_activity_added = activity_callback

# Append detailed logs or transcripts to database/files
def log_append_callback(team_id: str, title: str, content: str, chapter_num: Optional[int]):
    with open(f"att_{team_id}.log", "a") as f:
        f.write(f"\n=== {title} ===\n{content}\n")

manager.on_log_append = log_append_callback
```

## 🔗 6. Dynamic Team Migration & Topology Tree

ATT supports dynamic organizational restructuring at runtime. A team can request to migrate itself under a different parent team in the active hierarchy using the `request_migration` tool.

### Topology Tree Rendering

You can print the current active lineage hierarchy as an indented ASCII tree:

```python
tree_representation = manager.render_topology_tree()
print(tree_representation)
# Outputs:
# - [Root AI: Root_AI] (Level 0)
#   ├── AT-abc123 (Purpose: Spec Review) [Level 1]
#   │    └── AT-def456 (Purpose: Security Check) [Level 2]
#   └── AT-xyz789 (Purpose: Docs Generation) [Level 1]
```

### Hooking up Migration Callbacks

Register a callback on `ATTManager` to catch approved hierarchy migrations (e.g., to update a visual graph layout):

```python
def migration_callback(team_id: str, old_parent_id: Optional[str], new_parent_id: str):
    print(f"[MIGRATION] Team {team_id} moved from {old_parent_id} to {new_parent_id}")

manager.on_team_migration = migration_callback
```

## 🤖 7. Heterogeneous LLM Registry (Multi-Model Support)

ATT features a formal registry system allowing dynamic teams to assign different members to different models based on task complexity (e.g. using a fast model for basic tasks and a strong model for planning).

### Registering Clients

You can register client instances under specific names using either Mode 1 or Mode 2:

```python
# Mode 1: Register pre-initialized custom client instance
manager.register_llm_client(
    name="",
    client=my_custom_client
)

# Mode 2: Register built-in client wrapper using API keys directly
manager.register_llm_client(
    name="",
    provider="google",
    api_key="AIzaSy...",
    model=""
)

manager.register_llm_client(
    name="openai-strong",
    provider="openai",
    api_key="sk-...",
    model=""
)
```

### Assigning Clients to Agents

You can route different agents to different registered models when spawning a team using the `roles_and_models` mapping:

```python
# Spawn a team where Specialist_A uses openai-strong, and Specialist_B uses gemini-flash
team = manager.create_agent_team(
    creator=root_agent,
    member_count=3,
    preset_name="generic",
    roles_and_models={
        "Specialist_A": "openai",
        "Specialist_B": "gemini"
    }
)
```

### Dynamic Subagent Routing

ReAct agents can dynamically specify different models when spawning child subagent teams via the `dispatch_subagent` tool:

```text
Thought: I need a strong planner and a fast writer.
Action: dispatch_subagent(
    task="Write the report",
    team_purpose="Reporting",
    roles_and_models={"Planner": "openai", "Writer": "gemini"}
)
```
