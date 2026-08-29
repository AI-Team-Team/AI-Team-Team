# Developer API Reference

This document provides a technical overview of the internal classes, properties, and coordination interfaces in the `ai-team-team` package for framework developers and contributors.

> [!NOTE]
> If you are an external developer integrating the library into your own application, please consult the [Public API Reference](../user/API_Reference.md) instead.

## Core Classes

### `Agent`

Represents an individual AI specialist equipped with role definitions and generator client integration.

One instance may be shared across teams. Its `lock` serializes complete model turns, `message_history` retains complete cross-team provenance, and manager `ContextVar` values provide the active team and discussion.

* **Constructor**:

  ```python
  agent = Agent(name: str, role: str, llm_client: Optional[Any] = None, role_description: str = "", system_instructions: str = "", agent_id: Optional[str] = None)
  ```

* **Methods**:
  * `launch_att(manager: ATTManager, member_count: int = 3, roles_and_presets: Optional[List[Tuple[str, str]]] = None, system_instructions: str = "", team_purpose: str = "Unspecified team purpose", roles_and_models: Optional[Dict[str, str]] = None, member_configs: Optional[Dict[str, Dict[str, Any]]] = None) -> AgentTeam`
        Allows any active agent to recursively launch their own child dynamic `AgentTeam` structure.

`agent_id` is an immutable canonical UUID. `_private_doc_library_id` and `_model_alias` are manager-owned persistence fields; public code reads only `private_doc_library_id`.

### `AgentTeam`

Represents a dynamic team of at least 3 agents ($N \ge 3$) executing discussions, debates, and tasks.

* **Constructor**:

  ```python
  team = AgentTeam(creator: Any, preset_name: str, team_purpose: str = "Unspecified team purpose")
  ```

* **Properties**:
  * `parent_team -> Optional[AgentTeam]`: Resolves the parent team in the lineage tree.
  * `depth -> int`: Returns memoized lineage depth. A migration recursively invalidates this cache for the moved team and every descendant.
  * `state_lock -> asyncio.Lock`: Asynchronous mutex safeguarding proposal structural mutations during parallel Native tool executions.
* **Methods**:
  * `launch_att(...) -> AgentTeam`: Allows the active team to recursively spawn a child team.
  * `receive_message(message: Dict[str, Any])`: Appends incoming signals or parent alerts to the team's inbox queue.
  * `execute_reasoning_step(agent: Agent, prompt: str, system_instruction: str, max_steps: int = 5, manager: Optional[ATTManager] = None) -> str`
        Routes the reasoning step to Native or Text ReAct and returns a completed answer or stable incomplete placeholder.
  * `execute_reasoning_step_detailed(...) -> AgentTurnResult`
        Returns structured provenance, completion state, privacy-safe failure metadata, and `ToolFailureSummary` values. Native calls remain concurrent, but a failed parallel batch consumes at most one argument-correction opportunity.
  * `execute_react_step(agent: Agent, prompt: str, system_instruction: str, max_steps: int = 5, manager: Optional[ATTManager] = None) -> str`
        Text-compatible convenience wrapper around `execute_reasoning_step`.

### `ATTManager`

Master orchestrator managing the overall ATT topology, dynamic presets, tool registrations, and callback events.

Synchronous and asynchronous callbacks share one ordered background dispatcher; callback failures are logged and never alter core transaction outcomes.

* **Constructor**:

  ```python
  manager = ATTManager(root_ai: Agent, config: Optional[ATTConfig] = None, db_path: Optional[str] = None)
  ```

* **Methods**:
  * `register_model(name: str, config: Dict[str, Any])`
    Registers model metadata and optionally a `client=` runtime binding.
  * `register_llm_client(alias: str, client: Any)`
    Registers one stable alias for one direct client identity.
  * `register_generator_handler(handler: Callable[..., str])`
    Registers a global callback handler for generating text from a model alias.
  * `register_agent(agent: Agent) -> Agent`
    Installs one stable identity in the ID registry and active name index and creates exactly one canonical private library.
  * `get_private_library_id(agent_id: str) -> str`
    Resolves private ownership without exposing a raw private-library capability on `Agent`.
  * `await retire_agent(...)` / `await reactivate_agent(...)`
    Applies strict retain/archive/delete lifecycle rules and explicit model rebinding.
  * `register_preset(name: str, description: str, system_instructions: str, roles: List[Tuple[str, str]])`
    Registers custom dynamic committee presets.
  * `get_preset(name: str) -> dict`
    Retrieves a registered preset or defaults to `generic`.
  * `register_tool(name: str, description: str, func: Callable[..., Any])`
    Registers a custom tool globally to be automatically bound to all dynamic teams.
  * `register_tool_auditor(tool_name: str, auditor_func: Callable[..., Tuple[bool, str]])`
    Registers an auditing hook callback that intercepts specific tool calls before execution.
  * `register_tools_context(context: Dict[str, Any])`
    Registers additional runtime resources and rebinds coordination tools. The reserved `att_manager` reference is installed automatically and cannot be overwritten.
  * `create_agent_team(...) -> AgentTeam`
    Validates inputs before mutation, stages new identities and DocLibs outside their final paths, atomically publishes files and topology under the mutation lock, and rolls back all runtime and filesystem state on failure.
  * `suppress_auto_save() -> AsyncContextManager`
    Nested, task-local batching context that merges dirty deltas and submits one write when the outer scope exits.
  * `await execute_team_discussion(team: AgentTeam, prompt: str, rounds: int = 2) -> str`
    Executes a multi-agent debate session under the team's serial session lock. Normal and emergency sessions share the lock; separate teams remain concurrent.
  * `await execute_team_discussion_detailed(...) -> DiscussionResult`
    Returns per-round turns, transcript, dual-axis audit, and `COMPLETED` or `PARTIAL`. Isolated member failures do not cancel peers or prevent the member from rejoining the next round.
  * `find_parent_team(target: AgentTeam) -> Optional[AgentTeam]`
    Locates the parent team in the active team topology using child references and creator pointers.
  * `check_library_access(team_id: str, lib_id: str, path: str, required_permission: str) -> bool`
    Evaluates if a team is granted `READ` or `WRITE` access to a Document Library path based on prefix segments.
  * `list_private_files`, `read_private_file`, `write_private_file`, `delete_private_file`, `move_private_file`, `publish_private_file`
    Resolve ownership only from `_active_tool_agent`; private operations never accept caller-supplied owner or library identifiers.
  * `move_library_file(...)`
    Atomically moves a normal library file after checking both path ACLs.
  * `render_topology_tree() -> str`
    Renders the active lineage tree map in ASCII format.
  * `negotiate_and_execute_migration(team: AgentTeam, target_parent: AgentTeam, rationale: str) -> Tuple[bool, str]`
    Arbitrates dynamic team reorganizations and updates parental references.
  * `await save_state(path: Optional[str] = None, full: bool = True)`
    Queues and waits for a full snapshot, or a configuration delta when `full=False`.
  * `await load_state(path: str)`
    Stages and validates every persisted reference, model binding, topology edge, DocLib file, ACL, and managed link before atomically publishing the restored runtime.
  * `await flush_state()`
    Waits for all queued incremental commits.
  * `await close()`
    Rejects new work, cancels external LLM waits, flushes accepted writes, and
    closes the single writer lease, engines, and sessions.
  * `await flush_callbacks()`
    Waits for the ordered observational callback queue.
  * `acknowledge_unknown_alert(...)` / `clear_unknown_alerts(...)`
    Explicitly acknowledges durable, fingerprinted UNKNOWN audit alerts.

### `ATTConfig`

Configuration options for tuning the ATT multi-agent framework.

`ATTConfig` is a strict Pydantic model with forbidden extra fields and assignment validation. Runtime updates to scalar fields and supported mutable configuration mappings are validated by the same rules used during construction.

* **Constructor**:

  ```python
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

### `NegotiationBroker`

Owns durable communication requests, approvals, ballots, Agreements, and peer-delivery records. It reads policy only from `ATTConfig` and accepts already authenticated runtime actors from the tool boundary.

* `request_peer_communication(sender, recipient, initiated_by_agent_id, rationale) -> CommunicationOperationResult`
      Returns `APPROVED`, `ALREADY_ACTIVE`, or `PENDING_APPROVAL`. Approval policies create an immutable request snapshot and schedule explicit principals outside the caller's tool stack.
* `send_peer_message(sender, recipient, initiated_by_agent_id, content, invocation_id=None) -> CommunicationOperationResult`
      Commits one idempotent delivery or returns `NO_AGREEMENT`.
* `revoke_agreement(agreement_id, actor_team_id, reason) -> CommunicationOperationResult`
      Enforces endpoint-only revocation.
* `approval_path(sender, recipient, policy=None) -> List[ApprovalPrincipal]`
      Resolves ordered `agent_team` and Root `agent` principals without selecting an Agent to act for a team.

### `TeamDecisionProvider`

Executes governance decisions for explicit principals. AgentTeam decisions use the team's discussion lock and a complete frozen-member ballot; Agent decisions use only that Agent's invocation lock. Strict Pydantic JSON parsing accepts only literal booleans or a valid model alias from the supplied candidate set.

### `SupervisoryTeam`

A 3-AI supervisory committee checking transcripts for logical deadlocks, circular reasoning, and dialogue health.

* **Methods**:
  * `audit_team_dialog(team: AgentTeam, transcript: str) -> AuditResult`
    Returns independent content and runtime health. `AuditResult.status` is `HEALTHY`, `UNHEALTHY`, or `UNKNOWN`; `operational_status` is `HEALTHY`, `DEGRADED`, or `UNKNOWN` and follows the configured framework/supervisor authority mode.
  * `report_anomaly(failed_team: AgentTeam, reason: str, manager: ATTManager)`
    Escalates failure alerts recursively up ancestors or directly to the Level 0 Root AI.

### `Tool` and `ToolExecutor`

`Tool` owns the provider-neutral callable contract, validated JSON Schema, prompt rendering metadata, examples, and `retry_safe` declaration. Automatic schemas support `Annotated`, `Literal`, Enum, Pydantic models, `TypedDict`, containers, unions, and nesting. Portable `TypedDict` annotations across Python 3.10–3.13 must come from `typing_extensions`; incompatible standard-library definitions fail during tool registration with an actionable error. Registration validates handwritten schemas against Draft 2020-12.

`ToolExecutor.execute()` is shared by Text and Native strategies. It binds the invocation signature, applies strict Pydantic JSON validation, validates the original argument object against the generated or handwritten Draft 2020-12 schema, runs the auditor and callable under Agent/AgentTeam ContextVars, and returns `ToolResult` with a structured status, error kind, and attempt count. It recognizes typed `ToolArgumentError`, `ToolPermissionError`, `ToolBusinessError`, and `RetryableToolError`; custom result strings are never classified by prefix.

Native provider interfaces receive `Optional[List[Tool]]`. The provider adapter converts `Tool.json_schema` into its SDK's concrete function-calling shape and converts responses back to `LLMResponse` and `ToolCall`.

### `GatedFileReader`

Size-aware paginated file reader protecting agent context windows.

* **Constructor**:

  ```python
  reader = GatedFileReader(large_threshold_kb: int = 50, max_chunk: int = 100)
  ```

* **Methods**:
  * `read_file(path: str, start_line: int = 1, end_line: Optional[int] = None) -> str`
    Reads a file. Fallbacks to Outline Warning if the file size exceeds threshold and no line window is provided.
  * `read_file_tail(path: str, line_count: int = 50) -> str`
    Returns the last line_count lines of a file with prepended line numbers.

### `DocumentLibrary`

Represents a `team` or `agent_private` document store with path traversal protection. Team libraries use prefix ACLs. Private libraries reject ACLs, public visibility, and managed links at manager boundaries.

* **Constructor**:

  ```python
  lib = DocumentLibrary(lib_id: str, name: str, owner_team_id: str, description: str = "", is_public_visible: bool = False, root_dir: Optional[str] = None)
  ```

* **Properties**:
  * `root_dir -> str`: Absolute path to the persistent workspace folder (.att_doc_libs/<lib_id>).
* **Methods**:
  * `write_file(path: str, content: str)`
  * `read_file(path: str, start_line: int, end_line: Optional[int]) -> str`
  * `delete_file(path: str) -> str`
  * `list_contents(path: str) -> List[str]`
  * `move_file(source_path: str, target_path: str, overwrite: bool = False)`
  * `write_file_atomic(path: str, content: str, overwrite: bool = False)`

Native filesystem symlinks are rejected. Cross-library links are manager-owned metadata exposed through `create_library_link`; direct `DocumentLibrary` methods operate on physical files only.

## Policies & Strategy Interfaces

Migration strategies are defined in [`policies.py`](../../src/ai_team_team/core/policies.py). Communication is not a per-call strategy interface: its strict Pydantic configuration is consumed by `NegotiationBroker`.

### Migration Policies

* **`BaseMigrationPolicy`**: Base protocol defining `authorize_migration(team, target_parent, manager, rationale) -> Tuple[bool, str]`.
* **`PermissiveMigrationPolicy`**: Always returns `(True, "Allowed")`.
* **`AncestorApprovalMigrationPolicy`**: Consults explicit current-parent, target-parent, and Least Common Ancestor principals (default strategy).
* **`LineagePathMigrationPolicy`**: Traverses every explicit AgentTeam/Root Agent principal along the affected lineage path.

## Database Schema & ORM Models

SQLAlchemy Declarative Models mapping schema 6 are defined in [`models.py`](../../src/ai_team_team/database/models.py):

* **`ManagerConfigModel`**: Key-value stores for serialized configuration payloads and Root AI targets.
* **`AgentModel` & `AgentMessageModel`**: Uses immutable `agent_id` primary/foreign keys and persists lifecycle profiles plus complete conversation histories with `team_id` and `discussion_id` provenance.
* **`TeamModel`**: Tracks active topologies, migration counts, and UUID-backed creator/member references.
* **`TeamInboxModel` & `TeamProposalModel`**: Persists child escalations, peer messages, and democratic proposal votes.
* **`CommunicationRequestModel`, `CommunicationApprovalModel`, `CommunicationBallotModel`**: Persist the request lifecycle, ordered explicit principals, and member ballots.
* **`CommunicationAgreementModel` & `PeerMessageModel`**: Persist directional endpoint channels, revocation state, and idempotent delivery lifecycle.
* **`LibraryModel` & `LibraryPermissionModel` & `DocLibFileModel` & `DocLibLinkModel`**: Persists library kind, mutually exclusive team/agent ownership, lifecycle, ACL segments, physical document contents, and managed team-library link targets.

### Database Session Factory

* **`get_session(db_path: str) -> Generator[Session, None, None]`**
  A strict standalone writer context defined in `database/session.py`. It acquires the same exclusive writer lease, performs schema preflight before DDL, enables the configured SQLite safeguards, and yields a transactional SQLAlchemy session. Foreign-key enforcement cannot be disabled.
