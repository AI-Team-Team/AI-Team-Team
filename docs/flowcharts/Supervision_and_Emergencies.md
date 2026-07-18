# Supervision and Emergencies Flowcharts

This document details the dialogue auditing logic, the recursive lineage escalation protocol executed by the **Supervisory Team**, and the emergency event-driven wakeup protocols.

## 1. 3-AI Dialogue Auditing Logic (Deep Dive)

This flowchart outlines the exact 3-AI consensus sequence executed post-discussion. The manager invokes three specialized LLM Auditor agents in parallel to verify overall dialogue health, mapping the output to an `is_healthy` boolean and triggering `on_log_append` for debugging.

```mermaid
flowchart TD
    Start["Call audit_team_dialog(team, transcript)"] --> MemoryBarrier["Hard Memory Isolation:\nagent.messages.clear()\n(Prevents OOM during infinite audits)"]
    MemoryBarrier --> FormulatePrompt["Assemble Audit Context containing\nthe raw multi-agent debate transcript"]
    
    FormulatePrompt --> BatchCall["Dispatch Parallel LLM Calls to 3 Auditor Prompts"]
    
    %% Parallel Auditor Execution
    BatchCall --> IntegrityAuditor["Integrity Auditor\n(Checks for Security/Logic/Hallucination)\nOutputs: {is_healthy: bool, reason: str}"]
    BatchCall --> ContinuityAuditor["Continuity Auditor\n(Checks for Objective Progress/Stalling)\nOutputs: {is_healthy: bool, reason: str}"]
    BatchCall --> DeadlockAuditor["Deadlock Auditor\n(Checks for Circular Tool Loops/Errors)\nOutputs: {is_healthy: bool, reason: str}"]
    
    IntegrityAuditor --> TryBlock{"Try LLM generation & JSON parse"}
    ContinuityAuditor --> TryBlock
    DeadlockAuditor --> TryBlock
    
    TryBlock -- "Exception / Parse Fails" --> FallbackHealthy["Log warning with error details\nDefault to healthy=True to prevent false blocks"]
    TryBlock -- "Success" --> CombineResults["Aggregate responses from all 3 Auditors"]
    
    CombineResults --> HealthGate{"Are ALL is_healthy flags == True?"}
    
    HealthGate -- "Yes" --> LogHealthy["manager.on_log_append('Audit Passed')"]
    LogHealthy --> End["Discussion healthy (No intervention needed)"]
    FallbackHealthy --> End
    
    HealthGate -- "No (Anomaly Detected)" --> LogFailed["manager.on_log_append('Audit Failed', audit_reason)"]
    LogFailed --> TriggerEscalation["Call report_anomaly(failed_team, combined_reason, manager)"]
    TriggerEscalation --> EscalationFlow["Execute Parent Escalation Tree"]
```

## 2. Parent-Ancestor Escalation Tree

This flowchart visualizes the direct parent escalation checks executed by `SupervisoryTeam.report_anomaly` to route failure alerts:

```mermaid
flowchart TD
    StartClimb["Start anomaly escalation for failed_team"] --> ResolveParent["Get current_parent\n(Traverse parent_team or find_parent_team)"]
    
    ResolveParent --> ParentExists{"current_parent exists?"}
    
    ParentExists -- "Yes" --> RouteAlert["Route failure alert payload to Parent inbox:\n- failed_team_id\n- reason\n- type: child_failure_escalation"]
    RouteAlert --> TriggerCallback["Trigger on_emergency_escalation callback hook"]
    
    TriggerCallback --> WakeupGate{"Parent is idle and\nenable_emergency_wakeup == True?"}
    
    WakeupGate -- "Yes" --> EmergencyDiscussion["Spawn asynchronous task:\nexecute_emergency_discussion(parent, alert)\n(Runs emergency debate rounds)"]
    WakeupGate -- "No" --> ParentPrepend["Parent injects alert into its next active discussion prompt"]
    
    EmergencyDiscussion --> End["Escalation alert routed successfully"]
    ParentPrepend --> End["Escalation alert routed successfully"]
    
    ParentExists -- "No (No Parent / Root level)" --> AlertRootAI["Escalate critical warning directly to Root AI Level 0"]
    AlertRootAI --> RootAlert["Display Critical Warning log\n(Root AI handles architectural correction)"]
    RootAlert --> End
```

## 3. Emergency Wakeup Routing (Deep Dive)

This sequence diagram dives deeper into the specific control flow when a child team escalates an emergency, detailing how the `enable_emergency_wakeup` flag triggers preemptive `asyncio` context switches, and how it safely falls back to a deferred execution queue.

```mermaid
sequenceDiagram
    participant Child as Child Team (AT-2)
    participant Parent as Parent Team (AT-1)
    participant Manager as ATTManager
    participant EventLoop as Asyncio Event Loop

    Note over Child: Child team hits deadlock or fails.
    Child->>Parent: append to message_inbox (type: 'child_failure_escalation')
    
    Parent->>Manager: check config.enable_emergency_wakeup
    
    alt enable_emergency_wakeup == True
        Manager->>Manager: Evaluate target team run state
        
        alt is_running == True
            Note over Manager: Team is already active in a discussion.<br/>Message sits in inbox until next poll.
        else is_running == False
            Note over Manager: Team is idle. Initiate preemptive wakeup.
            Manager->>EventLoop: asyncio.create_task(execute_emergency_discussion)
            
            alt EventLoop is active
                EventLoop->>Parent: Wakes up and processes inbox immediately
            else EventLoop is blocked/missing
                EventLoop-->>Manager: RuntimeError: no running event loop
                Note over Manager: Fallback triggered
                Manager->>Manager: deferred_emergency_tasks.put_nowait()
                Note over Manager: Execution deferred until flush_deferred_tasks()
            end
        end
    else enable_emergency_wakeup == False
        Note over Manager: Emergency Wakeups disabled.<br/>Message sits in inbox.
    end
```
