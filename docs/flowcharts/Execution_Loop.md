# Unified Multi-Agent Discussion & ReAct Execution Loop

This document provides visual flowcharts mapping the core runtime execution engine of the ATT framework.

## 1. Master Discussion Loop (`execute_team_discussion`)

This flowchart sequences the multi-round cooperative debate process executed when a team is tasked with resolving a prompt:

```mermaid
flowchart TD
    Start["Call manager.execute_team_discussion(team, prompt, rounds)"] --> Init["1. Setup transcript logs\n2. Initialize discussion round = 1"]
    
    Init --> SuppressIOGate["with manager._suppress_auto_save():\n(Blocks high-frequency SQLite writes)"]
    SuppressIOGate --> LoopRounds{"round <= total_rounds?"}
    
    LoopRounds -- "Yes" --> MemberIteration["Iterate through each member (Agent) in team"]
    
    MemberIteration --> RunAgentStep["Call team.execute_reasoning_step(agent, prompt)"]
    
    RunAgentStep --> NextMember{"All members finished turn?"}
    NextMember -- "No" --> MemberIteration
    
    NextMember -- "Yes" --> SupervisoryAudit["3-AI Supervisory Team audits round transcript"]
    
    SupervisoryAudit --> AuditResult{"is_healthy == True?"}
    
    AuditResult -- "No (Anomaly)" --> ReportAnomaly["Call report_anomaly()\nRoute failure alert to parent inbox\n(or escalate to Level 0 Root AI)"]
    ReportAnomaly --> IncrementRound["Increment round by 1"]
    
    AuditResult -- "Yes (Healthy)" --> IncrementRound
    
    IncrementRound --> LoopRounds
    
    LoopRounds -- "No" --> FinalizeState["1. Save final snapshot to SQLite\n2. Log debate completion metrics"]
    FinalizeState --> End["Return compiled debate transcript"]
```

## 2. Granular Agent Turn & Reasoning Step (`execute_reasoning_step` / `execute_react_step`)

This flowchart outlines the prompt compilation, strategy routing (Text ReAct vs Native), reasoning execution loops, tool execution auditing, memory compression, and auto-saving performed during a single agent's execution turn:

```mermaid
flowchart TD
    StartStep["Call execute_reasoning_step(agent, team, prompt)"] --> TransitionCheck{"agent.last_context.get('team_id') != team.team_id?"}
    
    TransitionCheck -- "Yes" --> InjectTransition["Inject Transition Notice system message into memory\n(Updates role, team purpose, and active preset details)"]
    TransitionCheck -- "No" --> BuildContext["Compile Prompt Context:\n1. Get Identity Header\n2. Render Topology Tree map\n3. Format Active Voting Proposals\n4. Inject Global Expert Directory"]
    
    InjectTransition --> BuildContext
    BuildContext --> InboxAlerts["Check unread inbox alerts"]
    InboxAlerts --> InboxThreshold{"Inbox size > 1500 chars?"}
    
    InboxThreshold -- "Yes" --> SummarizeInbox["Use LLM client to summarize inbox\nInject summary into prompt"]
    InboxThreshold -- "No" --> InjectInbox["Inject raw inbox alerts into prompt"]
    
    SummarizeInbox --> RouteStrategy{"Check Config Mode & supports_native_tool_calling()"}
    InjectInbox --> RouteStrategy
    
    RouteStrategy -- "Text ReAct Mode" --> InitReAct["Initialize ReAct step counter = 1"]
    RouteStrategy -- "Native Mode" --> InitNative["Initialize Native round counter = 1"]
    
    %% --- Text ReAct Strategy Flow ---
    InitReAct --> ReActLoop{"step <= react_max_steps?"}
    ReActLoop -- "Yes" --> LLMCall["Invoke Agent.llm_client.generate()"]
    
    LLMCall --> CatchFailover{"Token Limit Hit?"}
    CatchFailover -- "Yes" --> FailoverPop["messages.pop()\nPurge duplicated user prompt"]
    FailoverPop --> ModelSwap["Hot-swap client via Failover Policy"]
    ModelSwap --> LLMCall
    
    CatchFailover -- "No" --> ParseAction["Parse response for actions (XML tags or Action: tool_name)"]
    ParseAction --> ActionType{"Action found?"}
    ActionType -- "No (Final Answer)" --> SetFinalAnswer["Append Final Answer to memory\nBreak Loop"]
    ActionType -- "Yes (Tool Call)" --> SafeASTParse["Parse arguments using safe ast.literal_eval\n(Handles unquoted multiline strings & commas)"]
    SafeASTParse --> ToolAuditor{"Tool Auditor registered for tool?"}
    ToolAuditor -- "Yes" --> RunAuditor["Invoke pre-execution auditor callback"]
    RunAuditor --> AuditorApprove{"Auditor approved?"}
    AuditorApprove -- "No" --> BlockTool["Set observation = 'Blocked by auditor'\nAppend to memory"]
    AuditorApprove -- "Yes" --> RunTool["Execute Tool function\n(e.g., GatedFileReader, DocLib, P2P Message)"]
    ToolAuditor -- "No" --> RunTool
    RunTool --> SaveObservation["Append Thought, Action, and Observation to memory"]
    BlockTool --> NextReActStep["Increment step by 1"]
    SaveObservation --> NextReActStep
    NextReActStep --> ReActLoop
    ReActLoop -- "No" --> CheckMemory
    
    %% --- Native Strategy Flow ---
    InitNative --> NativeLoop{"round <= max_tool_rounds?"}
    NativeLoop -- "Yes" --> FetchTools["Thorough Abstraction:\nFetch native Tool objects"]
    FetchTools --> LLMNativeCall["Invoke Agent.llm_client.generate(tools=native_tools)"]
    
    LLMNativeCall --> CatchNativeFailover{"Token Limit Hit?"}
    CatchNativeFailover -- "Yes" --> FailoverNativePop["messages.pop()\nPurge duplicated user prompt"]
    FailoverNativePop --> ModelNativeSwap["Hot-swap client via Failover Policy"]
    ModelNativeSwap --> LLMNativeCall
    
    CatchNativeFailover -- "No" --> NativeResponse{"tool_calls returned?"}
    
    NativeResponse -- "Yes (Structured calls)" --> SaveToolCall["Save Assistant message with tool_calls (JSON) to DB"]
    SaveToolCall --> ParallelExecute["Execute all tool calls concurrently via asyncio.gather()"]
    ParallelExecute --> SaveToolResults["Save ToolResult messages to DB\n(tool_call_id, name, content)\nIncrement round counter"]
    SaveToolResults --> NativeLoop
    
    NativeResponse -- "No (Text response)" --> SaveTextResponse["Save Assistant final text to memory\nBreak Loop"]
    NativeLoop -- "No" --> CheckMemory
    
    %% --- Post Execution Flow ---
    SetFinalAnswer --> CheckMemory
    SaveTextResponse --> CheckMemory
    
    CheckMemory["Check total memory turns"] --> PruningGate{"Turns > max_memory_turns + 2?\n(Compression enabled)"}
    
    PruningGate -- "Yes" --> SummarizeEarly["1. Extract early turns (excluding profile)\n2. Generate historical fact summary via LLM\n3. Replace early turns with Archive system prompt"]
    PruningGate -- "No" --> AutoSave["Invoke manager._auto_save() to SQLite"]
    
    SummarizeEarly --> AutoSave
    AutoSave --> EndStep["Return agent step result"]
```
