# Spawning & Escalation Channels Flowchart

This document details the control flow of the dynamic, recursive `AgentTeam` spawning lineage and sibling communication gating.

## 1. Dynamic Spawning & Tool Binding Flowchart

This flowchart outlines the logic executed when an individual `Agent` or `AgentTeam` launches a dynamic sub-team:

```mermaid
flowchart TD
    Start["Call creator.launch_att(manager, member_count)"] --> EnforceSize{"member_count >= 3?"}
    
    EnforceSize -- "No" --> RaiseAssert["Raise AssertionError\n(Spawning blocked)"]
    EnforceSize -- "Yes" --> GenerateID["Generate unique team_id: AT-xxxxxx"]
    
    GenerateID --> SpawnMembers["Spawn members with matching role presets\nand llm_client configurations"]
    
    SpawnMembers --> CreateTeam["Instantiate AgentTeam with creator link"]
    
    CreateTeam --> ToolsContext{"Tools Context registered\nin ATTManager?"}
    
    ToolsContext -- "Yes" --> GetDefaultTools["Call get_default_tools(tools_context, Team)"]
    GetDefaultTools --> BindTools["Bind Tools map onto Team.tools"]
    BindTools --> RegisterTeam["Register team reference in manager.teams map"]
    
    ToolsContext -- "No" --> RegisterTeam
    
    RegisterTeam --> CreatorIsTeam{"Is creator an AgentTeam?"}
    
    CreatorIsTeam -- "Yes" --> AddChildLink["Add child Team reference into creator.child_teams list"]
    AddChildLink --> End["Dynamic Team successfully spawned & active"]
    
    CreatorIsTeam -- "No (Agent)" --> End
```

## 2. Dynamic Sibling Talk Authorization Sequence

This sequence diagram illustrates how a Parent Team calls `set_sibling_talk` to dynamically authorize Sibling Teams to communicate:

```mermaid
sequenceDiagram
    autonumber
    participant Parent as Parent Team (AT-Parent)
    participant Manager as ATTManager
    participant Child1 as Child Team 1 (AT-Child1)
    participant Child2 as Child Team 2 (AT-Child2)
    
    Parent->>Manager: Run execute_react_step()
    Note over Parent: LLM decides to authorize sibling talk
    Parent->>Manager: Call set_sibling_talk(child_id='AT-Child1', allow=True)
    Note over Manager: Verify if caller AT-Parent is the parent of AT-Child1
    Manager-->>Parent: Authorization Confirmed
    Note over Manager: Set AT-Child1.allow_sibling_talk = True
    
    Child1->>Manager: Call negotiate_communication(AT-Child1, AT-Child2)
    Note over Manager: Resolve common parent AT-Parent
    Note over Manager: Check AT-Parent's allow_sibling_talk permission
    Manager-->>Child1: Permission Approved (True)
    Note over Child1, Child2: Child 1 and Child 2 establish communication tunnel!
```

## 3. Dynamic Lineage Migration Sequence

This sequence diagram illustrates how an active Agent Team calls `request_migration` to reorganize the lineage hierarchy, arbitrated by the System Critic:

```mermaid
sequenceDiagram
    autonumber
    participant T as Migrating Team (AT-T)
    participant Manager as ATTManager
    participant Critic as LLM Critic Client
    participant P_curr as Old Parent Team (AT-Old)
    participant P_targ as New Parent Team (AT-New)

    T->>Manager: Call request_migration(target_parent_id='AT-New', rationale='...')
    Note over Manager: Verify migration limits & cycle checks
    Manager->>Critic: Call generate() with arbitration prompt
    Note over Critic: Arbitrate rationale and structure
    Critic-->>Manager: Return approved=True JSON payload
    
    Note over Manager: Update parent-child pointers:<br/>P_curr.child_teams.remove(T)<br/>P_targ.child_teams.append(T)<br/>T._parent_team = P_targ
    
    Manager->>P_curr: Dispatch "migration_alert" to inbox
    Manager->>P_targ: Dispatch "migration_alert" to inbox
    Manager->>T: Dispatch success alert to inbox
    
    Manager->>Manager: Trigger on_team_migration callback
    Manager-->>T: Return success status
```
