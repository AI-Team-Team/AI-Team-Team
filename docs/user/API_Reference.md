# Public API Reference

This document describes the public interface, parameters, and protocol conventions of the `ai-team-team` package. Only components intended for direct instantiation or external interaction are listed here.

## ⚙️ `ATTConfig`

Configuration class to configure the multi-agent framework settings.

### Constructor

```python
from ai_team_team import ATTConfig, EpisodicMemoryConfig, FileReadConfig, PermissiveCommunicationConfig

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
    file_read: FileReadConfig = FileReadConfig(),
    episodic_memory: EpisodicMemoryConfig = EpisodicMemoryConfig(),
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
* **`file_read`**: Strict `FileReadConfig`; `max_read_tokens` limits only returned decoded file content and `tokenizer_fallback` selects `"conservative"` or `"strict"` behavior when no exact effective-model counter is available.
* **`episodic_memory`**: Strict optional `EpisodicMemoryConfig`; `enabled=False` by default performs no indexing calls, creates no Memory Cards, exposes no memory tools, and does not require FTS5.
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

* **`launch_att(...) -> AgentTeam | TeamFormationRequest`**
  Launches an all-new child AgentTeam immediately, or opens a persistent consent workflow when the proposal names existing Agents or explicitly includes the initiator. Existing identities are not added until they accept; see [Consensual Existing-Agent Team Formation](../Consensual_Team_Formation.md).

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

* **`launch_att(...) -> AgentTeam | TeamFormationRequest`**
  Launches an all-new child AgentTeam immediately, or returns a formation request when existing Agents must consent. The initiating member is never added implicitly.
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

* **`register_tool(name: str, description: str, func: Callable[..., Any], schema: Optional[Any] = None, *, memory_capture: str = "metadata_only")`**
  Registers a custom utility tool globally and requires explicit `memory_capture="content"` before its observation body may enter episodic recall content.
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
* **`register_token_counter(model_alias: str, counter: Callable[[str], int | Awaitable[int]])`**
  Registers a runtime-only host token counter for one stable model alias. Provider clients may instead expose the optional `count_tokens(text)` contract.
* **`register_preset(name: str, description: str, system_instructions: str, roles: List[Tuple[str, str]])`**
  Registers a custom dynamic committee preset (e.g. roles and system prompt).
* **`register_tools_context(context: Dict[str, Any])`**
  Registers additional runtime resources and rebinds tools. `att_manager` is present automatically and cannot be overwritten.
* **`create_agent_team(...) -> AgentTeam | TeamFormationRequest`**
  Creates an all-new AgentTeam immediately when only new-Agent specifications are present. Supplying `existing_members`, `existing_member_ids`, or `initiator_joins=True` creates persistent invitations instead; only accepted Agents may enter the final membership, and joining changes no Agent-owned field.
* **`bootstrap_agent_team(creator, **kwargs) -> AgentTeam`**
  Performs explicitly trusted host topology initialization without interactive consent and emits a `trusted_team_bootstrap` audit event. This administrative API is never available to Agent tools and should not replace ordinary formation.
* **`inspect_team_formation(request_id, *, actor) -> TeamFormationInspection`**
  Returns the proposal, four public attitude counts, live eligible membership, `can_create`, and an eligibility reason.
* **`await respond_team_invitation(request_id, *, actor, attitude) -> FormationOperationResult`**
  Records an invited Agent's `accepted`, `declined`, or `explicitly_ignored` attitude. Choosing `None` deliberately withholds a public attitude and remains externally indistinguishable from an unprocessed invitation as `no_response`.
* **`await create_team_from_formation(request_id, *, actor) -> FormationOperationResult`**
  Lets only the initiating Agent commit the currently accepted eligible membership.
* **`await abandon_team_formation(request_id, *, actor, reason="") -> FormationOperationResult`**
  Terminates an uncreated proposal and notifies every invitee.
* **`list_agent_inbox(agent_id, *, unread_only=True) -> list[AgentInboxMessage]`** / **`await mark_agent_inbox_read(agent_id, message_ids=None) -> int`**
  Provides trusted-host access to persistent notifications owned by a stable Agent identity.

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
* **`await flush_memory_indexing()`**
  Waits for every currently runnable optional episodic-memory index job.
* **`await retry_memory_index(segment_id: str)`**
  Returns a pending or failed Agent-owned segment to the background indexing queue.
* **`list_memory_index_failures(agent_id: Optional[str] = None)`**
  Returns trusted-host diagnostics for failed index segments without exposing Journal access through Agent tools.
* **`await restore_forgotten_memory(agent_id: str, memory_id: str)`**
  Restores one forgotten Agent-owned Memory Card through the trusted host API.
* **`list_agent_history(agent_id: str)`**
  Returns the ordered host-only System Memory Journal view for one historical Agent identity.
* **`await close()`**
  Rejects new work, cancels outstanding external LLM waits and emergency tasks, flushes all accepted persistence changes without a timeout, and releases the exclusive database writer lease. `ATTManager` also supports `async with`.
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

# 4. Tool bodies are excluded from memory by default; explicit content capture is opt-in
tool = Tool(func=dummy_tool, memory_capture="content")
```

`memory_capture` accepts `"metadata_only"` or `"content"`; private and episodic-memory tools always use metadata-only capture.

Use `typing_extensions.TypedDict` for portable schemas across every supported Python version. Pydantic rejects `typing.TypedDict` on Python 3.11.

## 📁 `GatedFileReader`

Asynchronous token-bounded text reader for model-facing content. The budget applies only to decoded `content`; structured metadata and framework tool framing are excluded.

### Constructor

```python
from ai_team_team import GatedFileReader

reader = GatedFileReader(
    max_read_tokens=4000,
    tokenizer_fallback="conservative",
    token_counter=my_counter,
    model_alias="primary",
)
```

### Methods

* **`await read_file(path: str, start_line: int = 1, end_line: Optional[int] = None, start_character: int = 1, character_count: Optional[int] = None, expected_file_version: Optional[str] = None) -> FileReadResult`**
  Reads normalized UTF-8 content through line or character coordinates and returns the largest prefix within `max_read_tokens`. `end_line` and `character_count` are mutually exclusive. Partial results include the first unreturned position and a file version for safe continuation.

## 📁 `DocumentLibrary`

A persistent document store classified as either `team` or `agent_private`.

Applications normally access private libraries only through manager tools; the host process remains the trusted administrator.

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
* **`read_file(path: str, start_line: int = 1, end_line: Optional[int] = None, start_character: int = 1, character_count: Optional[int] = None) -> str`**
  Reads an unbounded normalized range for trusted host-side operations. Model-facing code should use manager or tool reads so the active Agent's token budget is enforced.
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

* **`dispatch_subagent(task: str, team_purpose: str, member_configs: Optional[dict] = None, existing_member_ids: Optional[List[str]] = None, system_instructions: str = "", is_public_visible: bool = False, initial_documents: Optional[dict] = None, initiator_joins: bool = False, unanimous_acceptance_action: str = "require_confirmation", late_join_policy: str = "disabled") -> str`**
  Creates and synchronously discusses an all-new child AgentTeam when no existing identity participates. If existing Agent IDs or initiator self-membership are requested, it returns `PENDING_RESPONSES` with a persistent formation request instead; no team or DocLib is created and the first discussion is deferred until after a successful formation commit.
* **`list_agent_inbox(unread_only: bool = True) -> str`** / **`mark_agent_inbox_read(message_ids: Optional[List[str]] = None) -> str`**
  Lists or acknowledges persistent notifications for the current invocation-scoped Agent identity.
* **`inspect_team_formation(request_id: str) -> str`** / **`respond_team_invitation(request_id: str, attitude: Optional[str] = None) -> str`**
  Inspects public attitude counts or lets the current invited Agent choose `accepted`, `declined`, `explicitly_ignored`, or `None`; `None` deliberately withholds a public attitude and appears as `NO_RESPONSE`.
* **`create_team_from_formation(request_id: str) -> str`** / **`abandon_team_formation(request_id: str, reason: str = "") -> str`**
  Lets the initiating Agent commit an eligible accepted subset or abandon the proposal.
* **`decide_team_formation_late_join(request_id: str, invitee_agent_id: str, approved: bool) -> str`**
  Resolves a consenting invitee's pending late join when the stored policy requires initiator confirmation.
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

### Selective Episodic Memory

These tools are visible only when `episodic_memory.enabled=True` and are always scoped to the current active Agent identity.

* **`search_memories(query: Optional[str] = None, tags: Optional[List[str]] = None, team_id: Optional[str] = None, discussion_id: Optional[str] = None, limit: int = 20, cursor: Optional[str] = None) -> MemorySearchResult`**
  Searches only the current Agent's active Memory Cards.
* **`recall_memory(memory_id: str, start_line: int = 1, end_line: Optional[int] = None, start_character: int = 1, character_count: Optional[int] = None, expected_segment_version: Optional[str] = None) -> MemoryRecallResult`**
  Returns a token-bounded historical observation. Partial results expose `next_line`, `next_character`, and `segment_version`; pass them into the next call to continue without gaps or duplication.
* **`keep_memory_in_context(memory_id: str, note: Optional[str] = None) -> MemoryOperationResult`**
  Retains a compact reference only after the card was recalled in the same Agent turn.
* **`forget_memory(memory_id: str, reason: Optional[str] = None) -> MemoryOperationResult`**
  Hides the Agent-owned card without modifying the immutable Journal or source Segment.

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
* **`read_library_file(lib_id: str, path: str, start_line: int = 1, end_line: Optional[int] = None, start_character: int = 1, character_count: Optional[int] = None, expected_file_version: Optional[str] = None) -> FileReadResult`**
  Reads a token-bounded normalized range after live AgentTeam membership, source ACL, managed-link, and target ACL checks. Partial results provide continuation coordinates and a file version.
* **`delete_library_file(lib_id: str, path: str) -> str`**
  Deletes a file or directory in a library (requires WRITE permission).
* **`list_library_files(lib_id: str, path: str = "/") -> str`**
  Lists contents under a library path (requires READ permission).
* **`move_library_file(lib_id: str, source_path: str, target_path: str, overwrite: bool = False) -> str`**
  Atomically moves a normal team-library file after live `WRITE` checks on both paths. Managed-link conflicts are rejected.

### Private Agent DocLib Actions

Private tools do not accept an Agent or library ID. They always use the current invocation identity, so a model cannot name another AI's private workspace.

* **`list_private_files(path: str = "/") -> str`**
* **`read_private_file(path: str, start_line: int = 1, end_line: Optional[int] = None, start_character: int = 1, character_count: Optional[int] = None, expected_file_version: Optional[str] = None) -> FileReadResult`**
* **`write_private_file(path: str, content: str) -> str`**
* **`delete_private_file(path: str) -> str`**
* **`move_private_file(source_path: str, target_path: str, overwrite: bool = False) -> str`**
* **`publish_private_file(source_path: str, target_path: str, overwrite: bool = False) -> str`** — copies an ordinary file to the current team's built-in DocLib. The default rejects collisions and `overwrite=True` still requires live target `WRITE` permission.
