# Public API Reference

This document describes the public interface, parameters, and protocol conventions of the `ai-team-team` package. Only components intended for direct instantiation or external interaction are listed here.

## ⚙️ `ATTConfig`

Strict, assignment-validated configuration for the ATT runtime.

### Constructor

```python
from ai_team_team import (
    ATTConfig,
    ConversationConfig,
    EpisodicMemoryConfig,
    ExecutionConfig,
    FileReadConfig,
    PermissiveCommunicationConfig,
    HealthSupervisionConfig,
)

config = ATTConfig(
    communication=PermissiveCommunicationConfig(),
    file_read=FileReadConfig(),
    conversations=ConversationConfig(),
    episodic_memory=EpisodicMemoryConfig(enabled=False),
    executions=ExecutionConfig(),
    health=HealthSupervisionConfig(),
    model_tokenizer_configs={
        "analysis": "bert-base-uncased",
        "default": "/absolute/path/to/tokenizer.json",
    },
)
```

### Top-Level Parameters

| Configuration Property | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `enable_dynamic_delegation` | `bool` | `True` | Exposes dynamic child-AgentTeam delegation when the current depth also permits it. |
| `max_delegation_depth` | `int` | `2` | Maximum recursive AgentTeam depth; must be at least `1`. |
| `min_subagent_team_size` | `int` | `3` | Minimum final member count for a dynamically formed AgentTeam; must be at least `3`. |
| `model_registry` | `Dict[str, str]` | `{}` | Persisted, validated host metadata mapping with non-empty string keys and values; register operational model metadata and client bindings through `ATTManager.register_model()` and `register_llm_client()`. |
| `enable_membership_voting` | `bool` | `False` | Enables optional membership proposal voting. |
| `enable_memory_compression` | `bool` | `True` | Enables bounded high-fidelity message windows and compression of older conversation material. |
| `workspace_root` | `str` | `"."` | Non-empty host workspace used as the root for ATT-managed DocLib storage; `~` is expanded. |
| `working_context_message_limit` | `int` | `20` | Positive recent-message target for derived context compaction; the sanitized personal Journal remains complete. |
| `communication` | `CommunicationConfig` | `PermissiveCommunicationConfig()` | Selects the one communication institution followed by every AgentTeam. |
| `migration_policy` | `Literal` | `"ancestor_approval"` | Migration authorization: `"permissive"`, `"ancestor_approval"`, or `"lineage_path"`. |
| `tool_calling_mode` | `Literal` | `"auto"` | Tool strategy: `"auto"`, `"native"`, `"text_react"`, or the `"react"` alias. |
| `max_tool_execution_retries` | `int` | `2` | Additional execution attempts for eligible typed transient failures; may be `0`. |
| `tool_execution_retry_policy` | `Literal` | `"never"` | Replay policy: `"never"`, `"retry_safe"`, or `"typed_transient"`. |
| `tool_execution_retry_backoff_factor` | `float` | `0.5` | Initial exponential delay for eligible execution retries; `0` retries immediately. |
| `text_tool_schema_mode` | `Literal` | `"compact"` | Text prompt schema rendering: `"compact"`, `"full"`, or `"compact_with_examples"`. |
| `tool_prompt_modes` | `Dict[str, str]` | `{}` | Per-tool schema rendering overrides using the same three modes. |
| `operational_status_decision_mode` | `Literal` | `"framework"` | Runtime-health authority: `"framework"`, `"supervisor"`, or `"framework_then_supervisor"`. |
| `operational_degraded_escalation_mode` | `Literal` | `"none"` | Degraded runtime alert routing: `"none"`, `"queue"`, or `"wake"`. |
| `model_token_limits` | `Dict[str, int]` | `{}` | Per-model hard quotas used by the atomic token ledger; values are non-negative and `0` disables that model. |
| `model_max_output_tokens` | `Dict[str, int]` | `{}` | Positive per-model output reservations and provider request caps used with hard quotas. |
| `default_max_output_tokens` | `int` | `1024` | Positive output reservation used when a model-specific cap is absent. |
| `model_tokenizer_configs` | `Dict[str, str]` | `{}` | Maps model aliases to a `tokenizers` pretrained identifier or tokenizer JSON path for prompt accounting and model-facing file reads. |
| `failover_policy` | `Literal` | `"auto"` | Token-exhaustion behavior: `"auto"`, `"parent"`, or `"none"`. |
| `parent_failover_timeout_seconds` | `float` | `120.0` | Positive timeout for parent AgentTeam or Root Agent model selection; parent-governed failure does not fall back to auto selection. |
| `audit_unknown_escalation_mode` | `Literal` | `"wake"` | Routes UNKNOWN health attention through protected personal notifications, with `"queue"` retaining attention without forced activation. |
| `audit_unknown_soft_threshold` | `int` | `100` | Positive soft warning threshold for unique UNKNOWN alerts; alerts are not dropped or expired automatically. |
| `agent_private_data_policy` | `Literal` | `"archive"` | Default Agent retirement data handling: `"retain"`, `"archive"`, or confirmed `"delete"`. |
| `file_read` | `FileReadConfig` | `FileReadConfig()` | Controls decoded content-token limits and missing-counter behavior for model-facing team and private file reads. |
| `episodic_memory` | `EpisodicMemoryConfig` | `EpisodicMemoryConfig()` | Configures the optional Agent-owned episodic-memory catalog, which is disabled by default. |
| `activity` | `PersonalActivityConfig` | `PersonalActivityConfig()` | Continuing-person scheduling, notification frames, finite sleep, cooldown accounting, and bounded model requests. |
| `conversations` | `ConversationConfig` | `ConversationConfig()` | Title and preview bounds, withdrawal window, and default personal team/direct detail settings. |
| `executions` | `ExecutionConfig` | `ExecutionConfig()` | Independent executor capacity, background detachment, bounded stop-hook waiting, and retained-result access. |
| `health` | `HealthSupervisionConfig` | `HealthSupervisionConfig()` | Typed health-evidence thresholds, rolling observation window, assessment deadline, and optional semantic detection. |
| `allow_unilateral_detachment` | `bool` | `True` | Allows a team to leave its current parent without that parent's approval, subject to live authority and cooldown. |
| `enable_migration` | `bool` | `True` | Enables ordinary parent-to-parent position changes separately from voluntary detachment. |
| `migration_cooldown_downtime` | `Literal` | `"include"` | Counts real offline elapsed time in the ten-minute own-position cooldown; `"exclude"` preserves remaining time instead. |

### `ExecutionConfig`

The strict defaults are `automatic_detachment_seconds=120.0`, `max_concurrent_executions=8`, `cancellation_grace_seconds=2.0`, and `retain_results_after_source_revocation=True`.

The threshold starts at actual executor dispatch, includes retry and backoff, and excludes initial queue and preflight time.

Setting retained-result access to `False` requires current authority for the original protected sources without borrowing a later team scope, deleting execution history, or rereading those sources automatically.

Stop-hook waiting is bounded independently of persistence, and accepted local commits have no arbitrary flush timeout.

### `ConversationConfig`

The strict, assignment-validated defaults are `title_max_characters=200`, `preview_characters=500`, `summary_preview_limit=20`, `withdrawal_window_seconds=600.0`, `team_details=True`, and `direct_details=True`.

Character counts and preview limits must be positive integers; the withdrawal window must be finite and positive, without a fixed ten-minute maximum.

Personal `set_chat_details()` overrides persist independently of the default configuration and do not modify team membership or Agent identity.

### `PersonalActivityConfig` and `ModelRequestPolicy`

These strict nested models validate both construction and runtime assignment, including individual `llm.model_timeouts` entries.

`activity.model_requests_per_invocation=5` bounds request sequences in one fair invocation, and `tool_batches_per_invocation=5` bounds complete batches before a technical yield.

Neither setting makes an Agent idle or completes a business task.

The defaults admit eight personal invocations and eight provider requests concurrently, with at most twenty newly presented references in each notification frame.

Finite sleep uses `minimum_sleep_minutes=5` and `maximum_sleep_minutes=2880`, with validated ordered bounds.

Eligible execution faults use `tool_cooldown_seconds=600.0` and `cooldown_downtime="include"`; `"exclude"` preserves the remaining duration while ATT is offline.

`activity.llm` defaults to `max_retries=3`, `backoff_base_seconds=1.0`, `backoff_cap_seconds=30.0`, `request_timeout_seconds=120.0`, `sequence_timeout_seconds=600.0`, and `recovery_delay_seconds=60.0`.

`activity.llm.model_timeouts` can override the positive finite single-request timeout for a stable model alias.

Provider earliest-retry instructions can exceed the jitter cap but cannot force a request beyond the remaining whole-sequence budget.

No second team-discussion engine, numbered round API, or argument-correction turn limit remains.

### Communication Configuration

`CommunicationConfig` is a strict discriminated union selected by its immutable `policy` field.

| Configuration Type | Policy | Additional Fields | Meaning |
| :--- | :--- | :--- | :--- |
| `PermissiveCommunicationConfig` | `"permissive"` | None | Authenticated AgentTeams communicate directly without an Agreement. |
| `ParentApprovalCommunicationConfig` | `"parent_approval"` | `request_delivery="queue"`, `direction="bidirectional"` | The actual parent principals of non-independent endpoints approve, deduplicated. |
| `LineageApprovalCommunicationConfig` | `"lineage_approval"` | `request_delivery="queue"`, `direction="bidirectional"` | The non-exempt recipient and required real lineage principals approve without a virtual Root. |

Approval configurations accept only `request_delivery="queue"` and either channel direction.

Communication `wake` is explicitly rejected while its separate safeguards remain deferred.

Independent endpoints are exempt from their own parent/ancestor authority; two independent endpoints communicate directly without Requests or Agreements.

### `HealthSupervisionConfig`

The strict defaults are `protocol_failure_threshold=3`, `tool_argument_failure_threshold=5`, `observation_window_seconds=600.0`, `audit_timeout_seconds=600.0`, and `semantic_detection_enabled=False`.

Counts belong to one immutable Agent identity, with tool failures additionally grouped by tool and argument-error category.

A valid model response resets its protocol streak, and success on a tool resets that tool's argument streak.

Provider availability, silence, normal waiting, permission denial, and business refusal do not become personal health findings.

Thresholds request assessment, not intervention.

Confirmed integrity faults require immediate deterministic protection and a retained incident without awaiting assessment.

The rolling observation window expires detector samples, not incidents.

The total assessment deadline starts at durable admission, includes queueing, and is independent of the 120-second parent-resource attempt.

### Tokenizer Configuration and Hard-Quota Accounting

`model_tokenizer_configs` accepts only non-empty model aliases and non-empty strings understood by the required `tokenizers` package as either pretrained identifiers or tokenizer JSON files.

General prompt accounting first checks the exact model alias and then the optional `"default"` tokenizer entry; if neither is configured or loading fails, it uses the framework's character heuristic.

Model-facing file reads deliberately use a stricter counter chain for the active Agent's exact model alias: configured tokenizer, provider `count_tokens(text)`, host `register_token_counter(alias, counter)`, and finally the selected `FileReadConfig` fallback.

Hard-quota prompt estimation includes the serialized prompt, system instruction, and complete tool definitions and JSON Schemas, then atomically reserves the configured maximum output budget before dispatch.

### `FileReadConfig`

`FileReadConfig` controls content returned by `read_library_file` and `read_private_file`; small structured result metadata and tool-protocol framing are outside the decoded content budget.

| Property | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `max_read_tokens` | `int` | `4000` | Positive hard limit for returned decoded file content; file size and line count are not resource limits. |
| `tokenizer_fallback` | `Literal` | `"conservative"` | Uses a UTF-8-byte upper-bound estimate when no exact counter is available; `"strict"` rejects the read instead. |

Partial reads return `next_line`, `next_character`, and `file_version`; pass all three into the next read to continue without gaps and reject a stale cursor after file mutation.

### `EpisodicMemoryConfig`

Advanced episodic memory is optional and disabled by default; disabled mode performs no indexing calls, creates no Memory Cards, exposes no memory tools, and does not require FTS5.

| Property | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `enabled` | `bool` | `False` | Enables the Agent-owned episodic-memory catalog. |
| `segment_boundary` | `Literal["activity_invocation"]` | `"activity_invocation"` | Uses committed personal invocation boundaries as immutable indexing segments. |
| `index_max_retries` | `int` | `2` | Additional indexing attempts after the first failure; may be `0`. |
| `index_retry_backoff_factor` | `float` | `0.5` | Initial exponential retry delay; may be `0`. |
| `index_worker_count` | `int` | `2` | Positive number of background indexing workers. |
| `max_search_results` | `int` | `20` | Positive upper bound for catalog search matches. |
| `max_recall_lines` | `int` | `100` | Positive line limit for one recalled source range. |
| `max_recall_chars` | `int` | `20000` | Positive character limit for one recalled source range. |
| `max_recall_tokens` | `int` | `4000` | Positive content-token limit for recalled material. |
| `max_tags_per_card` | `int` | `12` | Positive maximum normalized tags stored on one Memory Card. |
| `max_retained_context_items` | `int` | `20` | Positive maximum retained recall references in the Agent's working context. |

Policy names, numeric values, construction, runtime assignment, and mutable mapping updates all use strict validation; unknown fields or invalid values raise `ValueError`.

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
  Launches an all-new AgentTeam with explicit optional `parent=` immediately, or opens a persistent consent workflow when the proposal names existing Agents or explicitly includes the initiator. Existing identities are not added until they accept; see [Consensual Existing-Agent Team Formation](../Consensual_Team_Formation.md).

## 👥 `AgentTeam`

Represents an organization with explicit membership, optional Agent/AgentTeam parent, shared conversation, documents, and governance. External users obtain an `AgentTeam` instance when calling `ATTManager.create_agent_team` or `Agent.launch_att`.

### Properties

* **`team_id`**: `str` - The unique identifier of the team (e.g. `AT-abc123`).
* **`team_purpose`**: `str` - The global purpose/objective of this team.
* **`team_progress`**: `str` - The real-time status/progress of this team (default: `"Not started"`).
* **`depth`**: `int` - The depth level of the team in the lineage hierarchy (e.g., Level 1, Level 2).
* **`members`**: `List[Agent]` - The list of `Agent` instances assigned to this team.
* **`doc_library`**: `Optional[DocumentLibrary]` - Resolves the built-in document library for the team.
* **`parent_team`**: `Optional[AgentTeam]` - The actual AT parent, if one exists.
* **`organizational_parent`**: `ApprovalPrincipal | None` - The explicit Agent/AT parent, or independence; creator provenance never selects it.
* **`is_independent`**: `bool` - Whether the team has no organizational parent.
* **`child_teams`**: `List[AgentTeam]` - The list of active child teams spawned by this team.
* **`proposals`**: `Dict[str, Dict[str, Any]]` - Active membership voting proposals mapped by ID.
* **`status_map`**: `Dict[str, str]` - Dictionary mapping member names to their current statuses (e.g. `"Thinking..."`, `"Idle"`).

### Methods

* **`launch_att(...) -> AgentTeam | TeamFormationRequest`**
  Launches an all-new child AgentTeam immediately, or returns a formation request when existing Agents must consent. The initiating member is never added implicitly.
## 🏛️ `ATTManager`

The master controller managing the overall agent team topology, tool registrations, presets, and callback events.

### Constructor

```python
from ai_team_team import ATTManager

manager = ATTManager(root_ai: Agent, config: Optional[ATTConfig] = None, db_path: Optional[str] = None, *, persistence_mode: str = "durable")
```

Durable mode requires an explicit `db_path` and claims exclusive writer ownership before registering managed resources.

The Host may explicitly choose `persistence_mode="volatile"` without `db_path`; this keeps the same authority checks but does not promise restart recovery.

Loading a SQLite checkpoint adopts durable mode after successful publication.

### Methods

* **`await activate_agent(agent_id: str, *, scope: OperationScope | None = None) -> ActivityAdmission`**
  Admits a continuing person in personal scope by default, or coalesces with that person's existing activity without changing its scope.
* **`inspect_agent_activity(agent_id: str) -> ActivityView`**
  Returns personal intent, runtime availability, and the current admission and scope without activating the person.
* **`await wait_for_activity_checkpoint(admission_id: str, *, intent=None) -> ActivityCheckpoint`**
  Observes a committed boundary, optionally waiting for `"continuing"`, `"idle"`, or `"sleep"`; cancelling the observer does not cancel the person.
* **`await deliver_agent_mail(agent_id: str, *, message_type: str, payload: Mapping[str, Any]) -> SourceDeliveryReceipt`**
  Commits addressed personal mail and notification references before scheduling eligible activity; presentation is not reading or consent.
* **`await clear_agent_model_unavailability(agent_id: str) -> None`**
  Host-only acknowledgement after resource remediation, without resetting quota, switching the model, or bypassing live-request and provider waiting boundaries.
* **`register_runtime_clock(clock: RuntimeClock) -> None`**
  Binds a Host clock before activity, requests, or timers are admitted; ordinary applications use the built-in clock.

  Institutional admission also freezes the binding before a commit wait, including audits, parent resource attempts, migration cooldowns, and health-detection windows.

  Completed audit teardown does not unfreeze the clock, and restored institutional anchors retain the same protection.
* **`await send_team_message(team_id, markdown, *, actor, operation_key=None, reply_to=None) -> SourceDeliveryReceipt`**
  Deliberately publishes to a current ordinary AgentTeam and commits recipient views and notices before acknowledging delivery.
* **`await send_direct_message(agent_id, markdown, *, actor, operation_key=None, reply_to=None) -> SourceDeliveryReceipt`**
  Publishes personal chat under the canonical pair's live blocks, refusal, friendship, and directional stranger allowance.
* **`list_team_messages(team_id, *, actor, unread_only=False, query=None, limit=50, cursor=None, include_deleted=False) -> ChatMessagePage`**
  Returns authorized live and frozen personal history, filtering before metadata, search, or opaque pagination; previews do not mark read.
* **`list_direct_messages(agent_id, *, actor, unread_only=False, query=None, limit=50, cursor=None, include_deleted=False) -> ChatMessagePage`**
  Lists only the acting person's direct conversation with that endpoint.
* **`await read_chat_message(message_id, *, actor, version=None, start_line=1, end_line=None, start_character=1, character_count=None, expected_file_version=None) -> ChatReadResult`**
  Returns a token-gated authorized body range and commits its personal read marker; stale versions and failed reads return no content or false read receipt.
* **`list_chat_reminders(*, actor, message_id=None, limit=50, cursor=None) -> ChatReminderPage`**
  Inspects only that person's captured unread previews, including retained withdrawal evidence, without reopening a withdrawn source or clearing its unread revision.
* **`await edit_chat_message(message_id, markdown, *, actor, operation_key=None) -> ChatOperationResult`**
  Appends an author-only revision, checking current team scope or direct delivery admission; direct edits also consume stranger allowance while not friends.
* **`await withdraw_chat_message(message_id, *, actor, operation_key=None) -> ChatOperationResult`**
  Commits an author-attributed source marker within the configured window without erasing earlier frozen history or captured recipient reminders.
* **`await control_chat_message(command, message_id, *, actor, operation_key=None) -> ChatOperationResult`**
  Uses `mark_message_read`, `mark_message_unread`, `delete_message`, or `restore_message` to change only the actor's authorized personal view.
* **`await set_chat_details(*, actor, team_details=None, direct_details=None, operation_key=None) -> ChatOperationResult`**
  Changes personal bounded-preview preferences while preserving unread counts.
* **`inspect_direct_relationship(agent_id, *, actor) -> ChatRelationship`**
  Reports pair generation, friendship, each endpoint's independent controls, and the actor's remaining stranger deliveries.
* **`list_friendship_requests(*, actor) -> tuple[FriendshipRequestView, ...]`**
  Includes only requests sent to or from that person, including historical decisions.
* **`await request_friendship(agent_id, *, actor, operation_key=None) -> ChatOperationResult`**
  Creates or returns a pending metadata-only request without treating crossed requests or read mail as consent.
* **`await respond_friendship(request_id, decision, *, actor, operation_key=None) -> ChatOperationResult`**
  Accepts `accept`, `reject`, or `ignore` for the recipient, or `cancel` for the sender; obsolete generations cannot establish friendship.
* **`await control_direct_relationship(agent_id, command, *, actor, operation_key=None) -> ChatOperationResult`**
  Supports `block_agent`, `unblock_agent`, `remove_friendship`, or `lift_direct_refusal` without changing another person's owned controls.
* **`await close_team_conversation(team_id)`**
  Host-only finalization closes current memberships and preserves personal archives; surviving direct children become independent while their descendants retain their own immediate parents.
* **`register_tool(name, description=None, func=None, schema=None, *, memory_capture="metadata_only", execution_contract=None, executor="callable", resource_resolver=None, retry_safe=False, result_storage="protected")`**
  Registers a custom utility tool globally and requires explicit `memory_capture="content"` before its observation body may enter episodic recall content.
  Background execution requires an affirmative execution contract, while executor and resource-resolver bindings remain Host-only runtime objects.
  `result_storage="transient"` prevents the task body from being persisted without changing the tool's independent retry declaration.
* **`register_agent(agent: Agent) -> Agent`**
  Registers one stable identity and creates its unique private DocLib. Direct mutation of `manager.agents` is unsupported.
* **`get_private_library_id(agent_id: str) -> str`**
  Returns the canonical `PDL-<agent_id>` ID.
* **`await retire_agent(agent_id: str, policy: Optional[str] = None, confirm_delete: bool = False)`**
  Deactivates an unused AI under `retain`, `archive`, or confirmed `delete`. Root, team members, team creators, agents with an active model call, and identities referenced by membership, activity, or governance/audit history cannot be permanently deleted, including in volatile sessions.
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
  Returns a detached proposal, four public attitude counts, live eligible membership, `can_create`, and an eligibility reason.
* **`await prepare_team_formation_draft(*, actor, objective, candidate, request_id=None, parent=None) -> TeamFormationDraft`**
  Immediately validates the initiator's optional candidate without another model call or participant barrier; initial parents are explicit and revision candidates retain their exact base.
* **`get_team_formation_draft(draft_id, *, actor) -> TeamFormationDraft`** / **`list_team_formation_drafts(*, actor) -> list[TeamFormationDraft]`**
  Returns detached draft views owned by the initiating Agent.
* **`await publish_team_formation_draft(draft_id, *, actor) -> FormationOperationResult`**
  Explicitly publishes a ready validated candidate. Publication never grants invitee consent and fails closed when a revision draft has a stale base.
* **`await revise_team_formation(request_id, *, actor, base_revision, changes) -> FormationOperationResult`**
  Commits one validated material revision, preserves immutable history, and resets every retained invitee to `no_response`. A normalized no-op returns `UNCHANGED` without persistence or notifications.
* **`list_team_formation_revisions(request_id) -> list[TeamFormationRevision]`** / **`list_team_formation_decisions(request_id) -> list[TeamFormationInvitationDecision]`**
  Returns detached immutable audit histories for trusted host inspection.
* **`await respond_team_invitation(request_id, *, actor, proposal_revision, attitude) -> FormationOperationResult`**
  Records an invited Agent's `accepted`, `declined`, or `explicitly_ignored` attitude. Choosing `None` deliberately withholds a public attitude and remains externally indistinguishable from an unprocessed invitation as `no_response`.
* **`await create_team_from_formation(request_id, *, actor, proposal_revision) -> FormationOperationResult`**
  Lets only the initiating Agent commit the currently accepted eligible membership.
* **`await abandon_team_formation(request_id, *, actor, proposal_revision, reason="") -> FormationOperationResult`**
  Terminates an uncreated proposal and notifies every invitee.
* **`await decide_team_formation_late_join(request_id, invitee_agent_id, *, actor, proposal_revision, approved) -> FormationOperationResult`**
  Lets the initiating Agent approve or deny one pending late join against the exact current proposal revision.
* **`list_agent_inbox(agent_id, *, unread_only=True) -> list[AgentInboxMessage]`** / **`await mark_agent_inbox_read(agent_id, message_ids=None) -> int`**
  Provides trusted-host access to persistent notifications owned by a stable Agent identity.
* **`open_agent_mail(message_id: str, *, actor: Agent) -> dict`**
  Inspects an email addressed to that Agent, including its public governance request, without marking it read or supplying a choice.
* **`list_governance_requests(*, actor: Agent, pending_only: bool = True) -> list[dict]`**
  Lists that Agent's cases and unanswered eligible requests independently of email read state.
* **`await submit_governance_choice(case_id: str, choice: dict, *, actor: Agent) -> GovernanceSubmissionResult`**
  Requires the actor's current tool-invocation context and records one immutable strict boolean or eligible model-alias choice for the exact frozen case.
* **`await execute_agent_interaction(agent: Agent, prompt: str, *, team: Optional[AgentTeam] = None) -> InteractionResult`**
  Observes an answer from the same continuing person with actual invocation and team provenance; it neither stops activity nor publishes a shared message.
  `team=None` supplies personal scope, and a concurrent input coalesces without replacing an already active scope.
* **`await request_model_resource(agent: Agent, team: AgentTeam | None, error: TokenLimitExceededError) -> ResourceDecisionResult`**
  Returns `APPLIED`, `PENDING` with an independently bounded attempt ID, or `UNAVAILABLE`; it never nests a parent model call inside the requester.

* **`render_topology_tree() -> str`**
  Renders the ordinary AgentTeam lineage as a trusted-host ASCII diagnostic, not an automatically injected Agent context.
* **`list_entities(entity_type: Literal["agent", "agent_team", "all"] = "all", start_index: int = 1, end_index: Optional[int] = None) -> EntityDiscoveryResult`**
  Lists public records using one-based inclusive entity positions, defaulting to 30 records from the requested start.
* **`search_entities(keywords: List[str], entity_type: Literal["agent", "agent_team", "all"] = "all", start_index: int = 1, end_index: Optional[int] = None) -> EntityDiscoveryResult`**
  Filters public directory fields by case-insensitive OR substrings before ordering and selecting the requested positions.
* **`inspect_entity(entity_type: Literal["agent", "agent_team"], entity_id: str) -> AgentDirectoryRecord | AgentTeamDirectoryRecord`**
  Returns the latest eligible public record by stable ID without granting membership, communication, or file permissions.
* **`await negotiate_and_execute_migration(team: AgentTeam, target_parent: Agent | AgentTeam | ApprovalPrincipal | None, rationale: str) -> MigrationOperationResult`**
  Returns a durable request ID with `PENDING` while explicit principals deliberate and submit personal-email choices, or a terminal `EXECUTED`, `DENIED`, or `STALE` result after topology revalidation.
* **`inspect_migration_request(request_id: str) -> MigrationRequest`**
  Returns a detached copy of a durable migration request for trusted-host inspection.
* **`await save_state(path: Optional[str] = None, full: bool = True)`**
  Queues and waits for a versioned snapshot commit, rejecting new or already-waiting saves while state restoration or shutdown owns the runtime.
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
  Rejects new work, cancels outstanding external LLM waits and local admission work, flushes all accepted persistence changes without a timeout, and releases the exclusive database writer lease. `ATTManager` also supports `async with`.
* **`await flush_callbacks()`**
  Waits for observational callbacks accepted so far, including worker-thread events awaiting transfer to the dispatcher.
* **`await request_health_assessment(subject: HealthSubject, evidence: Mapping) -> HealthAssessmentAdmission`**
  Host-only durable admission of explicitly permitted evidence; duplicate live assessment generations coalesce.
* **`await wait_for_health_assessment(audit_id) -> AuditResult`** / **`await cancel_health_assessment(audit_id)`**
  Observe or explicitly cancel one bounded assessment; cancelling its observer does not cancel it.
* **`register_semantic_health_detector(detector, *, evidence_provider)`**
  Host-only binding of a runtime detector and explicit authorized evidence producer; also requires `health.semantic_detection_enabled=True`.
* **`await report_integrity_fault(subject, fault_code, *, protect)`**
  Executes an immediate synchronous trusted guard and records an incident; a failed guard is recorded with its exception type and then propagated, without storing the exception body.
* **`inspect_health_incident(incident_id, *, actor=None)`** / **`await claim_health_incident(incident_id, *, actor=None)`**
  Inspect or claim under live Host or actual-parent authority, independently of notification presentation and mail read state.
* **`await acknowledge_health_incident(incident_id, occurrence_count, *, actor=None, claim_token=None)`**
  Acknowledges only the exact occurrence generation; an Agent handler must present its exact claim token.
* **`async with manager.handle_health_incident(incident_id, actor=...)`**
  Releases a claim on handling failure or cancellation; successful block exit does not implicitly acknowledge it.
* **`await clear_health_incidents(incident_ids)`**
  Host-only explicit acknowledgement of selected incidents without deleting retained evidence.

The discovery models are exported from `ai_team_team`.

`EntityDiscoveryResult` distinguishes requested and actual ranges and includes `maximum_index`, `total_results`, `returned_count`, and detached `items`.

See [Agent and AgentTeam Discovery](../Agent_and_AgentTeam_Discovery.md) for exact public fields, strict validation, lifecycle scope, ordering, and live-pagination behavior.

### Callbacks

Callbacks may be synchronous or asynchronous. ATT dispatches them in order on a background channel; slow callbacks do not block personal activity, and callback exceptions are logged without changing core outcomes.

Thread emissions wake the owning event loop and preserve the same acceptance order as event-loop emissions.

Constructing the manager in that loop or entering `async with manager` establishes the callback loop; events emitted before a loop is available remain deferred until it is bound or flushed.

Callbacks receive explicit event metadata and do not inherit Agent or AgentTeam invocation authority.

Each observation runs in its own task, so callback self-cancellation is logged without cancelling the dispatcher or preventing the next observation from running.

Closing the manager cancels observation dispatch without waiting indefinitely for a callback that suppresses cancellation; shutdown does not promise to deliver the remaining queued observations.

* **`on_system_event: Callable[[str, dict], None | Awaitable[None]] | None`**
  Receives ordered metadata-only runtime, governance, resource, lifecycle, and health observations without private bodies or invocation authority.

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

## 🔍 Supervisory AgentTeams

Health assessments create fresh real managed privileged ATs through common staged team creation and personal activity.

They receive a fixed restricted tool profile rather than ordinary discovery, private-file, delegation, membership, chat, or background authority.

Every predefined auditor must submit a valid finding before a strict majority forms a conclusion; missing findings, ties, failure, or total deadline expiry produce `UNKNOWN`.

`AuditResult.status` and `operational_status` remain independent and cannot authorize business repair or model/permission changes.

Completed or interrupted assessments retain evidence and historical identity snapshots, not reusable audit people or active teams.

See [Health Supervision](../Supervisory_Team.md) for thresholds, evidence privacy, deadlines, and explicit incident acknowledgement.

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

### Personal Activity Controls

The continuing-person runtime adds `set_activity_intent(intent)` for explicit idle or finite sleep, and `set_operation_scope(scope)` for a validated scope transition after the complete batch.

These tools accept no Agent override, and ordinary text, silence, or a tool failure does not implicitly choose idle.

See the [Phase 2 runtime contract](../dev/autonomous_activity/Phase_2.md) for checkpoint, quota, sleep, and incomplete-replacement boundaries.

These tools are automatically registered and bound to all agent teams by default. ReAct agents can invoke them using standard positional/keyword call syntax:

### Entity Discovery

* **`list_entities(entity_type: str = "all", start_index: int = 1, end_index: Optional[int] = None) -> JSON`**
  Lists public Agent, AgentTeam, or combined records with inclusive entity-position pagination.
* **`search_entities(keywords: List[str], entity_type: str = "all", start_index: int = 1, end_index: Optional[int] = None) -> JSON`**
  Uses nonblank string keywords with case-insensitive OR matching over the same public directory fields.
* **`inspect_entity(entity_type: str, entity_id: str) -> JSON`**
  Inspects an eligible Agent or AgentTeam by its stable ID; `"all"` is not valid for inspection.

These tools are available to active ordinary Agents in both AgentTeam and personal interactions and never accept an acting-Agent override.

Neither the global directory nor the full topology is automatically injected into model prompts.

### Spawning & Communication

* **`dispatch_subagent(task: str, team_purpose: str, member_configs: Optional[dict] = None, existing_member_ids: Optional[List[str]] = None, system_instructions: str = "", is_public_visible: bool = False, initial_documents: Optional[dict] = None, initiator_joins: bool = False, unanimous_acceptance_action: str = "require_confirmation", late_join_policy: str = "disabled") -> str`**
  Returns creation references immediately for an all-new child, or `PENDING_RESPONSES` with an exact-consent request for existing identities; initial instructions are addressed mail, not synchronously awaited child work or a completion certificate.
* **`list_agent_inbox(unread_only: bool = True) -> str`** / **`mark_agent_inbox_read(message_ids: Optional[List[str]] = None) -> str`**
  Lists or acknowledges persistent notifications for the current invocation-scoped Agent identity.
* **`open_agent_mail(message_id: str) -> JSON`**
  Opens only the current Agent's own email and expands its governance case without changing its read receipt or voting.
* **`submit_governance_choice(case_id: str, choice: BooleanGovernanceChoice | ModelGovernanceChoice) -> JSON`**
  Submits `{"approved": true | false, "reason": "..."}` for communication or migration, or `{"model_alias": "eligible-alias", "reason": "..."}` for parent failover.
  Only explicit strictly validated choices count; repeated identical submissions return `ALREADY_SUBMITTED`, changed accepted ballots are rejected, and obsolete cases return `CLOSED`.
* **`list_governance_requests(pending_only: bool = True) -> JSON`**
  Lists the current Agent's eligible cases, including outstanding requests whose emails have already been marked read.
* **`propose_team_formation(proposal, organizational_parent="none") -> JSON`**
  Publishes the initiator's validated design directly without a mandatory draft.
* **`prepare_team_formation_draft(objective, candidate, request_id=None, organizational_parent="none") -> JSON`** / **`inspect_team_formation_draft(draft_id) -> JSON`** / **`publish_team_formation_draft(draft_id) -> JSON`**
  Validate, inspect, and explicitly publish the current person's own optional artifact; parent choices are `none`, `self`, or `current_team`.
* **`inspect_team_formation(request_id: str) -> str`** / **`revise_team_formation(request_id: str, base_revision: int, changes: TeamFormationRevisionPatch) -> str`**
  Lets the current Agent inspect a proposal or, when it is the initiator, commit an exact material revision that renews consent.
* **`respond_team_invitation(request_id: str, proposal_revision: int, attitude: Optional[str] = None) -> str`**
  Publishes `accepted`, `declined`, or `explicitly_ignored` for the exact reviewed revision; choosing `None` deliberately remains externally indistinguishable from no response.
* **`create_team_from_formation(request_id: str, proposal_revision: int) -> str`** / **`abandon_team_formation(request_id: str, proposal_revision: int, reason: str = "") -> str`**
  Lets the initiating Agent commit an eligible accepted subset or abandon the exact current proposal revision.
* **`decide_team_formation_late_join(request_id: str, invitee_agent_id: str, proposal_revision: int, approved: bool) -> str`**
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
* **`list_peer_messages() -> JSON`** / **`read_peer_message(message_id: str) -> JSON`**
  Lists endpoint-authorized references or explicitly reads a message after a live membership check; mail presentation alone never injects its body.

### Technical Health Attention

* **`list_health_incidents(pending_only: bool = True) -> JSON`** / **`inspect_health_incident(incident_id: str) -> JSON`**
  Lists permitted incident references or inspects their retained technical evidence, without intervention authority.
* **`claim_health_incident(incident_id: str) -> JSON`**
  Explicitly claims the current occurrence generation for authorized handling.
* **`acknowledge_health_incident(incident_id: str, occurrence_count: int, claim_token: str) -> JSON`**
  Acknowledges only the claimed generation; newer evidence remains pending and mail read state is independent.

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

* **`request_migration(target_parent: ApprovalPrincipal | None, rationale: str) -> JSON`**
  Requests to migrate the current invocation-scoped team under the configured policy and returns a durable `request_id` with `PENDING` instead of synchronously waiting for another Agent's approval.
* **`inspect_migration_request(request_id: str) -> JSON`**
  Lets the moving, target, or original-parent AgentTeam inspect its request without deciding for another approval principal.

### Selective Episodic Memory

These tools are visible only when `episodic_memory.enabled=True` and are always scoped to the current active Agent identity.

* **`search_memories(query: Optional[str] = None, tags: Optional[List[str]] = None, team_id: Optional[str] = None, invocation_id: Optional[str] = None, limit: int = 20, cursor: Optional[str] = None) -> MemorySearchResult`**
  Searches only the current Agent's active Memory Cards.
* **`recall_memory(memory_id: str, start_line: int = 1, end_line: Optional[int] = None, start_character: int = 1, character_count: Optional[int] = None, expected_segment_version: Optional[str] = None) -> MemoryRecallResult`**
  Returns a token-bounded historical observation. Partial results expose `next_line`, `next_character`, and `segment_version`; pass them into the next call to continue without gaps or duplication.
* **`keep_memory_in_context(memory_id: str, note: Optional[str] = None) -> MemoryOperationResult`**
  Retains a compact reference only after the card was recalled in the same personal invocation.
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

## Registered Execution and Background Tasks

Host methods require an explicit registered `actor`, while model tools derive the owner from the current personal invocation and accept no actor, sender, executor, or policy override.

| Host method | Result and contract |
| --- | --- |
| `register_executor(name, executor)` | Registers a unique runtime-only binding implementing `async execute(call)`, with a real `cancel(execution_id)` hook when provider or isolated cancellation is declared. |
| `await start_background_task(tool_name, arguments, *, actor, scope=None, description="", labels=())` | Returns `BackgroundTaskHandle` after admission commits, without waiting for queued or running execution to finish. |
| `list_background_tasks(*, actor, status=None, query=None, limit=50, cursor=None, include_foreground=False)` | Returns an owner-filtered `TaskPage`; search covers metadata, never protected result bodies. |
| `inspect_background_task(execution_id, *, actor)` | Returns `TaskView` with independent execution, health, attention, and uncertainty facts, without a body. |
| `await read_background_task_result(execution_id, *, actor, start_line=1, end_line=None, start_character=1, character_count=None, expected_file_version=None)` | Returns a token-bounded `FileReadResult` after source-policy and owner revalidation; does not acknowledge attention. |
| `await cancel_background_task(execution_id, *, actor)` | Returns `TaskControlResult` distinguishing confirmed cancellation, an unconfirmed stop, and an already terminal outcome. |
| `await acknowledge_background_task(execution_id, *, actor)` | Acknowledges attention without changing outcome, reading a source message, or deleting history. |
| `await report_execution_health(execution_id, health, evidence_kind, evidence=None)` | Trusted live-executor evidence only, limited to declared signals and classified counters/status rather than arbitrary text. |

The model tool family additionally exposes `search_background_tasks(query, ...)` as an explicit metadata-search convenience.

The default callable executor confirms the registered callable's return, and a returned remote job ID alone confirms only the operation that actually returned it, not remote job completion.

Custom shared-resource coordination uses a synchronous `resource_resolver(scope, arguments)` returning `ResourceClaim(namespace, resource_id, path="", access="write", subtree=False)` values.

Foreground-only tools retain their personal Session while sharing admission, resource coordination, executor dispatch, and result authorization with background-capable tools, including mixed self-modification contracts.

Undeclared foreground tools use conservative global exclusion, while pure self-modification controls do not implicitly acquire shared file access; a tool holding any shared reservation cannot synchronously wait on nested personal model activity.

Cancellation of a stop observer does not undo an accepted control request, and cancellation or close does not discard an operation's already returned outcome while its local result commit is pending.

Library claims must name registered physical targets and canonical virtual paths, while unresolved independence receives conservative exclusion.

Nonempty global or external resource claims preserve opaque source provenance and fail closed when retained-result source revalidation is required; an explicit empty resolver may declare a source-free operation.

Authoritative framework errors in stop hooks propagate from cancellation and `close()` independently of uncertain external stop outcomes, including late synchronous hook failures observed before shutdown completes.

The automatic threshold changes foreground waiting rather than the operation's identity or retry policy, and later outcomes notify only the same owner.

See [Phase 4](../dev/autonomous_activity/Phase_4.md) and the [execution flowchart](../flowcharts/Background_Tasks.md) for admission, resource, privacy, cancellation, and restore boundaries.
