# Quickstart Guide

Welcome to **AI-Team-Team (ATT)**!
This guide will help you integrate ATT into your project, define custom tools, configure LLM client adapters, and run continuing personal activity within explicit organizations.

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

## A Complete Offline Example

Save the following as `personal_activity.py`, or run `./venv/bin/python examples/personal_activity.py` from the repository after installation.

It uses a scripted provider to demonstrate public contracts without network access or API keys; it does not perform business reasoning.

The Agent returns an ordinary answer and then explicitly chooses idle through the appropriate tool protocol.

The example closes its first writer before reopening the same database and verifies the same persistent Agent UUID with a reconstructed Python object.

Run with `--text` to exercise Text ReAct; the default exercises Native tools.

Temporary workspaces keep this complete example from writing `.att_doc_libs` into the current project.

<!-- runnable: examples/personal_activity.py -->

```python
"""Run a deterministic personal interaction and restore the same identity offline."""

import argparse
import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any

from ai_team_team import ATTConfig, ATTManager, Agent, LLMResponse, Tool, ToolCall


class DemoClient:
    """A scripted provider for contract examples, not a business reasoning model."""

    def __init__(self, native: bool = True, *, answer: bool = True):
        self.native = native
        self.answer = answer
        self.calls = 0

    def supports_native_tool_calling(self) -> bool:
        return self.native

    def supports_output_token_limit(self) -> bool:
        return True

    async def generate(
        self,
        prompt: str | list[dict[str, Any]],
        system_instruction: str | None = None,
        tools: list[Tool] | None = None,
        max_output_tokens: int | None = None,
        temperature: float = 0.7,
        require_json: bool = False,
    ) -> LLMResponse:
        self.calls += 1
        if require_json:
            raise ValueError("This demo does not provide optional memory-indexing responses.")
        if self.answer and self.calls == 1:
            return LLMResponse(text="Final Answer: The demo received its instruction.")
        if self.native:
            return LLMResponse(tool_calls=[
                ToolCall(f"idle-{self.calls}", "set_activity_intent", {"intent": {"kind": "idle"}})
            ])
        return LLMResponse(text="Action: set_activity_intent(intent={'kind': 'idle'})")


async def run_demo(workspace: Path, *, native: bool = True) -> dict[str, Any]:
    workspace.mkdir(parents=True, exist_ok=True)
    state = workspace / "personal.sqlite"
    client = DemoClient(native)
    config = ATTConfig(workspace_root=str(workspace), tool_calling_mode="auto")
    root = Agent("Root", "Coordinator", client)
    async with ATTManager(root, config, db_path=str(state)) as manager:
        manager.register_llm_client("demo", client)
        admission = await manager.activate_agent(root.agent_id)
        checkpoint = await manager.wait_for_activity_checkpoint(admission.admission_id, intent="idle")
        owner_id = root.agent_id
        await manager.save_state()

    restored_client = DemoClient(native, answer=False)
    async with ATTManager(
        Agent("RestoreHost", "Coordinator", restored_client),
        ATTConfig(workspace_root=str(workspace)),
        db_path=str(state),
    ) as manager:
        manager.register_llm_client("demo", restored_client)
        await manager.load_state(str(state))
        current_root = manager.root_ai
        assert current_root.agent_id == owner_id
        assert current_root is not root
        assert manager.inspect_agent_activity(owner_id).intent == "idle"
        assert restored_client.calls == 0
    return {"intent": checkpoint.intent, "model_calls": client.calls,
            "same_identity_restored": True, "durability": admission.durability}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text", action="store_true", help="Use Text ReAct instead of Native tools.")
    options = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="att-personal-example-") as directory:
        result = asyncio.run(run_demo(Path(directory), native=not options.text))
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
```

Expected summary: `intent="idle"`, `model_calls=2`, `same_identity_restored=true`, and `durability="durable"`.

The following sections are integration fragments that assume their named clients, SDK functions, manager, and asynchronous application context exist.

## ⚙️ 2. Configure ATT and Create the Manager

Create the Root Agent and `ATTManager` after selecting the framework-wide policies that every AgentTeam will follow:

```python
from ai_team_team import ATTManager, Agent, ATTConfig, EpisodicMemoryConfig

config = ATTConfig(
    workspace_root="att_workspace",
    enable_dynamic_delegation=True,
    max_delegation_depth=2,
    min_subagent_team_size=3,
    working_context_message_limit=20,
    enable_memory_compression=True,
    episodic_memory=EpisodicMemoryConfig(enabled=False),  # Optional advanced mode
    failover_policy="auto",
    tool_calling_mode="auto",
    audit_unknown_escalation_mode="wake",  # Or "queue"
    agent_private_data_policy="archive",  # Or "retain" / "delete"
)

# Define your provider adapter as described in the next section first.
root_client = MyLLMClient()
root_agent = Agent(name="Root_AI", role="Architect", llm_client=root_client)
manager = ATTManager(root_ai=root_agent, config=config, db_path="att_state.db")
manager.register_llm_client("root-model", root_client)
```

Durable persistence is the default and requires an explicit `db_path`, with asynchronous incremental saving of accepted state changes.

For an intentionally non-recoverable session, use `ATTManager(root_ai=root_agent, config=config, persistence_mode="volatile")` without a database path.

Register the runtime model bindings described below before loading persisted state, because callables and external connections are intentionally not serialized.

Registering a generator handler does not attach it to an existing Root whose client is `None`.

Bind the Root explicitly and register its stable alias before saving or admitting personal work.

### Stable Client and Agent Registration

A direct client object must have one stable identity binding before related state can be saved, and its `model_name` attribute is accepted as an alias only when the same client object is registered under that name:

```python
analysis_client = MyLLMClient()
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

ATT is backend-agnostic.
To connect your LLM provider (e.g., Google GenAI, OpenAI, Anthropic, or a local model), you must provide a client class that implements the `LLMClientProto` protocol.

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
        Generates text or provider-neutral structured tool calls.
        
        Args:
            prompt: The current person's prepared context as text or message dictionaries.
            system_instruction: Guidelines and context injected for the agent.
            tools: Optional provider-neutral `Tool` instances to convert into the provider's schema.
            max_output_tokens: Required provider output ceiling when a hard token quota is configured.
            temperature: Sampling temperature.
            require_json: If True, return valid JSON for explicitly requested structured maintenance.
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

When `require_json=True`, return valid JSON for that maintenance contract, such as optional memory indexing.

Governance ballots and audit findings use explicit tools in the person's runtime; an ordinary JSON answer is not a public choice.

## 🛠️ 4. Register Custom Tools and Presets

You can extend agents' capabilities by registering custom tools and committees.

### Defining Tools

When registering a custom tool, provide precise type hints and a concise description.

ATT generates and validates the tool schema from the callable, and Text ReAct prompts display that schema according to `text_tool_schema_mode`.

```python
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
    return "Action: set_activity_intent(intent={'kind': 'idle'})"

manager.register_generator_handler(my_generator_handler)

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

- `Action: search_knowledge_base(query="Iris character profile", limit=3)`
- `Action: query_db(sql_command="SELECT * FROM characters")`

Malformed, truncated, ambiguous, or schema-invalid arguments are rejected without executing the tool.

### Tool Interception Auditing

You can register an auditing callback to check specific tool arguments before execution for safety, logging, or approval:

```python
def audit_search(query: str, limit: int = 3) -> tuple[bool, str]:
    if len(query) < 3:
        return False, "Query is too short"
    return True, "Approved"

manager.register_tool_auditor("search_knowledge_base", audit_search)
```

### Registering AgentTeam Presets

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

## 🚀 5. Create Organizations and Address a Person

Creation provenance and organizational parent are separate.

The default `parent=None` creates an independent AgentTeam; pass an Agent or AgentTeam explicitly when that parent is intended.

```python
team = manager.create_agent_team(
    creator=root_agent,
    parent=None,
    member_count=3,
    preset_name="reviewers",
    team_purpose="Review the database schema.",
)

# The Host explicitly selects this person, not a framework-appointed leader.
reviewer = team.members[0]
result = await manager.execute_agent_interaction(
    reviewer,
    "Review file_schema.sql and deliberately publish relevant findings if appropriate.",
    team=team,
)
print(result.answer)
print(result.agent_id, result.team_id, result.invocation_id)
```

The result observes that person's answer, not a team transcript or a task-completion certificate.

An ordinary answer does not stop activity or send a message.

Agents deliberately use `send_team_message`, `send_direct_message`, or `send_peer_message` to publish content, and `set_activity_intent` to choose idle or finite sleep.

Use `await manager.activate_agent(agent_id, scope=...)` when only admission is needed; its receipt is distinct from a later `wait_for_activity_checkpoint(..., intent="idle")` observation.

Concurrent inputs for the same active person coalesce, and changing a requested Host scope does not silently replace that person's current active scope.

## 📊 6. Observe Metadata Events

Synchronous and asynchronous observers run on an ordered background dispatcher.

Private bodies, raw model context, and tool arguments are not included in system-event metadata.

```python
def system_event(event_name: str, details: dict):
    print(event_name, details)

manager.on_system_event = system_event
await manager.flush_callbacks()
```

Observer delay or failure cannot become authority or interrupt core activity.

## 🔗 7. Explicit Organization Changes

The Host can inspect the current forest without inserting a global directory into model prompts:

```python
print(manager.render_topology_tree())
# Organizational forest
# - Independent AgentTeams
#   - AT-abc123 (Purpose: Review | Progress: Not started) [Depth 1]
```

An AgentTeam may request an explicit Agent or AgentTeam parent, or voluntary independence.

New attachment requires the prospective parent's explicit acceptance even under permissive migration policy.

```python
request = await manager.negotiate_and_execute_migration(
    team, intended_parent, "Coordinate under this explicitly chosen parent.",
)
print(request.status, request.request_id)
# Inspect the retained request later; PENDING is not a completed migration.
```

Successful own-position changes have a persisted ten-minute cooldown.

Forced detachment after an actual parent retires or dissolves preserves direct surviving children and does not count as their own migration.

Observe `migration_request_resolved` and related metadata through `on_system_event`, not a separate migration or emergency callback.

## 🔗 8. Configure AgentTeam Communication

Every AgentTeam follows the single communication institution selected in `ATTConfig`, regardless of its topology depth, and the default `permissive` policy delivers authenticated peer messages without an Agreement.

Select an approval-governed institution when communication channels must be authorized:

```python
from ai_team_team import ParentApprovalCommunicationConfig

manager.config.communication = ParentApprovalCommunicationConfig(
    request_delivery="queue",
    direction="bidirectional",
)
```

Assign to the existing manager's validated configuration when changing a running deployment; constructing an unrelated `ATTConfig` does not update that manager.

Pending requests retain their captured policy, and existing Agreements remain valid until explicitly revoked.

Use `LineageApprovalCommunicationConfig(request_delivery="queue", direction="one_way")` when the recipient and applicable real lineage must approve a one-way channel.

Communication approval supports voluntary queue delivery only; `wake` is rejected pending a separate design.

Independent-to-independent communication is permissive without a Request or Agreement, while mixed pairs retain the attached endpoint's required authority.

The invoking Agent must be an active member of its current invocation-scoped AgentTeam, and communication tools never accept overrides for the sender, policy, direction, or approval principals.

- **Request a governed channel**: `Action: request_peer_communication(team_id="AT-xyz789", rationale="Coordinate the audit")`
- **Send a peer message**: `Action: send_peer_message(team_id="AT-xyz789", message="Verify the status of Iris")`
- **Revoke a channel**: `Action: revoke_peer_agreement(agreement_id="CA-123", reason="Coordination complete")`
- **Escalate to the parent**: `Action: delegate_escalation(objective="Failed to verify rule consistency", rationale="Depth limit reached")`

Under an approval policy, `send_peer_message` requires an active Agreement; under the permissive policy, it delivers directly without creating an implicit Agreement.

Escalation to an actual parent AgentTeam uses the same configured peer-communication gate; it cannot bypass an absent Agreement or create a nested parent execution.

## 🧰 9. Select Native or Text ReAct Tool Calling

ATT uses `tool_calling_mode="auto"` by default.

Auto mode selects Native Strategy only when the manager receives the literal boolean `True` from the client's synchronous `supports_native_tool_calling()` probe.

Probe errors, awaitables, and non-boolean outcomes received by the manager produce a system event and fall back to Text ReAct.

Generator-handler wrappers currently pre-normalize inner probe outcomes and can conceal that diagnostic or use a configured capability after an exception; see the [documented limitation](../Tool_System.md#2-one-runtime-with-two-provider-protocols).

Provider adapters receive `List[Tool]` and are responsible for converting each `Tool.json_schema` into the provider SDK's format.

```python
# Force native structured tool calling without running the capability probe.
manager.config.tool_calling_mode = "native"

# Record native capability for a manager-routed model.
manager.register_model("handler-native", {
    "supports_native_tool_calling": True,
})
```

Force Native mode only after the selected adapter or handler converts its SDK response into actual `ToolCall` objects.

An `Action: ...` string is Text ReAct output and is not a Native tool call.

The complete offline example exercises both formats with matching capability declarations.

## 🤖 10. Model Registry and Global Generator Callback

ATT features a unified model registry allowing new Agent identities to select registered model configurations at creation.

Requests use the Agent's bound client, which may be a directly registered client or an adapter backed by the global generator handler.

### Registering Models & Callback Handlers

For the generator-handler integration, register model configuration details and provide a callback that owns provider credentials and SDK routing:

```python
# 1. Register model configurations (metadata/descriptions for the AI)
manager.register_model("handler-writing", {
    "model_type": "llm",
    "model_name": "writing-backend",
    "ai_note": "Host-configured route for drafting tasks."
})

manager.register_model("handler-analysis", {
    "model_type": "llm",
    "model_name": "analysis-backend",
    "ai_note": "Host-configured route for analytical tasks."
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
    # The Host supplies these SDK integration functions and output normalization.
    if model_name == "default":
        return await call_default_sdk(prompt, system_instruction, tools, max_output_tokens, require_json)
    registered = manager.model_configs[model_name]
    real_name = registered["model_name"]
    if real_name == "writing-backend":
        return await call_writing_sdk(prompt, system_instruction, tools, max_output_tokens, temperature, require_json)
    if real_name == "analysis-backend":
        return await call_analysis_sdk(prompt, system_instruction, tools, max_output_tokens, temperature, require_json)
    raise ValueError(f"No provider route is configured for {model_name!r}.")

manager.register_generator_handler(my_generator_handler)
```

### Assigning Models to Agents

You can route different agents to different registered model names when spawning a team using the `roles_and_models` mapping:

```python
# Select stable handler aliases for new Agents.
team = manager.create_agent_team(
    creator=root_agent,
    member_count=3,
    preset_name="generic",
    roles_and_models={
        "Specialist_A": "handler-analysis",
        "Specialist_B": "handler-writing"
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
            "model": "handler-analysis",
            "role_description": "Designs outline and schedules work",
            "system_instructions": "Focus on clarity and conciseness"
        },
        "Writer": {
            "model": "handler-writing",
            "role_description": "Drafts the report sections",
            "system_instructions": "Use rich descriptors and clean prose"
        },
        "Reviewer": {
            "model": "handler-writing",
            "role_description": "Checks logic and style consistency",
            "system_instructions": "Be strict on formatting rules"
        }
    }
)
```

### Reusing an Existing Agent

Register a persistent Agent once, then invite the same identity to several AgentTeams.
Ordinary host calls and Agent tools create a persistent formation request rather than adding an existing Agent immediately; only the Agent's explicit acceptance makes it eligible to join.
Membership never rebinds or clears the shared Agent's role, instructions, model binding, memory, lifecycle state, invocation lock, Agent inbox, or Private DocLib; formation notifications are appended to the existing inbox independently.

```python
shared_client = MyLLMClient()
manager.register_llm_client("shared-agent", shared_client)
alice = manager.register_agent(Agent("Alice", "Researcher", shared_client))

formation_a = manager.create_agent_team(
    creator=root_agent,
    member_configs={
        "Planner": {"model": "handler-analysis"},
        "Reviewer": {"model": "handler-writing"},
    },
    existing_members=[alice],
)
await manager.respond_team_invitation(formation_a.request_id, actor=alice, proposal_revision=formation_a.proposal_revision, attitude="accepted")
created_a = await manager.create_team_from_formation(formation_a.request_id, actor=root_agent, proposal_revision=formation_a.proposal_revision)
team_a = manager.teams[created_a.team_id]

formation_b = manager.create_agent_team(
    creator=root_agent,
    member_configs={
        "Analyst": {"model": "handler-analysis"},
        "Writer": {"model": "handler-writing"},
    },
    existing_member_ids=[alice.agent_id],
)
await manager.respond_team_invitation(formation_b.request_id, actor=alice, proposal_revision=formation_b.proposal_revision, attitude="accepted")
created_b = await manager.create_team_from_formation(formation_b.request_id, actor=root_agent, proposal_revision=formation_b.proposal_revision)
team_b = manager.teams[created_b.team_id]

assert next(member for member in team_a.members if member.agent_id == alice.agent_id) is alice
assert next(member for member in team_b.members if member.agent_id == alice.agent_id) is alice
```

Consent always belongs to an exact proposal revision.
If the initiator materially revises an open proposal with `await manager.revise_team_formation(..., base_revision=formation.proposal_revision, changes=TeamFormationRevisionPatch(...))`, every retained invitee returns to `no_response` and must review the new revision.
The initiator may publish its design directly or call optional `prepare_team_formation_draft(objective, candidate, request_id=None)` and then explicitly publish the ready artifact.

Candidate preparation invokes no other person, imposes no all-member barrier, and never supplies invitee consent.

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

By default, a team's DocLib is private and only accessible by its own members.
To share a document or folder, the owner team can grant permissions:

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

All `read_library_file` operations limit returned decoded content to `ATTConfig.file_read.max_read_tokens`, regardless of file size, line count, or requested range.
A partial result supplies `next_line`, `next_character`, and `file_version`; pass those coordinates and the version as `expected_file_version` to continue without gaps.
The small structured metadata and tool-protocol framing are outside the content budget.

Managed links work only between registered DocLib files.
Creation requires `WRITE` on the source path and `READ` on the target.
Reads and writes recheck the target ACL every time; writes require target `WRITE`, and deleting the link does not delete the target file.
Native filesystem symlinks are rejected.

### Private Agent Workspace

Every AI registered with the manager also receives one persistent private DocLib.

A shared AI keeps the same private workspace in every AT, but no team, other AI, public listing, ACL grant, or managed link can access it.

Private files are not automatically included in model prompts or shared conversations.

The current AI can deliberately use:

- `Action: write_private_file(path="notes/hypothesis.md", content="...")`
- `Action: read_private_file(path="notes/hypothesis.md", start_line=1, end_line=50)`
- `Action: list_private_files(path="/")`
- `Action: move_private_file(source_path="draft.md", target_path="final.md")`
- `Action: delete_private_file(path="obsolete.md")`
- `Action: publish_private_file(source_path="final.md", target_path="research/final.md")`

Publishing copies the file to the current team's built-in DocLib and keeps the private source.
A collision is rejected unless `overwrite=True`, and the target path is always checked for current team `WRITE` permission.

An explicit private read is scoped to that single reasoning invocation.
ATT redacts the observation from the AI's reusable model window when the invocation ends, preventing another team from receiving the private file body implicitly.

## 💾 12. Save and Close

Persistence APIs are asynchronous, and `flush_state()` waits for all accepted state changes before `close()` releases the writer and other manager resources:

```python
await manager.save_state()
await manager.flush_state()
await manager.close()
```

Use `async with ATTManager(...) as manager` when possible so normal scope exit performs the final flush and close automatically.

Passing another path to `save_state(path)` exports a snapshot without changing the current writer's `db_path`.

### Restore in a New Application Lifetime

Close the previous writer before opening its database, then bind every direct-client alias and any handler required by the checkpoint before calling `load_state()`.

This fragment binds the direct aliases introduced above; adapt that list to the actual checkpoint rather than substituting another alias for a missing binding.

```python
root_client = MyLLMClient()
manager = ATTManager(
    Agent("RestoreHost", "Coordinator", root_client),
    ATTConfig(workspace_root="att_workspace"),
    db_path="att_state.db",
)
manager.register_llm_client("root-model", root_client)
manager.register_llm_client("analysis", MyLLMClient())
manager.register_llm_client("shared-agent", MyLLMClient())
manager.register_generator_handler(my_generator_handler)
await manager.load_state("att_state.db")
root_agent = manager.root_ai
config = manager.config
```

The persisted Agent UUID and personal state remain the same, while successful restore replaces Python runtime objects.

Reacquire the current Root, configuration, and other active Agents by saved IDs from `manager.agents.values()` before using them again.

Runtime tools, auditors, counters, and observers also need their Host bindings restored; interrupted people may become eligible immediately after publication.

Continue with [Personal Activity](../Personal_Activity.md), [Personal Conversations](../Personal_Conversations.md), and [Background Tasks](../Background_Tasks.md) for current runtime behavior and exact authority boundaries.
