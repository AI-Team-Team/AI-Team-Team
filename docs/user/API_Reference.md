# Public API Reference

This document describes the public interface, parameters, and protocol conventions of the `ai-team-team` package. Only components intended for direct instantiation or external interaction are listed here.

## ⚙️ `ATTConfig`

Configuration class to configure the multi-agent framework settings.

### Constructor

```python
from ai_team_team import ATTConfig, PermissiveCommunicationConfig

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
    communication: CommunicationConfig = PermissiveCommunicationConfig(),
    migration_policy: str = "ancestor_approval",
    enable_emergency_wakeup: bool = True,
    emergency_discussion_rounds: int = 1,
    tool_calling_mode: str = "auto",
    max_tool_rounds: int = 5,
    max_tool_argument_retries: int = 3,
    max_tool_execution_retries: int = 2,
    tool_execution_retry_policy: str = "never",
    tool_execution_retry_backoff_factor: float = 0.5,
    text_tool_schema_mode: str = "compact",
    tool_prompt_modes: Optional[dict] = None,
    turn_failure_policy: TurnFailurePolicyConfig = TurnFailurePolicyConfig(),
    operational_status_decision_mode: str = "framework",
    operational_degraded_escalation_mode: str = "none",
    model_token_limits: Optional[dict] = None,
    model_max_output_tokens: Optional[dict] = None,
    default_max_output_tokens: int = 1024,
    audit_unknown_escalation_mode: str = "wake",
    audit_unknown_soft_threshold: int = 100,
    agent_private_data_policy: str = "archive",
    parent_failover_timeout_seconds: float = 120
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
* **`llm_max_retries`**: Retries after the initial attempt. `0` means one attempt and no retry.
* **`llm_retry_backoff_factor`**: Initial exponential-backoff delay. `0` retries immediately.
* **`enable_memory_compression`**: Whether to enable automatic dialogue compression/pruning of early conversation turns (default: `True`).
* **`max_memory_turns`**: The maximum number of conversation messages (turns) retained as high-fidelity context before summarizing older turns (default: `20`).
* **`communication`**: Strict `PermissiveCommunicationConfig`, `ParentApprovalCommunicationConfig`, or `LineageApprovalCommunicationConfig`. Approval configurations select `request_delivery` (`"queue"`/`"wake"`) and Agreement `direction` (`"one_way"`/`"bidirectional"`). The institution applies to every AgentTeam depth.
* **`migration_policy`**: The strategy used for dynamic lineage migration authorization. Options: `"permissive"`, `"ancestor_approval"`, `"lineage_path"`.
* **`enable_emergency_wakeup`**: Whether to trigger active wake-up discussion on idle parent teams upon receiving high-priority child anomalies (default: `True`).
* **`emergency_discussion_rounds`**: The number of emergency discussion rounds executed when a team is woken up (default: `1`).
* **`tool_calling_mode`**: The strategy used for tool calling and reasoning steps. Options: `"text_react"`, `"native"`, `"auto"` (default: `"auto"`).
* **`max_tool_rounds`**: The maximum reasoning loop steps allowed for the native strategy execution round (default: `5`).
* **`max_tool_argument_retries`**: Model correction opportunities after the first unknown-tool, parse, signature, or input-validation failure. A Native parallel batch consumes at most one opportunity.
* **`max_tool_execution_retries`**: Additional attempts for eligible `RetryableToolError` failures.
* **`tool_execution_retry_policy`**: Execution replay policy: `"never"`, `"retry_safe"`, or `"typed_transient"`.
* **`tool_execution_retry_backoff_factor`**: Initial exponential delay for eligible execution retries. `0` retries immediately.
* **`text_tool_schema_mode`**: Text prompt rendering mode: `"compact"`, `"full"`, or `"compact_with_examples"`.
* **`tool_prompt_modes`**: Per-tool prompt rendering overrides.
* **`turn_failure_policy`**: Strict `TurnFailurePolicyConfig` with independent `tool` and `llm` values of `"isolate"` or `"abort"`; both default to `"isolate"`.
* **`operational_status_decision_mode`**: Runtime-health authority: `"framework"`, `"supervisor"`, or `"framework_then_supervisor"`.
* **`operational_degraded_escalation_mode`**: Degraded runtime handling: `"none"`, `"queue"`, or `"wake"`.
* **`model_token_limits`**: Hard per-model token quotas. Active reservations and settled usage both consume availability; `0` disables the model quota.
* **`model_max_output_tokens`**: Optional per-model maximum output reservations and request caps. Clients governed by a hard quota must accept `max_output_tokens` or `max_tokens`; unsupported clients fail before dispatch.
* **`default_max_output_tokens`**: Default maximum output reservation when a model-specific value is absent (default: `1024`).
* **`audit_unknown_escalation_mode`**: Whether an indeterminate supervisory audit immediately wakes the parent (`"wake"`) or only enters its inbox (`"queue"`).
* **`audit_unknown_soft_threshold`**: Emits operational warnings after this many unique UNKNOWN alerts without dropping or expiring them.
* **`agent_private_data_policy`**: Default retirement handling for private data: `"archive"` (read-only), `"retain"`, or confirmed `"delete"`.
* **`parent_failover_timeout_seconds`**: Positive timeout for explicit parent AgentTeam/Root Agent model selection. Parent-governed failover never falls back to `"auto"`.

Policy names, numeric values, runtime assignments, and mutable configuration mapping updates use the same validation. Invalid values raise `ValueError`.

## 👤 `Agent`

Represents an individual AI specialist equipped with role definitions.

The same `Agent` object may belong to several teams. It keeps one continuous history, serializes its own model calls, and receives the current team through invocation-scoped context. Team-sensitive APIs raise `AmbiguousTeamContextError` when no context exists and membership is ambiguous.

### Constructor

```python
from ai_team_team import Agent

agent = Agent(name: str, role: str, llm_client: Optional[Any] = None, role_description: str = "", system_instructions: str = "", agent_id: Optional[str] = None)
```

`agent_id` is a manager-persisted canonical UUID and is normally generated by `Agent`. `private_doc_library_id` exposes the assigned private library ID without exposing a raw `DocumentLibrary` capability.

### Methods

* **`launch_att(manager: ATTManager, member_count: int = 3, roles_and_presets: Optional[List[Tuple[str, str]]] = None, system_instructions: str = "", team_purpose: str = "Unspecified team purpose", roles_and_models: Optional[Dict[str, str]] = None, member_configs: Optional[Dict[str, Dict[str, Any]]] = None, existing_members: Optional[List[Agent]] = None, existing_member_ids: Optional[List[str]] = None, is_public_visible: bool = False, initial_docs: Optional[Dict[str, str]] = None) -> AgentTeam`**
  Allows this agent to recursively launch a child dynamic `AgentTeam`, create new members from `member_configs`, and add already registered Agents through the role-neutral `existing_members` or `existing_member_ids` inputs.

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

* **`launch_att(manager: ATTManager, member_count: int = 3, roles_and_presets: Optional[List[Tuple[str, str]]] = None, system_instructions: str = "", team_purpose: str = "Unspecified team purpose", roles_and_models: Optional[Dict[str, str]] = None, member_configs: Optional[Dict[str, Dict[str, Any]]] = None, existing_members: Optional[List[Agent]] = None, existing_member_ids: Optional[List[str]] = None, is_public_visible: bool = False, initial_docs: Optional[Dict[str, str]] = None) -> AgentTeam`**
  Allows this team to recursively spawn a child dynamic sub-team (Level $N+1$), create new members, reuse existing registered Agent identities, and propagate visibility and context documents to the subteam's DocLib.
* **`await execute_reasoning_step(...) -> str`**
  Returns the completed answer, or a stable `[Turn incomplete: ...]` placeholder when the configured isolate policy contains a member-scoped failure.
* **`await execute_reasoning_step_detailed(...) -> AgentTurnResult`**
  Returns Agent/team/discussion provenance, completion status, answer or privacy-safe failure metadata, and structured tool failure summaries.

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
* **`register_agent(agent: Agent) -> Agent`**
  Registers one stable identity and creates its unique private DocLib. Direct mutation of `manager.agents` is unsupported.
* **`get_private_library_id(agent_id: str) -> str`**
  Returns the canonical `PDL-<agent_id>` ID.
* **`await retire_agent(agent_id: str, policy: Optional[str] = None, confirm_delete: bool = False)`**
  Deactivates an unused AI under `retain`, `archive`, or confirmed `delete`. Root, team members, team creators, agents with an active model call, and identities referenced by durable governance/audit records cannot be permanently deleted.
* **`await reactivate_agent(agent_id: str, model_alias: str) -> Agent`**
  Restores a retained or archived AI with an explicit stable runtime model binding and its original private library.
* **`register_tool_auditor(tool_name: str, auditor_func: Callable[..., Tuple[bool, str]])`**
  Registers an auditing hook executed before specific tool calls.
* **`register_model(name: str, config: Dict[str, Any])`**
  Registers model metadata. An optional `client=` argument also registers the runtime binding.
* **`register_llm_client(alias: str, client: Any)`**
  Registers one stable, unique alias for a direct client. Required before persisting any agent that uses the client.
* **`register_generator_handler(handler: Callable[..., str])`**
  Registers a global callback handler for generating text from a model alias.
* **`register_preset(name: str, description: str, system_instructions: str, roles: List[Tuple[str, str]])`**
  Registers a custom dynamic committee preset (e.g. roles and system prompt).
* **`register_tools_context(context: Dict[str, Any])`**
  Registers additional runtime resources and rebinds tools. `att_manager` is present automatically and cannot be overwritten.
* **`create_agent_team(creator: Any, member_count: int = 3, roles_and_presets: List[Tuple[str, str]] = None, preset_name: str = "custom", system_instructions: str = "", team_purpose: str = "Unspecified team purpose", roles_and_models: Optional[Dict[str, str]] = None, member_configs: Optional[Dict[str, Dict[str, Any]]] = None, existing_members: Optional[List[Agent]] = None, existing_member_ids: Optional[List[str]] = None, is_public_visible: bool = False, initial_docs: Optional[Dict[str, str]] = None) -> AgentTeam`**
  Dynamically spawns a recursive AgentTeam. `member_configs` creates new Agent identities, while `existing_members` and `existing_member_ids` add active registered identities without changing their names, roles, instructions, model bindings, memories, lifecycle state, or Private DocLibs. The combined explicit membership must satisfy the configured minimum size, duplicate identities are rejected, `is_public_visible` controls team-library discovery, and `initial_docs` populates that library.

* **`await execute_team_discussion(team: AgentTeam, prompt: str, rounds: int = 2) -> str`**
  Executes a multi-agent debate session inside the AT, automatically injecting unresolved inbox alerts, and running supervisory transcript audits. Sessions for the same team, including emergency sessions, wait on one serial lock; different teams may run concurrently.
* **`await execute_team_discussion_detailed(team: AgentTeam, prompt: str, rounds: int = 2, skip_audit: bool = False) -> DiscussionResult`**
  Returns the structured discussion ID, `COMPLETED` or `PARTIAL` status, transcript, per-round `AgentTurnResult` values, and dual-axis `AuditResult`.
* **`render_topology_tree() -> str`**
  Renders the active hierarchical agent team lineage as an indented ASCII tree.
* **`negotiate_and_execute_migration(team: AgentTeam, target_parent: AgentTeam, rationale: str) -> Tuple[bool, str]`**
  Arbitrates migration through explicit AgentTeam and Root Agent principals, revalidates the topology under its mutation lock, updates structure atomically, and broadcasts alerts.
* **`await save_state(path: Optional[str] = None, full: bool = True)`**
  Queues and waits for a versioned snapshot commit.
* **`await load_state(path: str)`**
  Transactionally restores a fully validated staged registry after runtime clients or a generator handler have been rebound. Missing or corrupt references raise `StateRestoreError` without changing the live manager or its DocLib files.
* **`await flush_state()`**
  Waits for all queued incremental writes.
* **`await close()`**
  Rejects new work, cancels outstanding external LLM waits and emergency tasks,
  flushes all accepted persistence changes without a timeout, and releases the
  exclusive database writer lease. `ATTManager` also supports `async with`.
* **`await flush_callbacks()`**
  Waits for all observational callbacks queued so far.
* **`acknowledge_unknown_alert(team_id: str, fingerprint: str) -> bool`**
  Explicitly acknowledges and removes one durable UNKNOWN alert.
* **`clear_unknown_alerts(team_id: str, fingerprints: Optional[set[str]] = None) -> int`**
  Explicitly removes selected or all UNKNOWN alerts for one team.

### Callbacks

Callbacks may be synchronous or asynchronous. ATT dispatches them in order on a background channel; slow callbacks do not block discussions, and callback exceptions are logged without changing core outcomes.

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
from typing_extensions import NotRequired, TypedDict

class WeatherArgs(TypedDict):
    city: str
    units: NotRequired[str]

# 1. Custom defined name, description and function
tool = Tool(name="weather", description="Query weather", func=dummy_tool)

# 2. Pythonic shortcuts (automatically derives name from func.__name__ and description from func.__doc__)
tool = Tool(dummy_tool)
tool = Tool(func=dummy_tool)

# 3. Explicit schema override (can be dict, Pydantic BaseModel, or TypedDict class)
tool = Tool(func=dummy_tool, schema=WeatherArgs)
```

Use `typing_extensions.TypedDict` for portable schemas across every supported Python version. Pydantic rejects `typing.TypedDict` on Python 3.11.

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

A persistent document store classified as either `team` or `agent_private`.
Applications normally access private libraries only through manager tools; the
host process remains the trusted administrator.

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
* **`owner_agent_id`**: `Optional[str]` - Set only for an agent-private library.
* **`library_kind`**: `str` - Either `team` or `agent_private`.
* **`lifecycle_state`**: `str` - `active`, `retained`, or `archived`.
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

* Audits separate content health (`AuditStatus.HEALTHY`, `UNHEALTHY`, or `UNKNOWN`) from runtime health (`OperationalStatus.HEALTHY`, `DEGRADED`, or `UNKNOWN`). Confirmed content anomalies preserve emergency escalation. UNKNOWN audits use `audit_unknown_escalation_mode`; degraded runtime alerts emit structured events and optionally queue or wake through `operational_degraded_escalation_mode`.

## 🔌 `LLMClientProto`

Protocol definition for integration of custom LLM backends (adapters).

```python
from typing import Optional, Protocol
from ai_team_team import Tool

class LLMClientProto(Protocol):
    async def generate(
        self,
        prompt: Union[str, List[Dict[str, Any]]],
        system_instruction: Optional[str] = None,
        tools: Optional[List[Tool]] = None,
        max_output_tokens: Optional[int] = None,
        temperature: float = 0.7,
        require_json: bool = False
    ) -> LLMResponse:
        """
        Generates a text completion or returns structured tool calls.
        
        Args:
            prompt: The user query or discussion history (string or list of message dicts).
            system_instruction: Guidelines and context injected for the agent.
            tools: Optional list of native `Tool` objects (Thorough Abstraction) to be resolved by the adapter.
            max_output_tokens: Required enforced response cap when this model has a hard quota.
            temperature: Sampling temperature.
            require_json: If True, the model MUST return a valid JSON string.
        """
        ...

    def supports_native_tool_calling(self) -> bool:
        """
        Returns the literal boolean True only when the client supports native structured function calling. Auto mode treats probe exceptions, awaitables, and non-boolean values as Text ReAct fallback.
        """
        ...

    def supports_output_token_limit(self) -> Union[bool, str]:
        """Returns max_output_tokens/max_tokens support for hard quotas."""
        ...
```

## 🛠️ Built-in ReAct Tools Reference

These tools are automatically registered and bound to all agent teams by default. ReAct agents can invoke them using standard positional/keyword call syntax:

### Spawning & Communication

* **`dispatch_subagent(task: str, team_purpose: str, member_configs: Optional[dict] = None, existing_member_ids: Optional[List[str]] = None, system_instructions: str = "", is_public_visible: bool = False, initial_documents: Optional[dict] = None) -> str`**
  Spawns a recursive child `AgentTeam` (Level $N+1$). `member_configs` creates new Agents and `existing_member_ids` adds active registered Agents without assigning team-specific roles; their combined count must satisfy the configured minimum. Optional context files can be pre-populated via `initial_documents`.
* **`delegate_escalation(objective: str, rationale: str) -> str`**
  Escalates a task or deadlock upward to the team's direct parent in the lineage hierarchy.
* **`send_peer_message(team_id: str, message: str) -> str`**
  Durably sends from the invocation-scoped AgentTeam. It returns stable JSON with `DELIVERED` or `NO_AGREEMENT`.
* **`request_peer_communication(team_id: str, rationale: str) -> str`**
  Requests a durable Agreement under the configured parent- or lineage-approval policy. It accepts no sender, policy, direction, or principal override.
* **`revoke_peer_agreement(agreement_id: str, reason: str) -> str`**
  Revokes a channel when the current invocation-scoped AgentTeam is either endpoint.
* **`list_peer_requests(status: str = "pending") -> str`**
  Lists requests involving the current endpoint or approval AgentTeam.
* **`list_peer_agreements(active_only: bool = True) -> str`**
  Lists Agreements whose endpoints include the current AgentTeam.

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
* **`create_library_link(source_lib_id: str, source_path: str, target_lib_id: str, target_path: str) -> str`**
  Creates a file-only managed link between registered DocLibs. Creation requires source `WRITE` and target `READ`; each later operation rechecks the target ACL.
* **`write_library_file(lib_id: str, path: str, content: str) -> str`**
  Writes content to a file in a library (requires WRITE permission).
* **`read_library_file(lib_id: str, path: str, start_line: int = 1, end_line: Optional[int] = None) -> str`**
  Reads a file segment from a library (requires READ permission, checks file-gating).
* **`delete_library_file(lib_id: str, path: str) -> str`**
  Deletes a file or directory in a library (requires WRITE permission).
* **`list_library_files(lib_id: str, path: str = "/") -> str`**
  Lists contents under a library path (requires READ permission).
* **`move_library_file(lib_id: str, source_path: str, target_path: str, overwrite: bool = False) -> str`**
  Atomically moves a normal team-library file after live `WRITE` checks on both paths. Managed-link conflicts are rejected.

### Private Agent DocLib Actions

Private tools do not accept an Agent or library ID. They always use the current invocation identity, so a model cannot name another AI's private workspace.

* **`list_private_files(path: str = "/") -> str`**
* **`read_private_file(path: str, start_line: int = 1, end_line: Optional[int] = None) -> str`**
* **`write_private_file(path: str, content: str) -> str`**
* **`delete_private_file(path: str) -> str`**
* **`move_private_file(source_path: str, target_path: str, overwrite: bool = False) -> str`**
* **`publish_private_file(source_path: str, target_path: str, overwrite: bool = False) -> str`** — copies an ordinary file to the current team's built-in DocLib. The default rejects collisions and `overwrite=True` still requires live target `WRITE` permission.
