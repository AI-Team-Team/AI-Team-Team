# Developer API Reference

This document provides a technical overview of the internal classes, properties, and coordination interfaces in the `ai-team-team` package for framework developers and contributors.

> [!NOTE]
> If you are an external developer integrating the library into your own application, please consult the [Public API Reference](../user/API_Reference.md) instead.

## Core Classes

### `Agent`

Represents an individual AI specialist equipped with role definitions and generator client integration.

One instance may be shared across teams. Its `lock` serializes all model-window mutations, `message_history` projects the sanitized cross-team Journal for host compatibility, and manager `ContextVar` values provide the selected scope and personal invocation.

* **Constructor**:

  ```python
  agent = Agent(name: str, role: str, llm_client: Optional[Any] = None, role_description: str = "", system_instructions: str = "", agent_id: Optional[str] = None)
  ```

* **Methods**:
  * `launch_att(...) -> AgentTeam | TeamFormationRequest`
        Creates an all-new child immediately or opens persistent consent when existing Agents or initiator self-membership are requested. No invitation mutates Agent-owned identity or runtime state.

`agent_id` is an immutable canonical UUID. `_private_doc_library_id` and `_model_alias` are manager-owned persistence fields; public code reads only `private_doc_library_id`.

### `AgentTeam`

Represents a dynamic team of membership satisfying `min_subagent_team_size`, default three, whose members act through their own continuing runtimes.

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

No AgentTeam method executes a compulsory all-member discussion or reasoning turn.

### `ATTManager`

The new personal runtime is composed through `ActivityAPI` and `PersonalActivityService` under `core/manager/activity/`.

`activate_agent()`, `inspect_agent_activity()`, `wait_for_activity_checkpoint()`, and `deliver_agent_mail()` expose committed admission and observation rather than a transcript-producing discussion.

The [Phase 2 engineering profile](autonomous_activity/Phase_2.md) specifies safe batches, immutable request profiles, local ownership, recovery, and lock ordering.

`ToolExecutor.execute(before_attempt=...)` accepts a trusted runtime hook for durable evidence after validation and auditing but before each actual executor attempt.

It is not a model-facing policy override or a new tool argument.

Master orchestrator managing the overall ATT topology, dynamic presets, tool registrations, and callback events.

`create_agent_team()` returns an immediate AgentTeam only for all-new membership. Existing Agent inputs return a persistent `TeamFormationRequest`; accepted identities are revalidated before the staged commit, and membership stores only the team/Agent relationship. `bootstrap_agent_team()` is the explicit audited host-only provisioned-topology bypass and is not registered as a tool.

Formation consent is revision-scoped.

`revise_team_formation()` commits material snapshots and resets retained invitations.

`prepare_team_formation_draft()` optionally validates the initiator's supplied candidate without invoking a model, and publication remains explicit.

There is no compulsory draft, detached team deliberation, or synthesis worker.

Synchronous and asynchronous callbacks share one ordered background dispatcher; callback failures are logged and never alter core transaction outcomes.

Event-loop and worker-thread emissions share the same acceptance order, and `flush_callbacks()` drains observations accepted before the flush, including pending thread emissions.

Observers do not inherit Agent or AgentTeam invocation context; actor and source information must come from the supplied metadata.

Per-callback observation tasks isolate self-cancellation from the ordered dispatcher, while shutdown cancels dispatch without awaiting an uncooperative observer indefinitely.

* **Constructor**:

  ```python
  manager = ATTManager(root_ai: Agent, config: Optional[ATTConfig] = None, db_path: Optional[str] = None, *, persistence_mode: str = "durable")
  ```

* **Methods**:
  * `register_model(name: str, config: Dict[str, Any])`
    Registers model metadata and optionally a `client=` runtime binding.
  * `register_llm_client(alias: str, client: Any)`
    Registers one stable alias for one direct client identity.
  * `register_generator_handler(handler: Callable[..., str])`
    Registers a global callback handler for generating text from a model alias.
  * `register_token_counter(model_alias: str, counter: Callable[[str], int | Awaitable[int]])`
    Registers a runtime-only exact counter for model-facing file content.
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
  * `register_tool(name, description=None, func=None, schema=None, *, memory_capture="metadata_only", execution_contract=None, executor="callable", resource_resolver=None, retry_safe=False, result_storage="protected")`
    Registers a validated tool with independent background, resource, retry, storage, and Journal-capture declarations; runtime executor and resource-resolver bindings are Host-owned.
  * `register_tool_auditor(tool_name: str, auditor_func: Callable[..., Tuple[bool, str]])`
    Registers an auditing hook callback that intercepts specific tool calls before execution.
  * `register_tools_context(context: Dict[str, Any])`
    Registers additional runtime resources and rebinds coordination tools. The reserved `att_manager` reference is installed automatically and cannot be overwritten.
  * `create_agent_team(...) -> AgentTeam | TeamFormationRequest`
    Validates all-new creation before mutation or opens a consent request without creating team entities when existing identities participate.
  * `bootstrap_agent_team(...) -> AgentTeam`
    Performs explicit trusted-host topology provisioning, preserves every Agent-owned field, and emits a durable administrative audit event.
  * `inspect_team_formation`, `prepare_team_formation_draft`, `get_team_formation_draft`, `publish_team_formation_draft`, `revise_team_formation`, `respond_team_invitation`, `create_team_from_formation`, `abandon_team_formation`, `decide_team_formation_late_join`
    Coordinate optional supplied candidates, immutable revision history, exact-revision invitation attitudes, live eligibility, accepted-subset creation, abandonment, and explicitly initiated late joining under per-draft and per-request locks.
  * `list_agent_inbox` / `mark_agent_inbox_read`
    Read and acknowledge identity-owned persistent notifications independently of any AgentTeam inbox.
  * `suppress_auto_save() -> AsyncContextManager`
    Nested, task-local batching context that merges dirty deltas and submits one write when the outer scope exits.
  * `await execute_agent_interaction(agent, prompt, *, team=None) -> InteractionResult`
    Observes one personal answer without publishing it, stopping continuing activity, or treating it as a ballot.
  * `activate_agent(agent_id, scope=None)` / `wait_for_activity_checkpoint(admission_id, intent=None)`
    Admit personal activity and observe accepted fairness or intent boundaries.
  * `find_parent_team(target: AgentTeam) -> Optional[AgentTeam]`
    Locates the parent team in the active team topology using the explicit parent index without creator or membership inference.
  * `check_library_access(team_id: str, lib_id: str, path: str, required_permission: str) -> bool`
    Evaluates if a team is granted `READ` or `WRITE` access to a Document Library path based on prefix segments.
  * `list_private_files`, `read_private_file`, `write_private_file`, `delete_private_file`, `move_private_file`, `publish_private_file`
    Resolve ownership only from `_active_tool_agent`; private operations never accept caller-supplied owner or library identifiers.
  * `move_library_file(...)`
    Atomically moves a normal library file after checking both path ACLs.
  * `render_topology_tree() -> str`
    Renders the ordinary lineage tree as a trusted-host diagnostic without automatically injecting it into Agent prompts.
  * `list_entities(entity_type="all", start_index=1, end_index=None) -> EntityDiscoveryResult`
    Captures public eligible records, sorts their labels deterministically, and selects inclusive entity positions.
  * `search_entities(keywords, entity_type="all", start_index=1, end_index=None) -> EntityDiscoveryResult`
    Applies case-insensitive OR substring matching to public fields before sorting and pagination.
  * `inspect_entity(entity_type, entity_id) -> AgentDirectoryRecord | AgentTeamDirectoryRecord`
    Resolves one latest public record by stable Agent or AgentTeam ID, using the same eligibility boundary.
  * `await negotiate_and_execute_migration(team: AgentTeam, target_parent: Agent | AgentTeam | ApprovalPrincipal | None, rationale: str) -> MigrationOperationResult`
    Arbitrates dynamic team reorganizations and updates parental references.
  * `await save_state(path: Optional[str] = None, full: bool = True)`
    Queues and waits for a full snapshot, or a configuration delta when `full=False`.
  * `await load_state(path: str)`
    Stages and validates every persisted reference, model binding, topology edge, DocLib file, ACL, and managed link before atomically publishing the restored runtime.
  * `await flush_state()`
    Waits for all queued incremental commits.
  * `await flush_memory_indexing()` / `await retry_memory_index(segment_id)`
    Coordinates optional background card indexing without making personal activity depend on indexing success.
  * `list_memory_index_failures(...)` / `restore_forgotten_memory(...)` / `list_agent_history(...)`
    Exposes trusted-host diagnostics and recovery while keeping the Journal unavailable to Agent tools.
  * `await close()`
    Rejects new work, cancels external LLM waits, flushes accepted writes, and closes the single writer lease, engines, and sessions.
  * `await flush_callbacks()`
    Waits for the ordered observational callback queue.
  * `request_health_assessment`, `wait_for_health_assessment`, `cancel_health_assessment`
    Admit fresh scoped audits and observe retained results under a total deadline.
  * `inspect_health_incident`, `claim_health_incident`, `acknowledge_health_incident`, `handle_health_incident`, `clear_health_incidents`
    Inspect retained evidence and explicitly handle the current incident occurrence generation.

### `ATTConfig`

Configuration options for tuning the ATT multi-agent framework.

`ATTConfig` is a strict Pydantic model with forbidden extra fields and assignment validation. Runtime updates to scalar fields and supported mutable configuration mappings are validated by the same rules used during construction.

* **Constructor**:

  ```python
  from ai_team_team import ATTConfig, HealthSupervisionConfig, ParentApprovalCommunicationConfig

  config = ATTConfig(
      communication=ParentApprovalCommunicationConfig(request_delivery="queue"),
      health=HealthSupervisionConfig(
          protocol_failure_threshold=3,
          tool_argument_failure_threshold=5,
          observation_window_seconds=600,
          audit_timeout_seconds=600,
      ),
      working_context_message_limit=20,
      migration_policy="ancestor_approval",
      allow_unilateral_detachment=True,
      migration_cooldown_downtime="include",
      failover_policy="parent",
      parent_failover_timeout_seconds=120,
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
      Resolves actual `agent_team` and `agent` principals with independent-side exemptions without selecting an Agent to act for a team.

### `DiscoveryService`

Projects the existing Agent and AgentTeam registries into detached public records rather than owning a separate directory or persisted index.

Capture runs without suspension under the topology lock; filtering, deterministic label ordering, derived depth calculation, and position selection operate only on the captured values.

Agent-facing wrappers are asynchronous without suspension so `Tool` does not dispatch live-object capture to a worker thread, and the service never borrows Agent invocation locks or updates depth caches.

Text ReAct, Native, personal interactions, and voluntary formation activity advertise the same available discovery tools instead of injecting full global directories.

Counts and range metadata describe one capture, while separate pages may observe different live registries without a version protocol.

See [Agent and AgentTeam Discovery](../Agent_and_AgentTeam_Discovery.md) for the public result models and exact privacy, lifecycle, and pagination contracts.

### `TeamDecisionProvider` and `GovernanceService`

The decision provider prepares exact governance cases and personal mail rather than running inference itself.

Each case freezes a real principal, eligible Agent IDs, electorate revision, strict choice schema, and business reference.

Complete explicit ballots are required before strict majority supplies authority, independently of email read receipts.

`GovernanceCase`, `GovernanceBallot`, and `GovernanceSubmissionResult` expose immutable case identity and choices.

An Agent parent acts through its own inbox and continuing personal activity; Root has no special representative fallback.

`MigrationRequest` retains exact route evidence, while parent resource attempts retain their independent total deadline and expire after interruption.

### `SupervisionService` and supervisory AgentTeams

The service provisions a fresh real privileged AT through common staged creation for each admitted assessment.

Its scoped people use the same personal scheduler, provider service, ToolExecutor, quota ledger, and writer.

Only explicit structured findings from every predefined auditor may form a strict-majority result.

The total default 600-second deadline includes queueing and is separate from parent failover.

Scoped evidence remains retained, but temporary identities are removed and never restored or reused.

Typed streak detectors, stable incidents, occurrence events, explicit claims, and current-generation acknowledgement remain separate from model findings and operational availability.

See [Supervisory Team](../Supervisory_Team.md) and the [Phase 5 profile](autonomous_activity/Phase_5.md) for evidence and authority boundaries.

### `Tool` and `ToolExecutor`

`Tool` owns the provider-neutral callable contract, validated JSON Schema, prompt rendering metadata, examples, and `retry_safe` declaration. Automatic schemas support `Annotated`, `Literal`, Enum, Pydantic models, `TypedDict`, containers, unions, and nesting. Portable `TypedDict` annotations across Python 3.11–3.13 must come from `typing_extensions`; incompatible standard-library definitions fail during tool registration with an actionable error. Registration validates handwritten schemas against Draft 2020-12.

`ToolExecutor.execute()` is shared by Text and Native protocols. It binds the invocation signature, applies strict Pydantic JSON validation, validates the original argument object against the generated or handwritten Draft 2020-12 schema, runs the auditor and callable under Agent/AgentTeam ContextVars, and returns `ToolResult` with a structured status, error kind, and attempt count. It recognizes typed `ToolArgumentError`, `ToolPermissionError`, `ToolBusinessError`, and `RetryableToolError`; custom result strings are never classified by prefix.

Native provider interfaces receive `Optional[List[Tool]]`. The provider adapter converts `Tool.json_schema` into its SDK's concrete function-calling shape and converts responses back to `LLMResponse` and `ToolCall`.

### `GatedFileReader`

Asynchronous token-bounded reader for normalized model-facing text content.

* **Constructor**:

  ```python
  reader = GatedFileReader(
      max_read_tokens=4000,
      tokenizer_fallback="conservative",
      token_counter=my_counter,
      model_alias="primary",
  )
  ```

* **Methods**:
  * `await read_file(path: str, start_line: int = 1, end_line: Optional[int] = None, start_character: int = 1, character_count: Optional[int] = None, expected_file_version: Optional[str] = None) -> FileReadResult`
    Returns the largest requested normalized content prefix within `max_read_tokens`. Partial results include the next source position and file version; the token budget excludes structured metadata and tool framing.

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
  * `read_file(path: str, start_line: int, end_line: Optional[int], start_character: int = 1, character_count: Optional[int] = None) -> str`
    Reads an unbounded normalized source range for trusted host-side operations.
  * `delete_file(path: str) -> str`
  * `list_contents(path: str) -> List[str]`
  * `move_file(source_path: str, target_path: str, overwrite: bool = False)`
  * `write_file_atomic(path: str, content: str, overwrite: bool = False)`

Native filesystem symlinks are rejected. Cross-library links are manager-owned metadata exposed through `create_library_link`; direct `DocumentLibrary` methods operate on physical files only.

## Policies & Strategy Interfaces

Migration strategies are defined in [`policies.py`](../../src/ai_team_team/core/policies.py). Communication is not a per-call strategy interface: its strict Pydantic configuration is consumed by `NegotiationBroker`.

### Migration Policies

* **`BaseMigrationPolicy`**: Delegates `authorize_migration(team, target_parent, manager, rationale) -> MigrationOperationResult` to the manager's durable migration service; a policy instance cannot override `ATTConfig`.
* **`PermissiveMigrationPolicy`**: Uses no ordinary path approvals but still requires explicit target-parent acceptance and final topology revalidation.
* **`AncestorApprovalMigrationPolicy`**: Resolves explicit current-parent, target-parent, and Least Common Ancestor principals when configured (default strategy).
* **`LineagePathMigrationPolicy`**: Resolves every explicit AgentTeam/Agent principal along the affected lineage path when configured.

## Database Schema & ORM Models

SQLAlchemy models and relational activity tables mapping schema 15 are grouped in the [`models`](../../src/ai_team_team/database/models/) package:

* **`ManagerConfigModel`**: Key-value stores for serialized configuration payloads and Root AI targets.
* **`AgentModel`, `AgentMessageModel`, and `AgentInboxModel`**: Use immutable `agent_id` primary/foreign keys and persist lifecycle profiles, bounded Working Context, and identity-addressed notifications.
* **`SystemMemoryEventModel`**: Stores the append-only host Journal without an Agent foreign key so confirmed identity deletion can retain historical snapshots.
* **`AgentMemorySegmentModel`, `AgentMemoryCardModel`, `MemoryCardTagModel`, `MemoryCardSourceEventModel`, and `RetainedMemoryReferenceModel`**: Store Agent-owned deterministic segments, searchable card metadata, source provenance, and explicit compact Working Context retention.
* **`TeamModel`**: Tracks explicit parent positions, independent creator provenance, lifecycle, and UUID-backed membership references.
* **`TeamInboxModel` & `TeamProposalModel`**: Persists child escalations, peer messages, and democratic proposal votes.
* **`TeamFormationRequestModel`, `TeamFormationInvitationModel`, `TeamFormationRevisionModel`, `TeamFormationInvitationDecisionModel`, and `TeamFormationDraftModel`**: Persist the current proposal projection, current invitations, immutable material revision snapshots, append-only exact-revision attitudes, optional initiator-authored candidates, accepted founding records, completion choices, and late-join state.
* **`CommunicationRequestModel`, `CommunicationApprovalModel`, `CommunicationBallotModel`**: Persist the request lifecycle, ordered explicit principals, and member ballots.
* **`CommunicationAgreementModel` & `PeerMessageModel`**: Persist directional endpoint channels, revocation state, and idempotent delivery lifecycle.
* **`GovernanceCaseModel`, `GovernanceElectorateModel`, `GovernanceBallotModel`, and `MigrationRequestModel`**: Persist exact cases, eligible people, append-only choices, and revalidated migration authority.
* **Institutional activity tables**: Retain topology revisions, parent acceptances, cooldowns, resource attempts, typed health observations, incidents, scoped audit activity, findings, and final evidence.
* **`LibraryModel` & `LibraryPermissionModel` & `DocLibFileModel` & `DocLibLinkModel`**: Persists library kind, mutually exclusive team/agent ownership, lifecycle, ACL segments, physical document contents, and managed team-library link targets.

### Registered Execution Service

`core.manager.executions` owns all registered personal-tool admission, canonical resource scheduling, executor dispatch, actual-start timing, threshold observation, factual stop controls, health evidence, and owner-only queries.

The personal runner uses the same classified `ToolExecutor` for argument validation, auditors, typed failures, and retries, while coordinated foreground-only controls retain their personal invocation context.

Foreground-only effects never select a separate callable or bypass resource resolvers and final source checks, and tools cannot wait for nested personal models while retaining shared resource claims.

Both direct model invocation and personal interaction enforce that boundary before admission; a permitted source-free nested invocation isolates the parent's tool-resource context without removing its revocable authority or dependency edges.

`ExecutorCall` carries immutable execution provenance and validated inputs without the owner's Session or model window.

Runtime bindings implement `async execute(call)` and optional declared stop hooks; persisted names never authorize replay or automatic reconnection during restore.

Stop protocol tasks retain fatal framework errors from immediate and late hooks for propagation through cancellation and shutdown without treating the error as proof of an external stop.

Timeout observations and accepted heartbeat/progress samples use the same activity lock, and monitor scheduling retains a deadline crossed during an awaited observation commit.

`ResourceClaim` describes protected read/write footprints, including directory descendants and physical link targets, with synchronous physical path locks as a final publication boundary.

See the [Phase 4 implementation profile](autonomous_activity/Phase_4.md) and [schema 14](autonomous_activity/Schema_14.md).

### Database Session Factory

* **`get_session(db_path: str) -> Generator[Session, None, None]`**
  A strict standalone writer context defined in `database/session.py`. It acquires the same exclusive writer lease, performs schema preflight before DDL, enables the configured SQLite safeguards, and yields a transactional SQLAlchemy session. Foreign-key enforcement cannot be disabled.
