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

## ⚙️ 2. Configure ATT and Create the Manager

Create the Root Agent and `ATTManager` after selecting the framework-wide policies that every AgentTeam will follow:

```python
from ai_team_team import ATTManager, Agent, ATTConfig, EpisodicMemoryConfig

config = ATTConfig(
    enable_dynamic_delegation=True,
    max_delegation_depth=2,
    min_subagent_team_size=3,
    subagent_discussion_rounds=2,
    react_max_steps=5,
    enable_memory_compression=True,
    episodic_memory=EpisodicMemoryConfig(enabled=False),  # Optional advanced mode
    failover_policy="auto",
    enable_emergency_wakeup=True,
    tool_calling_mode="auto",
    audit_unknown_escalation_mode="wake",  # Or "queue"
    agent_private_data_policy="archive",  # Or "retain" / "delete"
)

root_agent = Agent(name="Root_AI", role="Architect")
manager = ATTManager(root_ai=root_agent, config=config, db_path="att_state.db")
```

Supplying `db_path` enables asynchronous incremental persistence and automatic saving of accepted state changes.

Register the runtime model bindings described below before loading persisted state, because callables and external connections are intentionally not serialized.

### Stable Client and Agent Registration

A direct client object must have one stable identity binding before related state can be saved, and its `model_name` attribute is accepted as an alias only when the same client object is registered under that name:

```python
manager.register_llm_client("analysis", analysis_client)
```

Register every external Agent through the manager so ATT can preserve its UUID, model binding, lifecycle record, inbox, and single Private DocLib across all team memberships:

```python
researcher = Agent("Researcher", "Evidence analyst", analysis_client)
manager.register_agent(researcher)
private_id = manager.get_private_library_id(researcher.agent_id)

await manager.retire_agent(researcher.agent_id)  # Default policy: archive.
await manager.reactivate_agent(researcher.agent_id, "analysis")
```

Retirement and reactivation preserve the same Agent identity and private library unless the explicit, confirmed `delete` lifecycle policy is used.

## 🔌 3. Implement the LLM Client

ATT is backend-agnostic. To connect your LLM provider (e.g., Google GenAI, OpenAI, Anthropic, or a local model), you must provide a client class that implements the `LLMClientProto` protocol.

The adapter class must implement `generate` and the two synchronous capability methods in `LLMClientProto`:

```python
from typing import Any, Dict, List, Optional, Union

from ai_team_team import LLMResponse, Tool

class MyLLMClient:
    async def generate(
        self,
        prompt: Union[str, List[Dict[str, Any]]],
        system_instruction: Optional[str] = None,
        tools: Optional[List[Tool]] = None,
        max_output_tokens: Optional[int] = None,
        temperature: float = 0.7,
        require_json: bool = False,
    ) -> LLMResponse:
        """
        Generates a text completion or returns structured tool calls.
        
        Args:
            prompt: The user query or discussion history as text or message dictionaries.
            system_instruction: Guidelines and context injected for the agent.
            tools: Optional provider-neutral `Tool` instances to convert into the provider's schema.
            max_output_tokens: Required provider output ceiling when a hard token quota is configured.
            temperature: Sampling temperature.
            require_json: If True, you MUST return a valid JSON string for governance, supervision, or optional episodic-memory indexing.
        """
        response_text = await call_provider_sdk(...)
        return LLMResponse(text=response_text)

    def supports_native_tool_calling(self) -> bool:
        # Auto mode selects Native Strategy only for the literal boolean True.
        return False

    def supports_output_token_limit(self) -> Union[bool, str]:
        # Return the provider parameter name, True for max_output_tokens, or False.
        return "max_output_tokens"
```

When `require_json=True`, the response text must be valid JSON because governance, supervision, and optional memory indexing use strict structured results.

## 🛠️ 4. Register Custom Tools and Presets

You can extend agents' capabilities by registering custom tools and committees.

### Defining Tools

When registering a custom tool, provide precise type hints and a concise description.

ATT generates and validates the tool schema from the callable, and Text ReAct prompts display that schema according to `text_tool_schema_mode`.

```python
import os
from typing import List, Optional

from ai_team_team import Tool

async def my_generator_handler(
    model_name: str,
    prompt: str,
    system_instruction: Optional[str] = None,
    tools: Optional[List[Tool]] = None,
    max_output_tokens: Optional[int] = None,
    temperature: float = 0.3,
    require_json: bool = False
) -> str:
    # Perform actual SDK completion call here
    return "Final Answer: Done"

manager.register_generator_handler(my_generator_handler)

# Restore only after the required runtime handler and client aliases are bound.
if os.path.exists("att_state.db"):
    await manager.load_state("att_state.db")

def search_knowledge_base(query: str, limit: int = 3) -> str:
    """Search the project knowledge base."""
    # Your search logic (e.g., VectorDB lookup)
    return "Search results..."

# Derive the name, description, and schema from the callable.
manager.register_tool(search_knowledge_base)

# Alternatively, provide an explicit public name and description.
# manager.register_tool(
#     name="search_kb",
#     description="Search the project knowledge base. Arguments: query (str), limit (int)",
#     func=search_knowledge_base,
# )
```

### Text ReAct Argument Syntax

ATT derives and validates each tool's parameter schema from its callable, while the description should still explain the operation's purpose and any important domain constraints.

Text ReAct actions use safe Python literal and keyword syntax:

- `Action: search_kb(query="Iris character profile", limit=3)`
- `Action: query_db(sql_command="SELECT * FROM characters")`

Malformed, truncated, ambiguous, or schema-invalid arguments are rejected without executing the tool.

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

## 🚀 5. Spawn Teams and Execute Discussions

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

# Use the detailed API when the host needs per-turn failure and audit metadata.
detailed = await manager.execute_team_discussion_detailed(
    team=team,
    prompt="Audit the schema details provided in file_schema.sql.",
    rounds=2,
)
print(detailed.status, detailed.rounds, detailed.audit)
```

## 📊 6. Connect Status Displays and Custom Logs

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

# Callbacks run on an ordered background dispatcher.
# Await this observation boundary when the host must know that all queued callbacks completed.
await manager.flush_callbacks()
```

## 🔗 7. Dynamic Team Migration and Topology Tree

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

## 🔗 8. Configure AgentTeam Communication

Every AgentTeam follows the single communication institution selected in `ATTConfig`, regardless of its topology depth, and the default `permissive` policy delivers authenticated peer messages without an Agreement.

Select an approval-governed institution when communication channels must be authorized:

```python
from ai_team_team import ATTConfig, ParentApprovalCommunicationConfig

config = ATTConfig(
    communication=ParentApprovalCommunicationConfig(
        request_delivery="queue",
        direction="bidirectional",
    )
)
```

Use `LineageApprovalCommunicationConfig(request_delivery="wake", direction="one_way")` instead when the recipient and the required topology lineage must approve a one-way channel.

The invoking Agent must be an active member of its current invocation-scoped AgentTeam, and communication tools never accept overrides for the sender, policy, direction, or approval principals.

- **Request a governed channel**: `Action: request_peer_communication(team_id="AT-xyz789", rationale="Coordinate the audit")`
- **Send a peer message**: `Action: send_peer_message(team_id="AT-xyz789", message="Verify the status of Iris")`
- **Revoke a channel**: `Action: revoke_peer_agreement(agreement_id="CA-123", reason="Coordination complete")`
- **Escalate to the parent**: `Action: delegate_escalation(objective="Failed to verify rule consistency", rationale="Depth limit reached")`

Under an approval policy, `send_peer_message` requires an active Agreement; under the permissive policy, it delivers directly without creating an implicit Agreement.

Parent escalations enter the parent AgentTeam's inbox and are summarized during its next active discussion.

## 🧰 9. Select Native or Text ReAct Tool Calling

ATT uses `tool_calling_mode="auto"` by default.

Auto mode selects Native Strategy only when the client's synchronous `supports_native_tool_calling()` probe returns the literal boolean `True`; probe errors, awaitables, and non-boolean values produce a system event and fall back to Text ReAct.

Provider adapters receive `List[Tool]` and are responsible for converting each `Tool.json_schema` into the provider SDK's format.

```python
# Force native structured tool calling without running the capability probe.
config.tool_calling_mode = "native"

# Record native capability for a manager-routed model.
manager.register_model("gpt-5.6-sol", {
    "supports_native_tool_calling": True,
})
```

## 🤖 10. Model Registry and Global Generator Callback

ATT features a unified model registry allowing dynamic teams to assign different members to different model configurations based on task complexity (e.g. using a fast model for basic tasks and a strong model for planning). All LLM requests are resolved through a centralized global generator callback handler.

### Registering Models & Callback Handlers

Instead of passing raw API keys or client instances directly to the framework, register your model configuration details and provide a single callback function to execute the generation requests:

```python
# 1. Register model configurations (metadata/descriptions for the AI)
manager.register_model("gemini-123", {
    "model_type": "llm",
    "model_name": "gemini-3.7-flash",
    "ai_note": "gemini-3.7-flash - A very impressive large model"
})

manager.register_model("openai-123", {
    "model_type": "llm",
    "model_name": "gpt-5.6-sol",
    "ai_note": "gpt-5.6-sol - A very impressive large model"
})

# 2. Register a single global callback handler to execute LLM calls
# The host application keeps full control of API Keys, endpoint routing, and SDKs.
async def my_generator_handler(
    model_name: str,
    prompt: str,
    system_instruction: Optional[str] = None,
    tools: Optional[List[Tool]] = None,
    max_output_tokens: Optional[int] = None,
    temperature: float = 0.3,
    require_json: bool = False
) -> str:
    # Look up the registered config to get the real model name
    config = manager.model_configs.get(model_name)
    real_name = config.get("model_name") if config else model_name

    if real_name == "gemini-3.7-flash":
        return await call_gemini_sdk(prompt, system_instruction, tools, max_output_tokens, temperature, require_json)
    elif real_name == "gpt-5.6-sol":
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

### Reusing an Existing Agent

Register a persistent Agent once, then invite the same identity to several AgentTeams. Ordinary host calls and Agent tools create a persistent formation request rather than adding an existing Agent immediately; only the Agent's explicit acceptance makes it eligible to join. Membership never rebinds or clears the shared Agent's role, instructions, model binding, memory, lifecycle state, invocation lock, Agent inbox, or Private DocLib; formation notifications are appended to the existing inbox independently.

```python
shared_client = MyLLMClient()
manager.register_llm_client("shared-agent", shared_client)
alice = manager.register_agent(Agent("Alice", "Researcher", shared_client))

formation_a = manager.create_agent_team(
    creator=root_agent,
    member_configs={
        "Planner": {"model": "openai-123"},
        "Reviewer": {"model": "gemini-123"},
    },
    existing_members=[alice],
)
await manager.respond_team_invitation(formation_a.request_id, actor=alice, proposal_revision=formation_a.proposal_revision, attitude="accepted")
created_a = await manager.create_team_from_formation(formation_a.request_id, actor=root_agent, proposal_revision=formation_a.proposal_revision)
team_a = manager.teams[created_a.team_id]

formation_b = manager.create_agent_team(
    creator=root_agent,
    member_configs={
        "Analyst": {"model": "openai-123"},
        "Writer": {"model": "gemini-123"},
    },
    existing_member_ids=[alice.agent_id],
)
await manager.respond_team_invitation(formation_b.request_id, actor=alice, proposal_revision=formation_b.proposal_revision, attitude="accepted")
created_b = await manager.create_team_from_formation(formation_b.request_id, actor=root_agent, proposal_revision=formation_b.proposal_revision)
team_b = manager.teams[created_b.team_id]

assert next(member for member in team_a.members if member.agent_id == alice.agent_id) is alice
assert next(member for member in team_b.members if member.agent_id == alice.agent_id) is alice
```

Consent always belongs to an exact proposal revision. If the initiator materially revises an open proposal with `await manager.revise_team_formation(..., base_revision=formation.proposal_revision, changes=TeamFormationRevisionPatch(...))`, every retained invitee returns to `no_response` and must review the new revision. For creator-Team collaboration before publication, use `discuss_team_formation_proposal()`, wait for the Agent inbox completion notification, inspect the detached draft, and explicitly call `publish_team_formation_draft()`; the advisory discussion never supplies invitee consent.

## 📂 11. Collaborative Document Library (DocLib)

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

### File Operations (Token-Based Context Protection)

Agent teams can use standard file operations:

- **Write file**: `Action: write_library_file(lib_id="DL-AT-abc123", path="/specs/guide.txt", content="New guide text")`
- **Read file by lines**: `Action: read_library_file(lib_id="DL-AT-abc123", path="/specs/guide.txt", start_line=1, end_line=50)`
- **Read a long line by characters**: `Action: read_library_file(lib_id="DL-AT-abc123", path="/data/minified.json", start_line=1, start_character=1, character_count=20000)`
- **List files**: `Action: list_library_files(lib_id="DL-AT-abc123", path="/")`
- **Delete file**: `Action: delete_library_file(lib_id="DL-AT-abc123", path="/specs/guide.txt")`
- **Create managed file link**: `Action: create_library_link(source_lib_id="DL-AT-xyz789", source_path="/references/guide.txt", target_lib_id="DL-AT-abc123", target_path="/specs/guide.txt")`

All `read_library_file` operations limit returned decoded content to `ATTConfig.file_read.max_read_tokens`, regardless of file size, line count, or requested range. A partial result supplies `next_line`, `next_character`, and `file_version`; pass those coordinates and the version as `expected_file_version` to continue without gaps. The small structured metadata and tool-protocol framing are outside the content budget.

Managed links work only between registered DocLib files. Creation requires `WRITE` on the source path and `READ` on the target. Reads and writes recheck the target ACL every time; writes require target `WRITE`, and deleting the link does not delete the target file. Native filesystem symlinks are rejected.

### Private Agent Workspace

Every AI registered with the manager also receives one persistent private DocLib.

A shared AI keeps the same private workspace in every AT, but no team, other AI, public listing, ACL grant, or managed link can access it.

Private files are not automatically included in model prompts or transcripts.

The current AI can deliberately use:

- `Action: write_private_file(path="notes/hypothesis.md", content="...")`
- `Action: read_private_file(path="notes/hypothesis.md", start_line=1, end_line=50)`
- `Action: list_private_files(path="/")`
- `Action: move_private_file(source_path="draft.md", target_path="final.md")`
- `Action: delete_private_file(path="obsolete.md")`
- `Action: publish_private_file(source_path="final.md", target_path="research/final.md")`

Publishing copies the file to the current team's built-in DocLib and keeps the private source. A collision is rejected unless `overwrite=True`, and the target path is always checked for current team `WRITE` permission.

An explicit private read is scoped to that single reasoning invocation. ATT redacts the observation from the AI's reusable model window when the invocation ends, preventing another team from receiving the private file body implicitly.

## 💾 12. Save and Close

Persistence APIs are asynchronous, and `flush_state()` waits for all accepted state changes before `close()` releases the writer and other manager resources:

```python
await manager.save_state("att_backup.db")
await manager.flush_state()
await manager.close()
```

Use `async with ATTManager(...) as manager` when possible so normal scope exit performs the final flush and close automatically.
