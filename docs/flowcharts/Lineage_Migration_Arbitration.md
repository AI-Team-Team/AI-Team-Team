# Dynamic Lineage Migration Arbitration Sequence Diagram

This document sequences the Least Common Ancestor (LCA) resolution, representative path harvesting, LLM arbitration, and pointer restructuring executed during dynamic lineage migrations.

## 1. Lineage Migration Arbitration Sequence

The sequence diagram below visualizes the lifecycle of a migration request under the default **Ancestor Approval Policy** (`"ancestor_approval"`):

```mermaid
sequenceDiagram
    autonumber
    participant T as Migrating Team (AT-T)
    participant Manager as ATTManager
    participant Policy as AncestorApprovalPolicy
    participant P_old as Old Parent Rep (or Root AI)
    participant P_new as New Parent Rep (or Root AI)
    participant LCA as LCA Rep (or Root AI)

    T->>Manager: Call request_migration(target_parent_id='AT-New', rationale='...')
    Note over Manager: 1. Validate migration limit (max_migrations_per_team_discussion)<br/>2. Run cycle check: Ensure AT-New is not a descendant of AT-T
    
    Manager->>Manager: Resolve Least Common Ancestor (LCA) in Team tree
    
    Manager->>Policy: Call authorize_migration(T, AT-New, Manager, rationale)
    
    Note over Policy: Harvest path representatives:<br/>1. Old Parent representative (AT-Old leader)<br/>2. New Parent representative (AT-New leader)<br/>3. LCA representative (AT-LCA leader)<br/>* Fallback to Root AI if representative resolves to root level
    
    %% Arbitration Loop
    critical Representative LLM Arbitration
        Policy->>P_old: Send Migration Prompt (objective, rationale, LCA context)
        P_old-->>Policy: Return JSON {"approved": true, "reason": "..."}
        
        Policy->>P_new: Send Migration Prompt (objective, rationale, LCA context)
        P_new-->>Policy: Return JSON {"approved": true, "reason": "..."}
        
        Policy->>LCA: Send Migration Prompt (objective, rationale, LCA context)
        LCA-->>Policy: Return JSON {"approved": true, "reason": "..."}
    end
    
    Policy-->>Manager: Return approved=True, reason='All representatives approved'
    
    %% Restructure
    Note over Manager: Re-link pointer mappings in-memory:<br/>1. AT-Old.child_teams.remove(AT-T)<br/>2. AT-New.child_teams.append(AT-T)<br/>3. AT-T.parent_team = AT-New
    
    %% Alerts
    par Dispatch Alerts
        Manager->>P_old: Post "migration_alert" in inbox (notifying team AT-T moved out)
    and
        Manager->>P_new: Post "migration_alert" in inbox (notifying team AT-T moved in)
    and
        Manager->>T: Post "migration_alert" in inbox (confirming migration)
    end
    
    Manager->>Manager: Trigger manager.on_team_migration callback
    Manager->>Manager: Call manager._auto_save() to write new pointers to SQLite
    
    Manager-->>T: Return success status
```
