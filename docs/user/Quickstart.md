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
from typing import Any, List, Optional

class MyLLMClient:
    async def generate(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        tools: Optional[List[Any]] = None,
        max_output_tokens: Optional[int] = None,
        temperature: float = 0.3,
        require_json: bool = False,
        **kwargs
    ) -> str:
        """
        Generates text completion.
        
        Args:
            prompt: The user query or discussion history.
            system_instruction: Guidelines and context injected for the agent.
            tools: Optional list of native `Tool` instances. Adapters MUST parse these into their provider's schema manually.
            max_output_tokens: Required provider output ceiling when a hard token quota is configured.
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

# 2. Initialize manager and register global generator handler callback
root_agent = Agent(name="Root_AI", role="Architect")
manager = ATTManager(root_ai=root_agent, config=config)

async def my_generator_handler(
    model_name: str,
    prompt: str,
    system_instruction: Optional[str] = None,
    tools: Optional[List[Any]] = None,
    max_output_tokens: Optional[int] = None,
    temperature: float = 0.3,
    require_json: bool = False
) -> str:
    # Perform actual SDK completion call here
    return "Final Answer: Done"

manager.register_generator_handler(my_generator_handler)

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
transcript = await manager.execute_team_discussion(
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

# Callbacks run on an ordered background dispatcher. Wait at an observation
# boundary when the host needs to know that every callback has completed.
await manager.flush_callbacks()
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

# Register a callback to catch high-priority emergency alerts or parent escalations
def emergency_callback(team_id: str, alert_type: str, alert_reason: str):
    print(f"[EMERGENCY] Team {team_id} received {alert_type}: {alert_reason}")

manager.on_emergency_escalation = emergency_callback
```

## 🤖 7. Model Registry & Global Generator Callback (Multi-Model Support)

ATT features a unified model registry allowing dynamic teams to assign different members to different model configurations based on task complexity (e.g. using a fast model for basic tasks and a strong model for planning). All LLM requests are resolved through a centralized global generator callback handler.

### Registering Models & Callback Handlers

Instead of passing raw API keys or client instances directly to the framework, register your model configuration details and provide a single callback function to execute the generation requests:

```python
# 1. Register model configurations (metadata/descriptions for the AI)
manager.register_model("gemini-123", {
    "model_type": "llm",
    "model_name": "gemini-3.5-flash",
    "ai_note": "gemini-3.5-flash - A very impressive large model"
})

manager.register_model("openai-123", {
    "model_type": "llm",
    "model_name": "gpt-5.5",
    "ai_note": "gpt-5.5 - A very impressive large model"
})

# 2. Register a single global callback handler to execute LLM calls
# The host application keeps full control of API Keys, endpoint routing, and SDKs.
async def my_generator_handler(
    model_name: str,
    prompt: str,
    system_instruction: Optional[str] = None,
    tools: Optional[List[Any]] = None,
    max_output_tokens: Optional[int] = None,
    temperature: float = 0.3,
    require_json: bool = False
) -> str:
    # Look up the registered config to get the real model name
    config = manager.model_configs.get(model_name)
    real_name = config.get("model_name") if config else model_name

    if real_name == "gemini-3.5-flash":
        return await call_gemini_sdk(prompt, system_instruction, tools, max_output_tokens, temperature, require_json)
    elif real_name == "gpt-5.5":
        return await call_openai_sdk(prompt, system_instruction, tools, max_output_tokens, temperature, require_json)
    
    # Fallback default model
    return await call_default_sdk(prompt, system_instruction, tools, max_output_tokens, require_json)

manager.register_generator_handler(my_generator_handler)
```

### Assigning Models to Agents

You can route different agents to different registered model names when spawning a team using the `roles_and_models` mapping:

```python
# Spawn a team where Specialist_A uses openai-123, and Specialist_B uses gemini-123
team = manager.create_agent_team(
    creator=root_agent,
    member_count=3,
    preset_name="generic",
    roles_and_models={
        "Specialist_A": "openai-123",
        "Specialist_B": "gemini-123"
    }
)
```

### Dynamic Subagent Routing

ReAct agents can dynamically specify different models when spawning child subagent teams via the `dispatch_subagent` tool:

```plaintext
Thought: I need a strong planner and a fast writer. I will spawn a child team of 3 agents.
Action: dispatch_subagent(
    task="Write the report",
    team_purpose="Reporting",
    member_configs={
        "Planner": {
            "model": "openai-123",
            "role_description": "Designs outline and schedules work",
            "system_instructions": "Focus on clarity and conciseness"
        },
        "Writer": {
            "model": "gemini-123",
            "role_description": "Drafts the report sections",
            "system_instructions": "Use rich descriptors and clean prose"
        },
        "Reviewer": {
            "model": "gemini-123",
            "role_description": "Checks logic and style consistency",
            "system_instructions": "Be strict on formatting rules"
        }
    }
)
```

## 📂 8. Collaborative Document Library (DocLib)

Every Agent Team features a built-in document library (`DocLib`) to store documents, pass context down, and share specs across teams.

### Spawning with Context Documents

To bridge the context gap when spawning a child team, you can pass initial files directly into the child's default DocLib during `dispatch_subagent`:

```plaintext
Thought: I need a subagent team to write a report. I will pass the design outline directly to their library.
Action: dispatch_subagent(
    task="Draft the report using design_outline.md as reference.",
    team_purpose="Report Draft",
    initial_documents={
        "design_outline.md": "# Design Outline\n1. Intro\n2. Design Specs\n3. Conclusion"
    }
)
```

### Library Discovery & Metadata

An Agent Team can publish its library globally (allowing other teams to find its name and description) by setting visibility to public:

```python
# Create a team with globally discoverable library
team = manager.create_agent_team(
    creator=root_agent,
    member_count=3,
    is_public_visible=True
)
```

Other teams can search for discoverable libraries at runtime:

- `Action: list_public_libraries()`

### Granting and Requesting Access (ACL)

By default, a team's DocLib is private and only accessible by its own members. To share a document or folder, the owner team can grant permissions:

- **Grant access**: `Action: grant_library_permission(lib_id="DL-AT-abc123", path="/specs", target_team_id="AT-xyz789", permission="READ")`
- **Revoke access**: `Action: revoke_library_permission(lib_id="DL-AT-abc123", path="/specs", target_team_id="AT-xyz789")`

Agent teams can request access by sending a peer message to the owner team:

- `Action: send_peer_message(team_id="AT-abc123", message="Please grant READ permission to team AT-xyz789 for library DL-AT-abc123 path /specs.")`

### File Operations (Gated Context Protection)

Agent teams can use standard file operations:

- **Write file**: `Action: write_library_file(lib_id="DL-AT-abc123", path="/specs/guide.txt", content="New guide text")`
- **Read file**: `Action: read_library_file(lib_id="DL-AT-abc123", path="/specs/guide.txt", start_line=1, end_line=50)`
- **List files**: `Action: list_library_files(lib_id="DL-AT-abc123", path="/")`
- **Delete file**: `Action: delete_library_file(lib_id="DL-AT-abc123", path="/specs/guide.txt")`
- **Create managed file link**: `Action: create_library_link(source_lib_id="DL-AT-xyz789", source_path="/references/guide.txt", target_lib_id="DL-AT-abc123", target_path="/specs/guide.txt")`

All `read_library_file` operations are automatically audited by the `GatedFileReader`. If a team member attempts to read a file exceeding 50 KB without specifying a line chunk window, the operation will be rejected and return an Outline Warning, protecting the LLM context from pollution.

Managed links work only between registered DocLib files. Creation requires `WRITE` on the source path and `READ` on the target. Reads and writes recheck the target ACL every time; writes require target `WRITE`, and deleting the link does not delete the target file. Native filesystem symlinks are rejected.
