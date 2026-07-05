# State Persistence & Recovery Lifecycle Flowcharts

This document visualizes the database auto-save hooks, serialization rules, the $O(1)$ memory compression logic, and the two-pass recovery pipeline of the SQLite state persistence engine.

## 1. State Persistence Auto-Save Triggers (Deep Dive)

This flowchart shows the critical runtime events that automatically trigger SQLite state serialization via SQLAlchemy ORM, explicitly mapping how $O(1)$ garbage collection is performed via `notin_` cascading deletions.

```mermaid
flowchart TD
    Start["Runtime Event Triggered"] --> EventType{"Event Type?"}
    
    EventType -- "Spawning" --> Save1["Spawning child teams\n(create_agent_team)"]
    EventType -- "Membership" --> Save2["Adding / removing team members\n(add/remove_team_member)"]
    EventType -- "Governance" --> Save3["Initiating proposals / voting\n(cast_vote, initiate_membership_vote)"]
    EventType -- "Debate" --> Save4["Reaching discussion conclusions\n(execute_team_discussion)"]
    EventType -- "Reasoning Step" --> Save5["Executing agent reasoning step\n(execute_reasoning_step)"]
    EventType -- "Library Write" --> Save6["Modifying library files\n(write/delete_library_file)"]
    
    Save1 --> AutoSave["Invoke manager._auto_save()"]
    Save2 --> AutoSave
    Save3 --> AutoSave
    Save4 --> AutoSave
    Save5 --> AutoSave
    Save6 --> AutoSave
    
    AutoSave --> SessionBegin["Begin SQLAlchemy DB session\n(disable_fks=True for speed)"]
    
    SessionBegin --> O1GC["1. Fetch list of active agent_names\n2. Execute: session.query(AgentMessageModel).filter(AgentMessageModel.agent_name.notin_(active_agent_names)).delete()\n3. Execute identical notin_ deletions for TeamInboxModel, TeamProposalModel, DocLibFileModel"]
    
    O1GC --> DumpModels["Dump Config, AgentModels, and TeamModels to DB\n(JSON serialization of last_context and communication_rules)"]
    
    DumpModels --> CommitORM["Commit transaction and release lock"]
    CommitORM --> End["State snapshot saved successfully"]
```

## 2. Multi-Turn Memory Compression & Pruning

This flowchart maps the `max_memory_turns` logic. To prevent Out-Of-Memory (OOM) errors during long-running tasks, the agent dynamically prunes early conversation history and replaces it with a condensed, LLM-generated summary.

```mermaid
flowchart TD
    Start["Check agent.messages length"] --> SizeCheck{"len(messages) > max_memory_turns + 2?"}
    
    SizeCheck -- "No" --> EndNoOp["No compression needed\nProceed to auto-save"]
    
    SizeCheck -- "Yes" --> ExtractBase["Extract first_msg = messages[0]\n(The core system instructions)"]
    
    ExtractBase --> CalcSlice["Calculate slice_idx = len(messages) - max_turns"]
    
    CalcSlice --> ReverseScan{"Is messages[slice_idx] a 'tool' or 'function' role?"}
    ReverseScan -- "Yes" --> AdjustSlice["slice_idx -= 1\n(Prevents breaking ReAct tool response pairs)"]
    AdjustSlice --> ReverseScan
    
    ReverseScan -- "No" --> ExtractIntermediate["Extract intermediate_messages = messages[1 : slice_idx]"]
    
    ExtractIntermediate --> GenerateSummaryPrompt["Compile summary_prompt:\n'Summarize the preceding execution logs... Focus on what was completed.'"]
    
    GenerateSummaryPrompt --> CallCriticLLM["Invoke Agent's LLM Client to generate summary"]
    
    CallCriticLLM --> BuildArchive["Create new system message:\n'*** HISTORICAL SUMMARY ARCHIVE ***\\n{summary_text}'"]
    
    BuildArchive --> Reconstruct["agent.messages = [first_msg, archive_message] + messages[slice_idx:]"]
    
    Reconstruct --> EndCompressed["Memory compressed.\nProceed to auto-save."]
```

## 3. Recovery Workflow & Two-Pass Deserialization Pipeline

This flowchart outlines the execution phases when restoring the manager state from a database using `load_state(db_path)`:

```mermaid
flowchart TD
    StartLoad["Call manager.load_state(db_path)"] --> LoadDB["1. Open SQLite Connection\n2. Query Config & Topology tables"]
    
    LoadDB --> Step1Config["Phase 1: Config Restoration\n- Reconstruct ATTConfig properties\n- Bind Root AI agent metadata"]
    
    Step1Config --> Step2Agents["Phase 2: Agent Cache Rebuilding\n- Instantiate Agent objects\n- Restore multi-turn message queue\n- Bind LLM Client adapters"]
    
    Step2Agents --> Step3DocLib["Phase 3: Physical File Restoration\n- Clear local folder .att_doc_libs/<lib_id>\n- Write DB blobs back to local directories"]
    
    Step3DocLib --> Step4Lineage1["Phase 4: Two-Pass Lineage Reconstruction\n(Pass 1: Node Instantiation)\n- Recreate AgentTeam instances\n- Restore status maps, inboxes, and proposals\n- Hydrate O(1) cached team depth directly from DB"]
    
    Step4Lineage1 --> Step5Lineage2["Phase 4: (Pass 2: Pointer Resolution)\n- Resolve parent_team / child_teams tree references\n- Hook up creator agent / team object pointers"]
    
    Step5Lineage2 --> Step6ToolBinding["Phase 5: Bind Tools & Permissions\n- Re-link DocLib permissions ACLs\n- Re-bind default and custom tools to teams"]
    
    Step6ToolBinding --> Step7Broker["Phase 6: Restore Broker Agreements\n- Hydrate peer communication tunnel agreements"]
    
    Step7Broker --> EndLoad["Manager State successfully restored & active"]
```
