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
  agent = Agent(name: str, role: str, llm_client: Optional[Any] = None, role_description: str = "", system_instructions: str = "")
  ```

* **Methods**:
  * `launch_att(manager: ATTManager, member_count: int = 3, roles_and_presets: Optional[List[Tuple[str, str]]] = None, system_instructions: str = "", team_purpose: str = "Unspecified team purpose", roles_and_models: Optional[Dict[str, str]] = None, member_configs: Optional[Dict[str, Dict[str, Any]]] = None) -> AgentTeam`
        Allows any active agent to recursively launch their own child dynamic `AgentTeam` structure.

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
        Routes reasoning step to either Native structured tool calling strategy or classic Text ReAct strategy. Executes concurrent/parallel tool calls when in Native mode.
  * `execute_react_step(agent: Agent, prompt: str, system_instruction: str, max_steps: int = 5, manager: Optional[ATTManager] = None) -> str`
        Alias wrapper around `execute_reasoning_step` preserved for backward compatibility.

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
    Spawns a new team of size $N \ge 3$, establishes parent-child lineages, and binds generic/custom tools.
  * `suppress_auto_save() -> AsyncContextManager`
    Nested, task-local batching context that merges dirty deltas and submits one write when the outer scope exits.
  * `await execute_team_discussion(team: AgentTeam, prompt: str, rounds: int = 2) -> str`
    Executes a multi-agent debate session under the team's serial session lock. Normal and emergency sessions share the lock; separate teams remain concurrent.
  * `find_parent_team(target: AgentTeam) -> Optional[AgentTeam]`
    Locates the parent team in the active team topology using child references and creator pointers.
  * `check_library_access(team_id: str, lib_id: str, path: str, required_permission: str) -> bool`
    Evaluates if a team is granted `READ` or `WRITE` access to a Document Library path based on prefix segments.
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
      communication_policy: str = "permissive",
      migration_policy: str = "ancestor_approval",
      enable_emergency_wakeup: bool = True,
      emergency_discussion_rounds: int = 1,
      max_tool_retries: int = 3,
      model_token_limits: Optional[dict] = None,
      model_max_output_tokens: Optional[dict] = None,
      default_max_output_tokens: int = 1024,
      audit_unknown_escalation_mode: str = "wake",
      audit_unknown_soft_threshold: int = 100
  )
  ```

### `NegotiationBroker`

Coordinates sibling and cross-lineage communication permissions.

* `negotiate_communication(sender: AgentTeam, recipient: AgentTeam, mode: str = "proxied") -> bool`
      Directly returns `True` if communication_policy is `"permissive"`. Otherwise, checks sibling rules on common parents or checks for active peer agreements.
* `establish_peer_agreement(sender: AgentTeam, recipient: AgentTeam, rationale: str, mode: Optional[str] = None) -> bool`
      Validates cross-lineage communication according to the specified communication policy (or config default). Valid policies: `"permissive"`, `"rule_gated"`, `"proxied"`. Allow `None` parents representing Root AI.

### `SupervisoryTeam`

A 3-AI supervisory committee checking transcripts for logical deadlocks, circular reasoning, and dialogue health.

* **Methods**:
  * `audit_team_dialog(team: AgentTeam, transcript: str) -> AuditResult`
    Returns `HEALTHY`, `UNHEALTHY`, or `UNKNOWN` with a reason and optional operational cause.
  * `report_anomaly(failed_team: AgentTeam, reason: str, manager: ATTManager)`
    Escalates failure alerts recursively up ancestors or directly to the Level 0 Root AI.

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

Represents a team's document database with prefix-based permissions and path traversal protection.

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

Native filesystem symlinks are rejected. Cross-library links are manager-owned metadata exposed through `create_library_link`; direct `DocumentLibrary` methods operate on physical files only.

## Policies & Strategy Interfaces

 Pluggable strategies governing communication and migrations defined in [policies.py](file:///Users/charlestsaur/Documents/sandbox/AI-Team-Team/src/ai_team_team/core/policies.py):

### Communication Policies

* **`BaseCommunicationPolicy`**: Base protocol defining `authorize_peer_talk(sender, recipient, manager, rationale) -> bool`.
* **`PermissiveCommunicationPolicy`**: Always returns `True` (default strategy).
* **`RuleGatedCommunicationPolicy`**: Evaluates static regular expression pattern rules and parent rule mappings on opposing teams.
* **`ProxiedCommunicationPolicy`**: Queries the LLM generator client of parent representatives dynamically for consent.

### Migration Policies

* **`BaseMigrationPolicy`**: Base protocol defining `authorize_migration(team, target_parent, manager, rationale) -> Tuple[bool, str]`.
* **`PermissiveMigrationPolicy`**: Always returns `(True, "Allowed")`.
* **`AncestorApprovalMigrationPolicy`**: Consults the representatives of the current parent, target parent, and Least Common Ancestor (LCA) teams (default strategy).
* **`LineagePathMigrationPolicy`**: Traverses and queries every team representative along the traversal path from the current parent up to the LCA, and from the target parent up to the LCA.

## Database Schema & ORM Models

SQLAlchemy Declarative Models mapping the topology schema, defined in [models.py](file:///Users/charlestsaur/Documents/sandbox/AI-Team-Team/src/ai_team_team/database/models.py):

* **`ManagerConfigModel`**: Key-value stores for serialized configuration payloads and Root AI targets.
* **`AgentModel` & `AgentMessageModel`**: Persists agent identity profiles and complete conversation histories with `team_id` and `discussion_id` provenance.
* **`TeamModel`**: Tracks active topologies, migration counts, sibling settings, and links dual-linked parent-child hierarchy nodes.
* **`TeamInboxModel` & `TeamProposalModel`**: Persists child escalations, peer messages, and democratic proposal votes.
* **`BrokerAgreementModel`**: Tracks cross-lineage tunnels negotiated by the broker.
* **`LibraryModel` & `LibraryPermissionModel` & `DocLibFileModel` & `DocLibLinkModel`**: Persists libraries, ACL segments, physical document contents, and managed cross-library file-link targets.

### Database Session Factory

* **`get_session(db_path: str) -> Generator[Session, None, None]`**
  A strict standalone writer context defined in `database/session.py`. It acquires the same exclusive writer lease, performs schema preflight before DDL, enables the configured SQLite safeguards, and yields a transactional SQLAlchemy session. Foreign-key enforcement cannot be disabled.
