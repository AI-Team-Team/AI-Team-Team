# Unified Multi-Agent Discussion & ReAct Execution Loop

This document provides visual flowcharts mapping the core runtime execution engine of the ATT framework.

## 1. Master Discussion Loop (`execute_team_discussion`)

This flowchart sequences the multi-round cooperative debate process executed when a team is tasked with resolving a prompt:

```mermaid
flowchart TD
    Start["Call manager.execute_team_discussion(team, prompt, rounds)"] --> Init["1. Setup transcript logs\n2. Initialize discussion round = 1"]
    
    Init --> LoopRounds{"round <= total_rounds?"}
    
    LoopRounds -- "Yes" --> MemberIteration["Iterate through each member (Agent) in team"]
    
    MemberIteration --> RunAgentStep["Call manager.execute_react_step(agent, team, prompt)"]
    
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

## 2. Granular Agent Turn & ReAct Step (`execute_react_step`)

This flowchart outlines the prompt compilation, ReAct reasoning loop, tool execution auditing, memory compression, and auto-saving performed during a single agent's execution turn:

```mermaid
flowchart TD
    StartStep["Call execute_react_step(agent, team, prompt)"] --> BuildContext["Compile Prompt Context:\n1. Get Identity Header\n2. Render Topology Tree map\n3. Format Active Voting Proposals\n4. Inject Global Expert Directory"]
    
    BuildContext --> InboxAlerts["Check unread inbox alerts"]
    InboxAlerts --> InboxThreshold{"Inbox size > 1500 chars?"}
    
    InboxThreshold -- "Yes" --> SummarizeInbox["Use LLM client to summarize inbox\nInject summary into prompt"]
    InboxThreshold -- "No" --> InjectInbox["Inject raw inbox alerts into prompt"]
    
    SummarizeInbox --> InitReAct["Initialize ReAct step counter = 1"]
    InjectInbox --> InitReAct
    
    InitReAct --> ReActLoop{"step <= react_max_steps?"}
    
    ReActLoop -- "Yes" --> LLMCall["Invoke Agent.llm_client.generate()"]
    
    LLMCall --> ParseAction["Parse response for actions (XML tags or Action: tool_name)"]
    
    ParseAction --> ActionType{"Action found?"}
    
    ActionType -- "No (Final Answer)" --> SetFinalAnswer["Append Final Answer to transcript\nBreak ReAct Loop"]
    
    ActionType -- "Yes (Tool Call)" --> ToolAuditor{"Tool Auditor registered for tool?"}
    
    ToolAuditor -- "Yes" --> RunAuditor["Invoke pre-execution auditor callback"]
    RunAuditor --> AuditorApprove{"Auditor approved?"}
    
    AuditorApprove -- "No" --> BlockTool["Set observation = 'Blocked by auditor'\nAppend to memory"]
    AuditorApprove -- "Yes" --> RunTool["Execute Tool function\n(e.g., GatedFileReader, DocLib, P2P Message)"]
    
    ToolAuditor -- "No" --> RunTool
    
    RunTool --> SaveObservation["Append Thought, Action, and Observation to memory"]
    BlockTool --> NextReActStep["Increment step by 1"]
    SaveObservation --> NextReActStep
    NextReActStep --> ReActLoop
    
    ReActLoop -- "No" --> CheckMemory["Check total memory turns"]
    SetFinalAnswer --> CheckMemory
    
    CheckMemory --> PruningGate{"Turns > max_memory_turns + 2?\n(Compression enabled)"}
    
    PruningGate -- "Yes" --> SummarizeEarly["1. Extract early turns (excluding profile)\n2. Generate historical fact summary via LLM\n3. Replace early turns with Archive system prompt"]
    PruningGate -- "No" --> AutoSave["Invoke manager._auto_save() to SQLite"]
    
    SummarizeEarly --> AutoSave
    AutoSave --> EndStep["Return agent step result"]
```
