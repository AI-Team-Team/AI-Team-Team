# Tool Execution & Development System

This document outlines both the internal execution strategies of the framework and the guidelines for developers extending the system with custom native tools and interceptors.

## 1. Architectural Overview

To make reasoning execution vendor-independent and model-agnostic, the ATT framework decouples the reasoning loop from individual LLM clients. It implements a Strategy Pattern to govern how agent turns are executed.

```plaintext
                   ┌──────────────────────────┐
                   │    Agent / AgentTeam     │
                   └────────────┬─────────────┘
                                │ Calls execute_reasoning_step()
                                ▼
                   ┌──────────────────────────┐
                   │   Reasoning Strategy     │
                   │    Selection Route       │
                   └──────┬────────────┬──────┘
                          │            │
          If Native Mode  │            │ If Text ReAct Mode
          or Auto capable │            │ or Auto fallback
                          ▼            ▼
             ┌────────────────┐    ┌────────────────┐
             │ Native Strategy│    │ ReAct Strategy │
             │   (Parallel)   │    │  (Sequential)  │
             └────────────────┘    └────────────────┘
```

The system supports two core execution modes:

1. **Text ReAct Mode (`"text_react"`)**: A bounded step-by-step loop alternating between Thought, Action, and Observation. A balanced character scanner recognizes nested delimiters, quotes, triple quotes, escapes, multiline values, Markdown fences, and Unicode before the literal-only AST parser validates arguments.
2. **Native Tool Calling Mode (`"native"`)**: Executes structured tool invocations directly using LLM function calling schemas, running multiple tool calls concurrently in parallel.

## 2. Pluggable Reasoning Strategies

Reasoning strategies are encapsulated as pluggable classes inheriting from `BaseReasoningStrategy`.

### Class Hierarchy

* **`BaseReasoningStrategy`**: Abstract class declaring the `execute(...)` interface.
* **`TextReactReasoningStrategy`**: Implements the XML-tag and `Action: tool_name(...)` ReAct loop through the strict balanced parser.
* **`NativeReasoningStrategy`**: Implements native tool-calling loop:
  1. Requests active native `Tool` objects from the registry.
  2. Submits prompt messages and native `Tool` objects to the LLM client adapter (Thorough Abstraction).
  3. Receives structured `tool_calls` inside the unified `LLMResponse`.
  4. Spawns parallel executions for all `tool_calls` concurrently through the shared `ToolExecutor`.
  5. Feeds classified `ToolResult` messages back to the history buffer and repeats.

### Strategy Auto-Routing

During execution, if the `tool_calling_mode` in `ATTConfig` is set to `"auto"`, the team queries the agent's LLM client:

```python
if manager.probe_native_tool_capability(agent.llm_client, agent=agent, team=team):
    strategy = NativeReasoningStrategy()
else:
    strategy = TextReactReasoningStrategy()
```

The safe probe accepts only a synchronous literal boolean `True`.

Exceptions, awaitables, and non-boolean values emit a privacy-safe system event and fall back to Text ReAct; forced `"native"` mode does not probe.

## 3. Tool Contract, Schema Generation, and Validation

The framework operates under a **Thorough Abstraction Paradigm**. Instead of eagerly converting tools into JSON schemas at the reasoning layer and passing weak `Dict` structures to clients, the strategies fetch and pass native `Tool` objects natively down the stack.

Strategies and adapters use one provider-neutral contract: `tools: Optional[List[Tool]]`.

Provider adapters convert each `Tool.json_schema` to their SDK's wire format.

The resolver can dynamically build schemas from:

1. **Handwritten Schema**: A standard python dictionary containing raw JSON Schema properties.
2. **Pydantic Model**: A `BaseModel` subclass.
3. **TypedDict Class**: A `typing_extensions.TypedDict` class. Portable tool schemas across Python 3.11–3.13 must import `TypedDict`, `Required`, and `NotRequired` from `typing_extensions`; Pydantic does not support `typing.TypedDict` on Python 3.11.
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

```python
# Concurrently gather all tool executions in parallel
results = await asyncio.gather(*[
    executor.execute(call.name, kwargs=call.arguments) for call in response.tool_calls
])
```

Text and Native strategies share the same executor for invocation-scoped Agent/AgentTeam context, auditing, validation, retry, callback metadata, and result conversion.

`ToolResult.status` is one of `success`, `invalid_arguments`, `denied`, `business_error`, `transient_error`, `internal_error`, or `unknown_tool`; failures also carry `error_kind` and `attempts`.

Framework classification never depends on a returned string prefix, so a custom tool may legitimately return ordinary text beginning with `Error:`.

Built-in and custom tools can raise `ToolArgumentError`, `ToolPermissionError`, `ToolBusinessError`, or `RetryableToolError`.

Permission and business outcomes are never replayed and do not consume argument-correction opportunities.

Execution replay is disabled by default; `retry_safe` requires both `Tool(retry_safe=True)` and `RetryableToolError`, while `typed_transient` replays any `RetryableToolError` and makes the host responsible for idempotency.

`max_tool_argument_retries` counts model correction opportunities after the first invalid call.

A Native parallel batch consumes at most one correction opportunity regardless of how many calls are invalid.

`max_tool_execution_retries` counts extra eligible execution attempts and uses `tool_execution_retry_backoff_factor` for exponential delay.

## 5. Tool Registration & Development

ATT handles the heavy lifting of schema extraction. You only need to write standard Python functions with clear type hints and docstrings.

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

Tool observations may contain content only when the owner explicitly reads a private file. That observation expires when the current reasoning invocation ends and is replaced by a redacted marker before the shared AI can run for another team.

Optional episodic-memory recall uses the same transient-observation boundary and replaces the body with `[Historical memory recalled: <memory_id>]` at the end of the invocation.

Operational callbacks never contain private file bodies.

## 6. Shared Context Injection (`tools_context`)

Instead of relying on global variables, you should use the `tools_context`. ATT automatically attempts to inject it into any tool that defines a `context` parameter.

```python
# 1. Register global resources
manager.register_tools_context({
    "db_connection": my_sql_db
})

# 2. Define a tool that accepts the context
def query_database(sql_query: str, context: dict) -> str:
    db = context.get("db_connection")
    return db.execute(sql_query)
```

## 7. Tool Interception (ToolAuditor Hooks)

Allowing AI agents to execute Python functions autonomously poses significant safety risks. ATT provides a **ToolAuditor** interceptor pattern to block calls before execution.

```python
def audit_query_database(sql_query: str, context: dict) -> tuple[bool, str]:
    if "DROP" in sql_query.upper():
        return False, "Security Violation: Destructive SQL commands are prohibited."
    return True, "Query approved."

# Attach the auditor
manager.register_tool_auditor("query_database", audit_query_database)
```

If the auditor returns `False`, the execution is blocked, and the error reason is returned to the LLM agent as an observation.

## 8. Network Resilience & Memory Compression

* **Typed Transient API Recovery**: `generate_with_retry` retries only explicit timeout, connection, rate-limit, retryable service, or provider-status failures. Authentication, validation, programming, and other unclassified errors fail immediately. `llm_max_retries=0` performs one request without a retry, and `llm_retry_backoff_factor=0` retries without waiting.
* **Prompt Injection Guarantee**: During pruning, the active user `prompt` is forcefully appended to the message queue strictly *after* the memory compression block finishes, guaranteeing it is never swallowed.

## 9. Structured Turns and Member Failure Isolation

`execute_reasoning_step_detailed()` returns `AgentTurnResult`, while the text-compatible `execute_reasoning_step()` returns either the completed answer or `[Turn incomplete: ...]`.

`execute_team_discussion_detailed()` returns `DiscussionResult` with per-round turns, transcript, audit, and `COMPLETED` or `PARTIAL` status; `execute_team_discussion()` continues to return only the transcript.

The default `TurnFailurePolicyConfig(tool="isolate", llm="isolate")` ends only the affected member's current round when tool correction is exhausted or an LLM invocation fails.

Other members finish the round, the incomplete placeholder enters the transcript and next-round context, and the member starts the next round with a fresh correction budget.

Set either field to `"abort"` to stop the discussion instead.

Cancellation, manager shutdown, persistence failures, and framework state-integrity exceptions always propagate.

Strict governance discussions require every member turn to complete.

Any incomplete communication, migration, full-member ballot, or parent-failover discussion fails closed and leaves its request or approval pending instead of authorizing from a partial transcript.

## 10. Persistence & Serialization

To support complete state recovery and shared-agent provenance, the `AgentMessageModel` table stores structured tool calls plus invocation context:

* **`tool_calls`**: A native SQLite JSON column storing the list of structured tool executions.
* **`tool_call_id`**: A string column mapping the message to its specific trigger.
* **`name`**: A string column specifying which tool was executed.
* **`team_id`**: The team active for this message.
* **`discussion_id`**: The discussion invocation that produced this message.
