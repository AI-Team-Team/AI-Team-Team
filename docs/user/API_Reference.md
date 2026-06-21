# Public API Reference

This document describes the public interface, parameters, and protocol conventions of the `ai-team-team` package. Only components intended for direct instantiation or external interaction are listed here.

## ⚙️ `ATTConfig`

Configuration class to configure the multi-agent framework settings.

### Constructor

```python
from ai_team_team import ATTConfig

config = ATTConfig(
    enable_dynamic_delegation: bool = True,
    max_delegation_depth: int = 2,
    min_subagent_team_size: int = 3,
    subagent_discussion_rounds: int = 2,
    react_max_steps: int = 5,
    inbox_summarize_threshold_chars: int = 1500,
    model_registry: Optional[dict] = None,
    max_migrations_per_team_discussion: int = 1,
    enable_membership_voting: bool = False,
    llm_max_retries: int = 3,
    llm_retry_backoff_factor: float = 1.5,
    enable_memory_compression: bool = True,
    max_memory_turns: int = 20,
    communication_policy: str = "permissive",
    migration_policy: str = "ancestor_approval",
    enable_emergency_wakeup: bool = True,
    emergency_discussion_rounds: int = 1,
    tool_calling_mode: str = "auto",
    max_tool_rounds: int = 5
)
```

### Parameters

* **`enable_dynamic_delegation`**: Whether to allow agents to spawn child sub-teams using the `dispatch_subagent` tool.
* **`max_delegation_depth`**: The maximum depth limit of recursive dynamic subagent spawning lineages.
* **`min_subagent_team_size`**: The minimum member count allowed when initiating a dynamic team panel (must be $\ge 3$).
* **`subagent_discussion_rounds`**: The number of debate rounds executed during child subagent panel calls.
* **`react_max_steps`**: The maximum reasoning steps capped per agent turn to prevent infinite ReAct loops.
* **`inbox_summarize_threshold_chars`**: The character threshold above which unread inbox alerts are automatically summarized.
* **`model_registry`**: Mapping of specialized agent roles to specific LLM models or endpoints.
* **`max_migrations_per_team_discussion`**: The maximum number of hierarchical team migrations allowed for a team during a single discussion session.
* **`enable_membership_voting`**: Whether to enable the democratic membership voting system for dynamic teams.
* **`llm_max_retries`**: The maximum retry attempts for LLM generation failures.
* **`llm_retry_backoff_factor`**: The exponential backoff factor for retrying LLM calls.
* **`enable_memory_compression`**: Whether to enable automatic dialogue compression/pruning of early conversation turns (default: `True`).
* **`max_memory_turns`**: The maximum number of conversation messages (turns) retained as high-fidelity context before summarizing older turns (default: `20`).
* **`communication_policy`**: The strategy used for inter-team communication gating. Options: `"permissive"`, `"rule_gated"`, `"proxied"`.
* **`migration_policy`**: The strategy used for dynamic lineage migration authorization. Options: `"permissive"`, `"ancestor_approval"`, `"lineage_path"`.
* **`enable_emergency_wakeup`**: Whether to trigger active wake-up discussion on idle parent teams upon receiving high-priority child anomalies (default: `True`).
* **`emergency_discussion_rounds`**: The number of emergency discussion rounds executed when a team is woken up (default: `1`).
* **`tool_calling_mode`**: The strategy used for tool calling and reasoning steps. Options: `"text_react"`, `"native"`, `"auto"` (default: `"auto"`).
* **`max_tool_rounds`**: The maximum reasoning loop steps allowed for the native strategy execution round (default: `5`).

## 👤 `Agent`

Represents an individual AI specialist equipped with role definitions.

### Constructor

```python
from ai_team_team import Agent

agent = Agent(name: str, role: str, llm_client: Optional[Any] = None, role_description: str = "", system_instructions: str = "")
```

### Methods

* **`launch_att(manager: ATTManager, member_count: int = 3, roles_and_presets: Optional[List[Tuple[str, str]]] = None, system_instructions: str = "", team_purpose: str = "Unspecified team purpose", roles_and_models: Optional[Dict[str, str]] = None, member_configs: Optional[Dict[str, Dict[str, Any]]] = None, is_public_visible: bool = False, initial_docs: Optional[Dict[str, str]] = None) -> AgentTeam`**
  Allows this agent to recursively launch a child dynamic `AgentTeam` structure, passing visibility and initial documents.

## 👥 `AgentTeam`

Represents a dynamic team of agents executing discussions and tasks in a parent-child lineage. External users obtain an `AgentTeam` instance when calling `ATTManager.create_agent_team` or `Agent.launch_att`.

### Properties

* **`team_id`**: `str` - The unique identifier of the team (e.g. `AT-abc123`).
* **`team_purpose`**: `str` - The global purpose/objective of this team.
* **`team_progress`**: `str` - The real-time status/progress of this team (default: `"Not started"`).
* **`depth`**: `int` - The depth level of the team in the lineage hierarchy (e.g., Level 1, Level 2).
* **`members`**: `List[Agent]` - The list of `Agent` instances assigned to this team.
* **`doc_library`**: `Optional[DocumentLibrary]` - Resolves the built-in document library for the team.
* **`parent_team`**: `Optional[AgentTeam]` - Resolves the parent team in the lineage hierarchy.
* **`child_teams`**: `List[AgentTeam]` - The list of active child teams spawned by this team.
* **`proposals`**: `Dict[str, Dict[str, Any]]` - Active membership voting proposals mapped by ID.
* **`status_map`**: `Dict[str, str]` - Dictionary mapping member names to their current statuses (e.g. `"Thinking..."`, `"Idle"`).

### Methods

* **`launch_att(manager: ATTManager, member_count: int = 3, roles_and_presets: Optional[List[Tuple[str, str]]] = None, system_instructions: str = "", team_purpose: str = "Unspecified team purpose", roles_and_models: Optional[Dict[str, str]] = None, member_configs: Optional[Dict[str, Dict[str, Any]]] = None, is_public_visible: bool = False, initial_docs: Optional[Dict[str, str]] = None) -> AgentTeam`**
  Allows this team to recursively spawn a child dynamic sub-team (Level $N+1$), propagating visibility and context docs to the subteam's DocLib.

## 🏛️ `ATTManager`

The master controller managing the overall agent team topology, tool registrations, presets, and callback events.

### Constructor

```python
from ai_team_team import ATTManager

manager = ATTManager(root_ai: Agent, config: Optional[ATTConfig] = None, db_path: Optional[str] = None)
```

### Methods

* **`register_tool(name: str, description: str, func: Callable[..., Any])`**
  Registers a custom utility tool globally to be automatically bound to all dynamic teams.
* **`register_tool_auditor(tool_name: str, auditor_func: Callable[..., Tuple[bool, str]])`**
  Registers an auditing hook executed before specific tool calls.
* **`register_model(name: str, config: Dict[str, Any])`**
  Registers a unified model configuration (e.g. metadata, type, ai_note).
* **`register_generator_handler(handler: Callable[..., str])`**
  Registers a global callback handler for generating text from a model alias.
* **`register_preset(name: str, description: str, system_instructions: str, roles: List[Tuple[str, str]])`**
  Registers a custom dynamic committee preset (e.g. roles and system prompt).
* **`register_tools_context(context: Dict[str, Any])`**
  Registers system resources context (databases, file readers) and automatically binds coordination tools to all teams.
* **`create_agent_team(creator: Any, member_count: int = 3, roles_and_presets: List[Tuple[str, str]] = None, preset_name: str = "custom", system_instructions: str = "", team_purpose: str = "Unspecified team purpose", roles_and_models: Optional[Dict[str, str]] = None, member_configs: Optional[Dict[str, Dict[str, Any]]] = None, is_public_visible: bool = False, initial_docs: Optional[Dict[str, str]] = None) -> AgentTeam`**
  Dynamically spawns a new recursive Agent Team (AT) with a parent-child relationship. `is_public_visible` sets library visibility for discovery, and `initial_docs` maps file paths to initial contents to populate in the team's DocLib.

* **`execute_team_discussion(team: AgentTeam, prompt: str, rounds: int = 2) -> str`**
  Executes a multi-agent debate session inside the AT, automatically injecting unresolved inbox alerts, and running supervisory transcript audits.
* **`render_topology_tree() -> str`**
  Renders the active hierarchical agent team lineage as an indented ASCII tree.
* **`negotiate_and_execute_migration(team: AgentTeam, target_parent: AgentTeam, rationale: str) -> Tuple[bool, str]`**
  Arbitrates the migration of an AgentTeam using the configured migration policy strategy (which defaults to requiring approvals from the Least Common Ancestor and parent team representatives using their own LLM clients), updates structure, and broadcasts alerts.
* **`save_state(db_path: Optional[str] = None)`**
  Serializes the entire manager configuration, registered agents, active team lineages, inboxes, proposals, broker agreements, and Document Library folders (with full directory structure and file contents) into a local SQLite database.
* **`load_state(db_path: str)`**
  Restores the entire manager topology, configs, agent histories, document libraries, inbox alerts, agreements, and proposals from a local SQLite database snapshot.

### Callbacks

* **`on_status_change: Optional[Callable[[str, str], None]]`**
  Invoked when an agent changes state (e.g. `"Thinking..."`, `"Executing Tool..."`, `"Idle"`).
* **`on_activity_added: Optional[Callable[[str, str, str], None]]`**
  Invoked when an agent records a ReAct event. Formatted as: `(agent_name, activity_type, content)`.
* **`on_log_append: Optional[Callable[[str, str, str, Optional[int]], None]]`**
  Invoked when detailed transcripts or execution logs are appended. Formatted as: `(team_id, title, content, chapter_num)`.
* **`on_team_migration: Optional[Callable[[str, Optional[str], str], None]]`**
  Invoked when a team successfully migrates to a new parent in the hierarchy. Formatted as: `(team_id, old_parent_id, new_parent_id)`.
* **`on_emergency_escalation: Optional[Callable[[str, str, str], None]]`**
  Invoked when a team receives a high-priority emergency alert (e.g. child failure or escalation). Formatted as: `(team_id, alert_type, alert_reason)`.

## 🛠️ `Tool`

Encapsulates an AI tool with name, description, execution logic, and automated schema parsing.

### Constructor

```python
from ai_team_team import Tool

# 1. Custom defined name, description and function
tool = Tool(name="weather", description="Query weather", func=dummy_tool)

# 2. Pythonic shortcuts (automatically derives name from func.__name__ and description from func.__doc__)
tool = Tool(dummy_tool)
tool = Tool(func=dummy_tool)

# 3. Explicit schema override (can be dict, Pydantic BaseModel, or TypedDict class)
tool = Tool(func=dummy_tool, schema=WeatherArgs)
```

## 📁 `GatedFileReader`

Size-aware paginated file reader protecting agent context windows.

### Constructor

```python
from ai_team_team import GatedFileReader

reader = GatedFileReader(large_threshold_kb: int = 50, max_chunk: int = 100)
```

### Methods

* **`read_file(path: str, start_line: int = 1, end_line: Optional[int] = None) -> str`**
  Reads a file. Fallbacks to Outline Warning if the file size exceeds `large_threshold_kb` and no `end_line` is provided. Otherwise, returns a line-numbered paginated chunk capped at `max_chunk` lines.
* **`read_file_tail(path: str, line_count: int = 50) -> str`**
  Returns the last `line_count` lines of a file with prepended line numbers.

## 📁 `DocumentLibrary`

A collaborative document storage library for Agent Teams, providing persistent directory structure and access controls.

### Constructor

```python
from ai_team_team import DocumentLibrary

lib = DocumentLibrary(
    lib_id: str, 
    name: str, 
    owner_team_id: str, 
    description: str = "", 
    is_public_visible: bool = False,
    root_dir: Optional[str] = None
)
```

### Properties

* **`lib_id`**: `str` - Unique ID of the library (e.g. `DL-AT-abc123`).
* **`name`**: `str` - Human readable name.
* **`owner_team_id`**: `str` - The ID of the owner AgentTeam.
* **`description`**: `str` - Summary of the library content.
* **`is_public_visible`**: `bool` - True if visible to other teams for discovery.

### Methods

* **`write_file(path: str, content: str)`**
  Writes content to a relative file path, creating parent directories as needed.
* **`read_file(path: str, start_line: int = 1, end_line: Optional[int] = None) -> str`**
  Reads a file, routing through the GatedFileReader for context window protection.
* **`delete_file(path: str) -> str`**
  Deletes a file or recursively deletes a directory.
* **`list_contents(path: str = "/") -> List[str]`**
  Lists relative file paths and directory paths under the target path.

## 🔍 `SupervisoryTeam`

A non-participating 3-AI committee (comprising Integrity, Continuity, and Deadlock Auditors) that automatically monitors dialogue logs for deadlocks and anomalies.

The Supervisory Team is managed and called automatically by `ATTManager` at the end of each debate session. External users do not typically interact with this class directly, but it coordinates dialogue health audits using the manager's `critic_client` or falls back to the manager's global `generator_handler` under the `"critic"` model alias.

* If a dialogue audit fails (`is_healthy = False`), the supervisor automatically executes the **Asynchronous Escalation Protocol**, routing anomaly warnings up to the parent team's inbox queue (or to the Level 0 Root AI if no parent exists).

## 🔌 `LLMClientProto`

Protocol definition for integration of custom LLM backends (adapters).

```python
from typing import Optional, Protocol

class LLMClientProto(Protocol):
    async def generate(
        self,
        prompt: Union[str, List[Dict[str, Any]]],
        system_instruction: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        require_json: bool = False
    ) -> LLMResponse:
        """
        Generates a text completion or returns structured tool calls.
        
        Args:
            prompt: The user query or discussion history (string or list of message dicts).
            system_instruction: Guidelines and context injected for the agent.
            tools: Optional list of structured tool schemas.
            temperature: Sampling temperature.
            require_json: If True, the model MUST return a valid JSON string.
        """
        ...

    def supports_native_tool_calling(self) -> bool:
        """
        Returns True if the client/model configuration natively supports structured function calling.
        """
        ...
```

## 🛠️ Built-in ReAct Tools Reference

These tools are automatically registered and bound to all agent teams by default. ReAct agents can invoke them using standard positional/keyword call syntax:

### Spawning & Communication

* **`dispatch_subagent(task: str, team_purpose: str, member_configs: Optional[dict] = None, system_instructions: str = "", allow_sibling_talk: bool = False, sibling_talk_rules: str = "", is_public_visible: bool = False, initial_documents: Optional[dict] = None) -> str`**
  Spawns a recursive child `AgentTeam` (Level $N+1$). Each team must contain at least 3 members. Optional context files can be pre-populated via `initial_documents` (maps file paths to contents).
* **`delegate_escalation(objective: str, rationale: str) -> str`**
  Escalates a task or deadlock upward to the team's direct parent in the lineage hierarchy.
* **`set_sibling_talk(child_id: str, allow: bool = True) -> str`**
  Allows a parent team to dynamically authorize sibling peer communication for a specific child team.
* **`send_peer_message(team_id: str, message: str) -> str`**
  Sends a direct message to a peer team's inbox, subject to communication policy gates.
* **`negotiate_peer_talk(target_team_id: str, rationale: str) -> str`**
  Requests parent representatives to negotiate a cross-lineage communication agreement tunnel.

### Team Status & Membership

* **`update_team_purpose(new_purpose: str) -> str`**
  Updates the purpose string of the caller's team.
* **`update_team_status(purpose: str, progress: str) -> str`**
  Updates both the purpose and progress strings of the caller's team.
* **`add_team_member(team_id: str, role_name: str, model_name: str, role_description: str, system_instructions: str) -> str`**
  Allows a parent team to administratively add a new member with custom configurations to a child team.
* **`remove_team_member(team_id: str, agent_name: str) -> str`**
  Allows a parent team to administratively remove a member from a child team, enforcing the minimum size of 3.

### Democratic Membership Voting

* **`initiate_membership_vote(action: str, target: str, rationale: str, initiator_type: str = "individual", proposed_details: Optional[dict] = None) -> str`**
  Initiates a democratic proposal to `"add"` or `"remove"` a member. Requires unanimous participation of current members to resolve.
* **`cast_vote(proposal_id: str, vote: str, public: bool = True, rationale: str = "") -> str`**
  Casts a ballot (`"Agree"`, `"Disagree"`, or `"Abstain"`). Setting `public=False` enforces anonymity.
* **`retract_membership_vote(proposal_id: str) -> str`**
  Withdraws an active proposal. Only the initiator can retract.

### Reorganization

* **`request_migration(target_parent_id: str, rationale: str) -> str`**
  Requests to migrate the caller's team to a new parent in the hierarchy, audited by the configured `migration_policy`.

### Document Library (DocLib) File Actions

* **`create_doc_library(name: str, description: str, is_public: bool = False) -> str`**
  Creates a new document library owned by the caller's team.
* **`update_library_metadata(lib_id: str, description: Optional[str] = None, is_public: Optional[bool] = None) -> str`**
  Updates description or visibility of a library owned by the caller's team.
* **`list_public_libraries() -> str`**
  Lists all document libraries registered as publicly visible.
* **`grant_library_permission(lib_id: str, path: str, target_team_id: str, permission: str) -> str`**
  Grants access (`"READ"` or `"WRITE"`) to a target team for a path segment in the library.
* **`revoke_library_permission(lib_id: str, path: str, target_team_id: str) -> str`**
  Revokes permissions for a target team under a path.
* **`write_library_file(lib_id: str, path: str, content: str) -> str`**
  Writes content to a file in a library (requires WRITE permission).
* **`read_library_file(lib_id: str, path: str, start_line: int = 1, end_line: Optional[int] = None) -> str`**
  Reads a file segment from a library (requires READ permission, checks file-gating).
* **`delete_library_file(lib_id: str, path: str) -> str`**
  Deletes a file or directory in a library (requires WRITE permission).
* **`list_library_files(lib_id: str, path: str = "/") -> str`**
  Lists contents under a library path (requires READ permission).
