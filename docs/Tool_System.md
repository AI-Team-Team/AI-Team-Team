# Tool Execution & Development System

This document outlines both the internal execution strategies of the framework and the guidelines for developers extending the system with custom native tools and interceptors.

## 1. Architectural Overview

The [personal runtime](Autonomous_Agent_Runtime_Architecture/README.md) uses the shared parsers, strict `Tool` validation, auditor, typed executor, and privacy helpers in continuing invocations.

The [executor integration reference](Autonomous_Agent_Runtime_Architecture/Executor_Integration.md) defines execution-contract fields, custom binding hooks, resource resolvers, and typed health evidence.

Its ordinary tool failures remain observations, and technical budgets yield fairly without ending the person's activity.

Native batches keep one captured scope and apply explicit idle, sleep, or scope controls only after every required observation is complete.

Governance, formation, and restricted temporary audits use this same runtime while their own services retain consent, authority, and outcome rules.

Foreground execution evidence commits before each real attempt, including opted-in retries; undeclared custom tools cannot detach into background work.

The [registered execution service](Autonomous_Agent_Runtime_Architecture/Model_and_Tool_Execution.md) owns explicitly background and automatically detached operations independently of the foreground observer, with canonical resource exclusion and factual cancellation.

Use [Personal Activity](Personal_Activity.md), [Personal Conversations](Personal_Conversations.md), and [Background Tasks](Background_Tasks.md) for integration behavior, and [Autonomous Agent Runtime Architecture](Autonomous_Agent_Runtime_Architecture/README.md) for internal coordination.

Provider-neutral request and tool contracts keep the common personal runtime independent of concrete model SDKs.

```text
Personal admission -> one continuing Agent -> bounded provider request
                  -> Text Action or Native ToolCall
                  -> common validation, authorization and ToolExecutor
                  -> committed observation and checkpoint
                  -> continue, explicit idle or finite sleep
```

The system supports two core execution modes:

1. **Text ReAct Mode (`"text_react"`)**: A bounded step-by-step loop alternating between Thought, Action, and Observation.
   A balanced character scanner recognizes nested delimiters, quotes, triple quotes, escapes, multiline values, Markdown fences, and Unicode before the literal-only AST parser validates arguments.
2. **Native Tool Calling Mode (`"native"`)**: Executes structured tool invocations directly using LLM function calling schemas, running multiple tool calls concurrently in parallel.

## 2. One Runtime with Two Provider Protocols

The common personal runner supports Text ReAct and Native tool calling without separate business, governance, or audit inference engines.

Every ordinary request composes the person's own instructions, factual selected scope, currently available tools, and the bounded Working Context.

Native adapters receive `Optional[List[Tool]]`, normalize responses to `LLMResponse`, and translate Tool schemas into the provider's wire format.

Text mode uses the balanced Action scanner and literal-only parser before the same executor.

A model answer alone is not a publication, ballot, completion declaration, or stop request.

`activity.model_requests_per_invocation` and `activity.tool_batches_per_invocation` bound one scheduling quantum, not an all-member round.

The safe auto probe accepts only a synchronous literal boolean `True`.

Exceptions, awaitables, and other invalid outcomes received by the manager probe emit a sanitized event and fall back to Text ReAct; forced Native mode does not probe.

The generator-handler wrapper currently normalizes its inner probe before the manager sees it: non-`True` returns become `False`, and caught exceptions can use the configured capability flag.

Those paths do not reliably preserve the invalid-outcome diagnostic or fallback contract; the [wrapped-probe issue](../todo.md#wrapped-handler-capability-probe) tracks the implementation gap.

Handler integrations should declare a synchronous boolean capability explicitly or select a forced protocol after validating their adapter.

## 3. Tool Contract, Schema Generation, and Validation

The personal runtime passes provider-neutral `Tool` objects to the provider adapter.

The personal runner and adapters use one provider-neutral contract: `tools: Optional[List[Tool]]`.

Provider adapters convert each `Tool.json_schema` to their SDK's wire format.

The resolver can dynamically build schemas from:

1. **Handwritten Schema**: A standard python dictionary containing raw JSON Schema properties.
2. **Pydantic Model**: A `BaseModel` subclass.
3. **TypedDict Class**: A `typing_extensions.TypedDict` class.
   Portable tool schemas across Python 3.11–3.13 must import `TypedDict`, `Required`, and `NotRequired` from `typing_extensions`; Pydantic does not support `typing.TypedDict` on Python 3.11.
4. **Function Signatures**: If no schema is provided, the resolver parses parameter defaults and type annotations.

Tool registration validates every generated or handwritten schema with JSON Schema Draft 2020-12.

Every invocation first binds the Python signature, then applies strict Pydantic JSON validation for actual and nested types, and finally validates the original argument object against the tool's Draft 2020-12 schema.

Automatic schemas support `Annotated`, `Literal`, Enum, `BaseModel`, `TypedDict`, list, dict, Union, and nested combinations; typed dictionaries and mappings include their `additionalProperties` contracts.

```python
from typing_extensions import NotRequired, TypedDict

class WeatherArguments(TypedDict):
    city: str
    units: NotRequired[str]
```

Text prompts render every currently available tool using `text_tool_schema_mode`.

Compact mode recursively shows names, required fields, types, defaults, and nested structures; full mode emits the complete schema; `compact_with_examples` adds examples.

`tool_prompt_modes` overrides a specific tool, followed by `Tool.prompt_schema_mode`, followed by the global default.

## 4. Shared Tool Execution and Classified Results

Unlike the sequential execution loop of the text ReAct mode, the native strategy runs independent tool requests **concurrently in parallel** to minimize network latency.

The runner waits for every required observation in a captured Native batch before applying scope or intent changes.

Each call passes through registered execution admission and resource coordination rather than invoking a custom callable directly from a gather loop.

Cancellation fences outstanding sibling authority and settles accepted local commits without indefinitely waiting for an external provider.

Text and Native protocols share the same executor for invocation-scoped Agent/AgentTeam context, auditing, validation, retry, callback metadata, and result conversion.

`ToolResult.status` is one of `success`, `invalid_arguments`, `denied`, `business_error`, `transient_error`, `internal_error`, or `unknown_tool`; failures also carry `error_kind` and `attempts`.

Framework classification never depends on a returned string prefix, so a custom tool may legitimately return ordinary text beginning with `Error:`.

Built-in and custom tools can raise `ToolArgumentError`, `ToolPermissionError`, `ToolBusinessError`, or `RetryableToolError`.

Permission and business outcomes are never replayed automatically and do not become personal health failures.

Execution replay is disabled by default; `retry_safe` requires both `Tool(retry_safe=True)` and `RetryableToolError`, while `typed_transient` replays any `RetryableToolError` and makes the host responsible for idempotency.

Invalid arguments return typed observations for voluntary correction without terminating a team or consuming a legacy turn-correction allowance.

Repeated same-category invalid calls feed the configured health detector, whose threshold requests assessment rather than intervention.

`max_tool_execution_retries` counts extra eligible execution attempts and uses `tool_execution_retry_backoff_factor` for exponential delay.

### Runtime Tool Availability

| Profile | Tool view |
| --- | --- |
| Ordinary personal scope | Personal mail, private files, discovery, eligible formation and governance tools, historical chat reads, direct chat, activity controls, task tools, and compatible custom tools. |
| Ordinary AgentTeam scope | The personal view plus current-team publication, peer communication, shared-file and organizational operations authorized by that membership. |
| Restricted supervisory scope | Only admitted evidence, scoped audit communication, explicit findings, and idle controls; no ordinary business, private-file, recruitment, or background authority. |

The actual ordinary view is assembled per request, including runtime-added chat tools, activity controls, and task queries beyond the static default-tool registry.

Dynamic delegation, current depth, membership-voting configuration, optional episodic memory, live membership, and audit restrictions further determine visibility.

Host method signatures are not model-tool signatures: a model's `send_team_message(markdown, reply_to=None)` captures its AT and cannot receive a Host `actor` or team override.

The [model-tool reference](user/API_Reference.md#-built-in-react-tools-reference) lists each runtime family's actual parameters separately.

## 5. Tool Registration & Development

ATT derives tool names, descriptions, defaults, and argument schemas from Python function signatures, type hints, and docstrings unless registration supplies explicit metadata.

```python
def check_server_health(region: str, max_retries: int = 3) -> str:
    """
    Pings the production cluster to return server health metrics.
    
    Arguments:
        region (str): The geographical region (e.g., 'us-east', 'eu-west').
        max_retries (int): Maximum ping retries before failure.
    """
    return f"Server in {region} is healthy."

# Registration
manager.register_tool(
    name="check_server_health",
    description="Pings the production cluster to return server health metrics. Arguments: region (str), max_retries (int).",
    func=check_server_health,
    memory_capture="metadata_only",
)
```

`memory_capture="metadata_only"` is the default and prevents observation bodies or tool arguments from becoming episodic recall content.

Only an explicit `memory_capture="content"` opt-in permits a tool observation body to enter the sanitized Journal segment used for a Memory Card.

### Private workspace tools

The built-in private tools (`list/read/write/delete/move_private_file`) have no owner or library parameter.

They resolve the current Agent from invocation `ContextVar` state and fail closed without it.

`publish_private_file` copies an ordinary private file to the current team's built-in DocLib after a live target `WRITE` check; `move_library_file` requires `WRITE` on both team-library paths.

Tool observations may contain content only when the owner explicitly reads a private file.
That observation expires when the current reasoning invocation ends and is replaced by a redacted marker before the shared AI can run for another team.

Optional episodic-memory recall uses the same transient-observation boundary and replaces the body with `[Historical memory recalled: <memory_id>]` at the end of the invocation.

Operational callbacks never contain private file bodies.

## 6. Host Runtime Dependencies (`tools_context`)

`tools_context` is a Host-owned runtime dependency mapping whose reserved `att_manager` binding is used by the built-in tool registry.

Custom tool dependencies must be bound explicitly by the Host, for example through a closure before registration.

A parameter named `context` receives ordinary signature and schema validation; it does not request automatic trusted-resource injection.

```python
# 1. Register global resources
manager.register_tools_context({
    "db_connection": my_sql_db
})

# 2. Bind the Host dependency without exposing it as a model argument.
def bind_database_tool(db):
    def query_database(sql_query: str) -> str:
        return str(db.execute(sql_query))
    return query_database

query_database = bind_database_tool(manager.tools_context["db_connection"])
manager.register_tool(query_database)
```

## 7. Tool Interception (ToolAuditor Hooks)

A **ToolAuditor** hook inspects validated tool arguments before execution and may deny the call.

```python
def audit_query_database(sql_query: str) -> tuple[bool, str]:
    if "DROP" in sql_query.upper():
        return False, "Security Violation: Destructive SQL commands are prohibited."
    return True, "Query approved."

# Attach the auditor
manager.register_tool_auditor("query_database", audit_query_database)
```

If the auditor returns `False`, execution is blocked and the classified denial returns as an observation; ordinary denial is not evidence of poor Agent health.

## 8. Provider Availability and Context Compaction

`activity.llm` controls typed provider retry, total sequence deadlines, and recovery boundaries.

Timeouts, rate limits, recoverable service failures, and connection faults are resource-availability evidence rather than automatic Agent-health accusations.

Authentication, validation, and programming errors are not retried through string matching.

Derived context compaction preserves complete tool-call/result boundaries and source references while the sanitized Journal remains retained.

It does not invoke a separate summarizer that changes personal identity or silently replaces one team's memory with another's.

## 9. Continuing Activity and Failure Boundaries

`activate_agent()` admits one continuing person, while `execute_agent_interaction()` observes an answer with its actual invocation provenance.

The Agent explicitly chooses idle or finite sleep through `set_activity_intent`.

`set_notification_suppression(preference)`, `list_notification_suppressions(active_only=True)`, and `remove_notification_suppression(preference_id)` control only the invoking person's ordinary reminders.

Preferences may be permanent or timed and select all ordinary arrivals, a source Agent, or an active ordinary AgentTeam without granting any access to that source.

Timed preferences use the same Host-configurable positive day, hour, and minute bounds as sleep, and protected system notices and the finite sleep deadline remain effective.

Ending suppression produces eligible source counts without titles, previews, bodies, read changes, or replay of covered individual reminders, and any remaining preference still filters the summary.

Classified ordinary tool failures become personal observations, and a failed provider may enter a resource-unavailable state without terminating other people.

Cancellation, shutdown, persistence failures, and integrity faults retain their distinct propagation and settlement boundaries.

Governance authority requires complete exact-case explicit ballots, never a transcript or merely successful model output.

### Entity Discovery Tools

`list_entities`, `search_entities`, and `inspect_entity` let active ordinary Agents discover public people and organizations explicitly in both Text ReAct and Native modes, including personal interactions without a team.

They expose only existing directory fields, never select collaborators or grant consent, communication Agreements, or DocLib ACLs, and remain available independently of delegation depth and optional episodic memory.

Prompt assembly advertises discovery tools without injecting the full global Agent directory or AgentTeam topology.

The operations are read-only, while their explicit observations may join the calling Agent's ordinary memory.

See [Agent and AgentTeam Discovery](Agent_and_AgentTeam_Discovery.md) for strict argument validation, inclusive entity-position ranges, keyword semantics, lifecycle filtering, and live-page behavior.

### Personal-Inbox Governance Tools

Governance emails are announced through the eligible Agent's ordinary interaction context, using its existing instructions, history, memory, and invocation lock.

`open_agent_mail(message_id)` opens only that Agent's own email and public request without changing the read receipt or supplying a vote.

`submit_governance_choice(case_id, choice)` records an explicit immutable strict boolean or eligible model-alias choice, independently of mailbox state.

`list_governance_requests(pending_only=True)` includes unanswered eligible requests even when their emails are already read.

The Agent may open without choosing, defer a choice, or leave the email unanswered; no missing response becomes consent.

Public requests and submitted reasons join the same ordinary history, while optional episodic memory stays optional and private document content is never automatically loaded for voting.

Personal turns without an AgentTeam expose only identity-scoped tools and do not acquire team permissions or a fabricated team context.

If cancellation or a fatal error interrupts a Native tool batch, unfinished sibling invocations are cancelled and settled before the Agent's invocation lock is released.

Missing tool replies receive a safe interruption marker so the next ordinary interaction retains a valid provider message sequence without assuming that already committed effects were rolled back.

The four team-formation attitudes remain a separate domain vocabulary, and marking a formation email read cannot accept, decline, explicitly ignore, or withdraw a public attitude.

### Personal Chat Tools

The continuing personal runtime exposes `send_direct_message`, `list_team_messages`, `list_direct_messages`, `read_chat_message`, `edit_chat_message`, `withdraw_chat_message`, `control_chat_message`, `set_chat_details`, `inspect_direct_relationship`, `list_friendship_requests`, `request_friendship`, `respond_friendship`, and `control_direct_relationship` in both Text and Native modes.

`send_team_message(markdown, reply_to=None)` is available only in captured AgentTeam scope and does not accept a sender, actor, policy, or team override.

Direct send tools accept the recipient's Agent ID, while all personal controls derive their owner from the actual invocation.

`read_chat_message` supports line and Unicode character continuation, content-token limits, and expected source versions, just like model-facing file reads.

Chat previews and mail presentation do not mark messages read, cast votes, accept friendship, or publish model answers.

Chat tools use the common continuing runtime and do not introduce a team-discussion engine.

`list_chat_reminders(message_id=None, limit=50, cursor=None)` inspects owner-authorized captured unread previews separately from current source retrieval, including after withdrawal.

See [Personal Conversations](Personal_Conversations.md) for frozen history, current-source withdrawal, recipient-owned reminders, exact receipts, and the archive-finalization boundary.

### Personal Background Task Tools

The personal runtime exposes `start_background_task(tool_name, arguments, description="", labels=None)`, `list_background_tasks`, `search_background_tasks`, `inspect_background_task`, `read_background_task_result`, `cancel_background_task`, and `acknowledge_background_task` in both Text and Native modes.

Owner and original scope come from the invocation rather than model-supplied actor, executor, or policy overrides.

Only the invocation's available tools with an explicit background declaration may be started, and self-modifying operations remain foreground-only.

Undeclared custom tools also remain foreground-only, but their conservative global resource reservation participates in the same exclusion mechanism as background work rather than bypassing it.

Every registered foreground-only operation shares admission, resource resolution, executor dispatch, and final source authorization with background-capable operations while keeping the original personal Session.

Self-modification does not bypass explicit claims or mixed-effect contracts, and the configured executor runs instead of an unrelated callable placeholder.

Custom personal execution controls must declare their self-modifying contract; controls without shared claims can coordinate personal activity, but no tool may hold shared resource reservations while synchronously waiting on nested model activity.

A pure self-modification declaration does not implicitly grant file access, and a nonempty global resource claim retains opaque source provenance rather than imply a source-free result.

Automatic detachment defaults to 120 seconds of actual execution, including retries and backoff without a second dispatch.

The original Native tool call receives exactly one normal result or structured task handle, with later output delivered through a personal notification and explicit token-bounded result reading.

Task summaries contain counts rather than bodies, and attention acknowledgement neither changes execution outcome nor deletes retained results.

Managed-link bindings and actual physical paths are revalidated at resource access and commit boundaries, and failure bodies require the same final source authorization as successful results.

Accepted stop requests survive observer cancellation, while an operation that has already returned finishes local result settlement without being misreported as cancelled.

Stop-hook framework errors remain observable through cancellation and shutdown even when the external stop outcome is uncertain or a synchronous hook finishes after its grace period.

Executors declaring `suspension="provider"` supply `async suspend(execution_id)` and must return literal `True` to acknowledge suspension during lifecycle shutdown.

A suspension request alone is not a paused outcome, and a missing acknowledgement falls back to termination without inventing a terminal execution state or automatic resumption.

See [Lifecycle and Recovery](Autonomous_Agent_Runtime_Architecture/Lifecycle_and_Recovery.md) and [Recovery and Publication](Database/Recovery_and_Publication.md) for retained owner death, resource fencing, countdown recovery, and exact publication boundaries.

Heartbeat and progress timeout decisions serialize with accepted samples and retain crossed deadlines during slow observation commits, preventing stale stalls and lost monitor wakeups.

Private reads remain transient, and source revocation prevents new source access even when the default retained-result policy permits reading a previously lawfully committed personal result.

## 10. Persistence & Serialization

To support complete state recovery and shared-agent provenance, the `AgentMessageModel` table stores structured tool calls plus invocation context:

* **`tool_calls`**: A native SQLite JSON column storing the list of structured tool executions.
* **`tool_call_id`**: A string column mapping the message to its specific trigger.
* **`name`**: A string column specifying which tool was executed.
* **`team_id`**: The team active for this message.
* **`invocation_id`**: The personal invocation that produced this message.
* **`source_chat_message_id`**: The authorized chat source explicitly read into the personal observation.
