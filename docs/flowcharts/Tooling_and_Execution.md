# Tooling and Execution Flowcharts

This document consolidates the sequence flows defining how tools are parsed, audited, and executed within the runtime reasoning loops of the framework, as well as the low-level adapter logic for the LLM integrations.

## 1. Generator Handler Forwarding and Response Conversion

This sequence diagram illustrates the default generator-handler adapter's forwarding and response-conversion behavior for a Native request.

The personal runtime resolves a concrete provider binding before quota reservation, and directly registered clients do not require this forwarding path.

Handlers return `str`, `dict`, or `LLMResponse`, synchronously or through an awaitable.

The Host collects provider-specific streams and assembles any streamed tool calls before returning one of these supported values; the default ATT wrapper does not consume iterators or asynchronous iterators.

```mermaid
sequenceDiagram
    participant Agent as Default Adapter Caller
    participant Adapter as ManagerDefaultClientAdapter
    participant Handler as HandlerClientAdapter
    participant Generator as Host Generator Handler
    participant Provider as External LLM Provider (e.g., OpenAI)

    Agent->>Adapter: generate(prompt, tools=List[Tool])
    
    Note over Adapter: Adapter detects that manager.generator_handler exists.
    Adapter->>Handler: Init HandlerClientAdapter("default", handler)
    
    Note over Handler: Honor the handler's supported parameter contract
    
    Handler->>Generator: Invoke global generator_handler(**kwargs)
    Generator->>Provider: Make Host-owned SDK request
    
    Provider-->>Generator: Return result or provider-specific stream
    Note over Generator: Collect streams and normalize provider fields before returning
    
    Generator-->>Handler: Return str, dict, or LLMResponse
    
    alt Return is pure String
        Handler->>Handler: Cast to LLMResponse(text=res)
    else Return is Dict
        Note over Handler: Extract text and tool_calls
        Handler->>Handler: Loop over tool_calls array:<br/>Map to ToolCall dataclass(id, name, arguments)
        Handler->>Handler: Cast to LLMResponse(text, tool_calls=[...])
    else Return is LLMResponse
        Handler->>Handler: Pass through directly
    end
    
    Handler-->>Adapter: Return LLMResponse
    Adapter-->>Agent: Return standard LLMResponse
```

## 2. Tool Parsing & Auditor Lifecycle

This sequence diagram follows a registered tool from provider request preparation through execution admission, resource coordination, optional auditing, and foreground result acceptance.

Eligible long-running work may return a handle while the same execution continues, as described in [Background Tasks](Background_Tasks.md).

```mermaid
sequenceDiagram
    participant Dev as Developer
    participant Manager as ATTManager
    participant Strategy as Personal Runner (Native/Text)
    participant LLM as LLM Provider Adapter
    participant Service as ExecutionService
    participant Executor as Shared ToolExecutor
    participant Validator as Signature / Pydantic / JSON Schema
    participant Auditor as ToolAuditor
    participant Binding as Registered Executor / Callable
    
    %% Registration
    Note over Dev,Manager: Tool Registration
    Dev->>Manager: register_tool(name="drop_db", func=drop_db, description=...)
    Manager->>Manager: Wraps python function in native `Tool` object
    
    Dev->>Manager: register_tool_auditor("drop_db", audit_drop_db)
    Manager->>Manager: Store hook in tool_auditors under the public tool name
    
    %% Generation
    Note over Manager,LLM: Provider Request Preparation
    alt Native protocol
        Strategy->>LLM: generate(prompt, tools=List[Tool])
        Note over LLM: Adapter converts Tool schemas into provider format
        LLM-->>Strategy: LLMResponse with structured tool calls
    else Text ReAct protocol
        Strategy->>LLM: generate(prompt, system_instruction with tool schemas, tools=None)
        LLM-->>Strategy: Text response with Action
        Strategy->>Strategy: Balanced scanner and literal-only argument parsing
    end
    
    %% Execution and audit
    Note over Strategy,Auditor: Execution and Interception
    Strategy->>Service: execute(tool_name, arguments, captured scope)
    Service->>Service: Resolve available tool and validate scope, arguments, binding and resources

    alt Unavailable, invalid or denied admission
        Service-->>Strategy: Classified error observation without executing the callable
    else Valid registered work
        Service->>Service: Commit execution identity and coordinate resource claims
        Service->>Executor: execute with captured context and attempt hooks
        Executor->>Validator: Revalidate signature and strict nested input
        Validator-->>Executor: validated args and kwargs
        opt Auditor registered
            Executor->>Auditor: Pre-execution intercept under invocation ContextVars
            Auditor-->>Executor: Approval and reason, or failure
        end
        alt Auditor denies or fails
            Executor-->>Service: Denied or internal-error ToolResult
        else No auditor or approval is literal True
            Executor->>Service: Revalidate live authority and commit attempt evidence
            Service-->>Executor: Attempt accepted
            Executor->>Binding: Invoke under captured scope and resource authority
            Binding-->>Executor: Value or typed tool exception
            Executor-->>Service: Classified ToolResult
        end
        Service->>Service: Accept factual outcome and protected result
        Service-->>Strategy: Committed foreground observation
    end
```

## 3. Continuing Personal Activity

```mermaid
flowchart TD
    Admission["Explicit activation or eligible addressed notice"] --> Person["One continuing Agent and invocation lock"]
    Person --> Scope["Validate selected personal or AgentTeam scope"]
    Scope --> Context["Compose own instructions, bounded context and actual available tools"]
    Context --> Request["Persist provider request and reserve shared quota"]
    Request --> Provider["Bounded provider call"]
    Provider --> Mode{"Response protocol"}
    Mode -- "Text" --> Parse["Balanced Action and literal-only argument parser"]
    Mode -- "Native" --> Calls["Validated unique structured calls"]
    Parse --> Execute["Common resource admission, auditor and ToolExecutor"]
    Calls --> Execute
    Execute --> Observation["Typed observations and factual execution receipts"]
    Observation --> Checkpoint["Commit sanitized window, Journal sources and notice claims"]
    Mode -- "Ordinary answer" --> Answer["Observe answer, no implicit publication or stop"]
    Answer --> Checkpoint
    Checkpoint --> Intent{"Explicit intent or fairness boundary?"}
    Intent -- "Continue" --> Person
    Intent -- "Idle" --> Idle["Wait for eligible personal attention"]
    Intent -- "Finite sleep" --> Sleep["Persist bounded countdown and source rules"]
```

Ordinary tool errors produce observations without terminating an AT or resetting another person's activity.

Typed provider failures enter resource availability handling, not a generic LLM-blame or health decision.

Fatal persistence and state-integrity failures propagate while accepted effects finish local settlement.

## 4. Institutional Work on the Same Runtime

Exact governance cases deliver voluntary personal voting mail without acquiring a whole-team discussion lock.

Temporary audit people use the same scheduler and executor with an immutable restricted evidence/tool profile and total deadline.

Registered long-running tools use the [background execution service](Background_Tasks.md), retaining one execution and one original call result or task handle.

Optional memory indexing consumes committed personal invocation segments and never copies membership-specific identities.
