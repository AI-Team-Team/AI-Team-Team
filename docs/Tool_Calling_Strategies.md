# Dual-Mode Tool Calling & Reasoning Strategies Architecture

This document describes the design, implementation, and sequence flows of the **Dual-Mode Tool Calling & pluggable Reasoning Strategies** architecture implemented in the ATT (AI-Team-Team) framework.

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

This capability check ensures that capable models (e.g. GPT-4, Gemini Pro) automatically use fast, parallel native tool calling, while older or smaller local models fallback gracefully to text-based ReAct.

## 3. Thorough Abstraction & Automated Schema Generation

The framework operates under a **Thorough Abstraction Paradigm**. Instead of eagerly converting tools into JSON schemas at the reasoning layer and passing weak `Dict` structures to clients, the strategies fetch and pass native `Tool` objects natively down the stack. 

This strict separation of concerns prevents structural mismatch loops and infinite recursion during testing. The actual schema resolution is strictly delegated to the active `LLMClientAdapter`, which uses a robust `Schema Resolver` to automatically convert various pythonic types into standard API payloads. When registering a tool, you can pass:

1. **Handwritten Schema**: A standard python dictionary containing raw JSON Schema properties.
2. **Pydantic Model**: A `BaseModel` subclass. The resolver dynamically calls `.model_json_schema()` (or `.schema()`) to extract properties.
3. **TypedDict Class**: A standard python `TypedDict`. The resolver inspects type annotations using `typing.get_type_hints()` to build required parameters.
4. **Function Signatures**: If no schema is provided, the resolver reflects the python function's signature and parses parameter defaults, parameter type annotations, and the docstring first line to construct the JSON schema dynamically.

## 4. Concurrent Parallel Tool Execution

Unlike the sequential execution loop of the text ReAct mode, the native strategy runs independent tool requests **concurrently in parallel** to minimize network latency and improve agent response speeds.

When the LLM returns multiple `tool_calls` (e.g. fetching weather for multiple cities, or running multiple SQL queries), the Native Strategy runs them concurrently:

```python
# Concurrently gather all tool executions in parallel
results = await asyncio.gather(*[
    run_tool(call.name, call.arguments) for call in response.tool_calls
])
```

Each execution output is converted into a structured `ToolResult` and serialized into the agent's message queue.

## 5. Network Resilience & Transient API Recovery

Because autonomous multi-agent systems rely heavily on continuous LLM API integrations, the execution strategies implement robust, defensive fault tolerance via the `generate_with_retry` wrapper:

* **Transient Error Defaulting**: Unknown exceptions thrown by underlying provider SDKs are intentionally categorized as **Transient API Errors** rather than immediate terminal failures.
* **Exponential Backoff**: Transient errors trigger a configured exponential backoff loop (`llm_max_retries`, `llm_retry_backoff_factor`), drastically improving system stability during random API gateway timeouts or cloud provider jitter.

## 6. Memory Compression Context Safety

To prevent context window overflows, the strategy executes a dialogue pruning pipeline. Architecturally, the prompt injection sequence is highly protected:

* The intermediate conversation logs are summarized into a system archive message.
* **Prompt Injection Guarantee**: The active user `prompt` is forcefully appended to the message queue strictly *after* the memory compression block finishes. This guarantees that the current active instruction is never accidentally swallowed or diluted by the background summarizer.

## 7. Sequence Diagram

This sequence diagram illustrates the runtime workflow of a native reasoning step, detailing capability checking, parallel execution, and database state persistence:

```mermaid
sequenceDiagram
    autonumber
    participant Agent as Agent / AgentTeam
    participant Strategy as NativeReasoningStrategy
    participant Client as LLMClient / Adapter
    participant DB as SQLite DB
    participant Tools as Tool Registry
    
    Agent->>Strategy: execute(team, agent, prompt)
    Note over Strategy: Fetch registered tools
    Strategy->>Tools: Fetch native tools
    Tools-->>Strategy: return List[Tool]
    Note over Strategy: Check capability:\nsupports_native_tool_calling() -> True
    
    loop until max_tool_rounds or text response
        Strategy->>Client: generate(prompt, tools=native_tools)
        Client-->>Strategy: return LLMResponse(tool_calls=...)
        
        Note over Strategy: Save Assistant message to history
        Strategy->>DB: save_state() with tool_calls (JSON)
        
        Note over Strategy: Parallel Tool Execution via asyncio.gather()
        par Tool A
            Strategy->>Tools: execute(tool_a, args)
            Tools-->>Strategy: ToolResult A
        and Tool B
            Strategy->>Tools: execute(tool_b, args)
            Tools-->>Strategy: ToolResult B
        end
        
        Note over Strategy: Save ToolResults as "tool" messages to history
        Strategy->>DB: save_state() with tool_call_id, name, content
    end
    
    Strategy-->>Agent: return final answer text
```

## 8. Persistence & Serialization

To support 100% state recovery after crashes, the SQLite database schema has been updated. The `AgentMessageModel` table contains three columns mapping to the structured tool calls:

* **`tool_calls`**: A native SQLite `JSON` column storing the list of structured tool executions.
* **`tool_call_id`**: A string column mapping the message to its specific trigger call ID (required when role is `"tool"`).
* **`name`**: A string column specifying which tool was executed (required when role is `"tool"`).

These columns are serialized in `save_state` and reconstructed fully in `load_state`, preserving the complete multi-turn reasoning context.
