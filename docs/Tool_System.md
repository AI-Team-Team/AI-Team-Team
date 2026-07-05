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

1. **Text ReAct Mode (`"text_react"`)**: A classic step-by-step loop alternating between Thought, Action (parsed via regex), and Observation.
2. **Native Tool Calling Mode (`"native"`)**: Executes structured tool invocations directly using LLM function calling schemas, running multiple tool calls concurrently in parallel.

## 2. Pluggable Reasoning Strategies

Reasoning strategies are encapsulated as pluggable classes inheriting from `BaseReasoningStrategy`.

### Class Hierarchy

* **`BaseReasoningStrategy`**: Abstract class declaring the `execute(...)` interface.
* **`TextReactReasoningStrategy`**: Implements the XML-tag and regex-parsed ReAct execution loop.
* **`NativeReasoningStrategy`**: Implements native tool-calling loop:
  1. Requests active native `Tool` objects from the registry.
  2. Submits prompt messages and native `Tool` objects to the LLM client adapter (Thorough Abstraction).
  3. Receives structured `tool_calls` inside the unified `LLMResponse`.
  4. Spawns parallel executions for all `tool_calls` concurrently.
  5. Feeds `ToolResult` messages back to the history buffer and repeats.

### Strategy Auto-Routing

During execution, if the `tool_calling_mode` in `ATTConfig` is set to `"auto"`, the team queries the agent's LLM client:

```python
if hasattr(agent.llm_client, "supports_native_tool_calling") and agent.llm_client.supports_native_tool_calling():
    strategy = NativeReasoningStrategy()
else:
    strategy = TextReactReasoningStrategy()
```

## 3. Thorough Abstraction & Automated Schema Generation

The framework operates under a **Thorough Abstraction Paradigm**. Instead of eagerly converting tools into JSON schemas at the reasoning layer and passing weak `Dict` structures to clients, the strategies fetch and pass native `Tool` objects natively down the stack.

The actual schema resolution is strictly delegated to the active `LLMClientAdapter`. The resolver can dynamically build schemas from:

1. **Handwritten Schema**: A standard python dictionary containing raw JSON Schema properties.
2. **Pydantic Model**: A `BaseModel` subclass.
3. **TypedDict Class**: A standard python `TypedDict`.
4. **Function Signatures**: If no schema is provided, the resolver parses parameter defaults and type annotations.

## 4. Concurrent Parallel Tool Execution

Unlike the sequential execution loop of the text ReAct mode, the native strategy runs independent tool requests **concurrently in parallel** to minimize network latency.

```python
# Concurrently gather all tool executions in parallel
results = await asyncio.gather(*[
    run_tool(call.name, call.arguments) for call in response.tool_calls
])
```

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
    func=check_server_health
)
```

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

* **Transient API Recovery**: The `generate_with_retry` wrapper automatically handles unknown SDK exceptions via exponential backoff (`llm_max_retries`, `llm_retry_backoff_factor`).
* **Prompt Injection Guarantee**: During pruning, the active user `prompt` is forcefully appended to the message queue strictly *after* the memory compression block finishes, guaranteeing it is never swallowed.

## 9. Persistence & Serialization

To support 100% state recovery after crashes, the `AgentMessageModel` table contains three columns mapping to the structured tool calls:

* **`tool_calls`**: A native SQLite JSON column storing the list of structured tool executions.
* **`tool_call_id`**: A string column mapping the message to its specific trigger.
* **`name`**: A string column specifying which tool was executed.
