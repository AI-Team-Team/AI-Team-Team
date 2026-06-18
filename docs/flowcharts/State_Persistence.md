# State Persistence & Recovery Lifecycle Flowcharts

This document visualizes the database auto-save hooks, serialization rules, and the two-pass recovery pipeline of the SQLite state persistence engine.

## 1. State Persistence Auto-Save Triggers

This flowchart shows the critical runtime events that automatically trigger SQLite state serialization via SQLAlchemy ORM:

```mermaid
flowchart TD
    Start["Runtime Event Triggered"] --> EventType{"Event Type?"}
    
    EventType -- "Spawning" --> Save1["Spawning child teams\n(create_agent_team)"]
    EventType -- "Membership" --> Save2["Adding / removing team members\n(add/remove_team_member)"]
    EventType -- "Governance" --> Save3["Initiating proposals / voting\n(cast_vote, initiate_membership_vote)"]
    EventType -- "Debate" --> Save4["Reaching discussion conclusions\n(execute_team_discussion)"]
    EventType -- "ReAct Step" --> Save5["Executing agent reasoning step\n(execute_react_step)"]
    EventType -- "Library Write" --> Save6["Modifying library files\n(write/delete_library_file)"]
    
    Save1 --> AutoSave["Invoke manager._auto_save()"]
    Save2 --> AutoSave
    Save3 --> AutoSave
    Save4 --> AutoSave
    Save5 --> AutoSave
    Save6 --> AutoSave
    
    AutoSave --> SerializeORM["1. Begin database transaction\n2. Map models (AgentModel, TeamModel, etc.)\n3. Commit serialization changes to SQLite"]
    SerializeORM --> End["State snapshot saved successfully"]
```

## 2. Recovery Workflow & Two-Pass Deserialization Pipeline

This flowchart outlines the execution phases when restoring the manager state from a database using `load_state(db_path)`:

```mermaid
flowchart TD
    StartLoad["Call manager.load_state(db_path)"] --> LoadDB["1. Open SQLite Connection\n2. Query Config & Topology tables"]
    
    LoadDB --> Step1Config["Phase 1: Config Restoration\n- Reconstruct ATTConfig properties\n- Bind Root AI agent metadata"]
    
    Step1Config --> Step2Agents["Phase 2: Agent Cache Rebuilding\n- Instantiate Agent objects\n- Restore multi-turn message queue\n- Bind LLM Client adapters"]
    
    Step2Agents --> Step3DocLib["Phase 3: Physical File Restoration\n- Clear local folder .att_doc_libs/<lib_id>\n- Write DB blobs back to local directories"]
    
    Step3DocLib --> Step4Lineage1["Phase 4: Two-Pass Lineage Reconstruction\n(Pass 1: Node Instantiation)\n- Recreate AgentTeam instances\n- Restore status maps, inboxes, and proposals"]
    
    Step4Lineage1 --> Step5Lineage2["Phase 4: (Pass 2: Pointer Resolution)\n- Resolve parent_team / child_teams tree references\n- Hook up creator agent / team object pointers"]
    
    Step5Lineage2 --> Step6ToolBinding["Phase 5: Bind Tools & Permissions\n- Re-link DocLib permissions ACLs\n- Re-bind default and custom tools to teams"]
    
    Step6ToolBinding --> Step7Broker["Phase 6: Restore Broker Agreements\n- Hydrate peer communication tunnel agreements"]
    
    Step7Broker --> EndLoad["Manager State successfully restored & active"]
```
