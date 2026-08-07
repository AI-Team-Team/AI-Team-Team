# Lineage Tree Mutations Flowcharts

This document consolidates the sequence flows that govern how the Agent Team topology dynamically grows, restructures itself, and authorizes cross-branch communication.

## 1. Dynamic Spawning & Tool Binding

This flowchart outlines the logic executed when an individual `Agent` or `AgentTeam` launches a dynamic sub-team:

```mermaid
flowchart TD
    Start["Call creator.launch_att(manager, member_configs)"] --> EnforceSize{"len(member_configs) >= 3?"}
    
    EnforceSize -- "No" --> RaiseAssert["Raise AssertionError\n(Spawning blocked)"]
    EnforceSize -- "Yes" --> GenerateID["Generate unique team_id: AT-xxxxxx"]
    
    GenerateID --> SpawnMembers["Spawn members with matching role presets\nand llm_client configurations"]
    
    SpawnMembers --> CreateTeam["Instantiate AgentTeam with creator link"]
    
    CreateTeam --> RegisterAgents["Register stable Agent UUIDs\nReuse or create one private DocLib each"]
    RegisterAgents --> CreateDocLib["Create & register built-in team DocumentLibrary\nPopulate any initial_docs"]
    
    CreateDocLib --> ToolsContext{"Tools Context registered\nin ATTManager?"}
    
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
    
    Parent->>Manager: Run execute_reasoning_step()
    Note over Parent: LLM decides to authorize sibling talk
    Parent->>Manager: Call set_sibling_talk(child_id='AT-Child1', allow=True)
    Note over Manager: Verify if caller AT-Parent is the parent of AT-Child1
    Manager-->>Parent: Authorization Confirmed
    Note over Manager: Set AT-Child1.communication_rules["allow_sibling_talk"] = True
    
    Child1->>Manager: Call negotiate_communication(AT-Child1, AT-Child2)
    Note over Manager: Resolve common parent AT-Parent
    Note over Manager: Check AT-Parent's allow_sibling_talk permission
    Manager-->>Child1: Permission Approved (True)
    Note over Child1, Child2: Child 1 and Child 2 establish communication tunnel!
```

## 3. Cross-Lineage Proxied Negotiation Sequence

This sequence diagram details the `ProxiedCommunicationPolicy` arbitration process executed by the `NegotiationBroker`. When two teams from completely different branches attempt to communicate, the Broker queries the Representative Agents (usually the Team Leaders) of both parent lineages to jointly authorize the P2P tunnel.

```mermaid
sequenceDiagram
    autonumber
    participant T1 as Sender Team (AT-Sender)
    participant Broker as NegotiationBroker
    participant P1_Rep as Sender Parent Rep
    participant P2_Rep as Recipient Parent Rep
    participant T2 as Recipient Team (AT-Recipient)

    T1->>Broker: Call negotiate_peer_talk(target_id='AT-Recipient', rationale)
    
    Note over Broker: Resolve sender_parent and recipient_parent<br/>Identify their Representative Agents (Leaders)
    
    %% Parallel Arbitration Loop
    par Consult Sender Parent
        Broker->>P1_Rep: Call llm_client.generate(rationale_prompt)
        Note over P1_Rep: Evaluates impact on Sender's workload
        P1_Rep-->>Broker: Returns JSON {"approved": true, "reason": "..."}
    and Consult Recipient Parent
        Broker->>P2_Rep: Call llm_client.generate(rationale_prompt)
        Note over P2_Rep: Evaluates security & relevance for Recipient
        P2_Rep-->>Broker: Returns JSON {"approved": true, "reason": "..."}
    end
    
    Broker->>Broker: Check if both Representatives approved
    
    alt Approval Success
        Note over Broker: Save to SQLite: peer_talk_agreements
        Broker->>T1: Returns True (Tunnel Established)
        T1->>T2: Call send_peer_message(payload)
        T2-->>T1: Message successfully placed in Inbox
    else Approval Failed
        Broker->>T1: Returns False ("Rejected by representative...")
        Note over T1: Fallback observation injected into Sender memory
    end
```

## 4. Dynamic Lineage Migration (Overview)

This sequence diagram illustrates how an active Agent Team calls `request_migration` to reorganize the lineage hierarchy, arbitrated by the configured Migration Policy Strategy:

```mermaid
sequenceDiagram
    autonumber
    participant T as Migrating Team (AT-T)
    participant Manager as ATTManager
    participant Policy as Migration Policy Strategy
    participant P_curr as Old Parent Team (AT-Old)
    participant P_targ as New Parent Team (AT-New)

    T->>Manager: Call request_migration(target_parent_id='AT-New', rationale='...')
    Note over Manager: Verify migration limits & cycle checks
    Manager->>Policy: Call authorize_migration(team, target_parent, manager, rationale)
    Note over Policy: Evaluate strategy (Permissive, AncestorApproval, LineagePath)
    Policy-->>Manager: Return approved=True, reason='...'
    
    Note over Manager: Update parent-child pointers:<br/>P_curr.child_teams.remove(T)<br/>P_targ.child_teams.append(T)<br/>T._parent_team = P_targ
    
    Manager->>P_curr: Dispatch "migration_alert" to inbox
    Manager->>P_targ: Dispatch "migration_alert" to inbox
    Manager->>T: Dispatch success alert to inbox
    
    Manager->>Manager: Trigger on_team_migration callback
    Manager-->>T: Return success status
```

## 5. Democratic Membership Voting Sequence

This sequence diagram illustrates the lifecycle of a democratic membership proposal, from initiation to unanimous voting and execution:

```mermaid
sequenceDiagram
    autonumber
    participant A1 as Initiator (Agent 1)
    participant T as Agent Team (AT)
    participant A2 as Sibling (Agent 2)
    participant A3 as Sibling (Agent 3)
    participant Manager as ATTManager

    A1->>T: Call initiate_membership_vote(action='add', target='QA', proposed_details={...})
    Note over T: Acquire async team.state_lock<br/>Create VP-xxxx proposal<br/>Set Agent 1 vote to 'Agree'<br/>Record dirty team delta
    T-->>A1: Return Proposal ID (VP-xxxx)

    A2->>T: Call cast_vote(proposal_id='VP-xxxx', vote='Agree', public=False)
    Note over T: Acquire async team.state_lock<br/>Validate identity and record Voter 2 once<br/>Record dirty team delta
    T-->>A2: Success (1 voter remaining)

    A3->>T: Call cast_vote(proposal_id='VP-xxxx', vote='Agree')
    Note over T: Acquire async team.state_lock<br/>All 3 active members have voted.<br/>Agree: 3/3 (100% >= 2/3)<br/>Execute action: spawn Dynamic_QA
    T->>Manager: Spawn new member (Dynamic_QA) and append to T.members
    Note over T: Queue one incremental team delta
    T-->>A3: Success (Proposal approved and executed)
```

## 6. Lineage Migration Arbitration (Deep Dive)

The sequence diagram below visualizes the deeper lifecycle of a migration request under the default **Ancestor Approval Policy** (`"ancestor_approval"`):

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
    Manager->>Manager: Invalidate moved branch depth cache<br/>Queue affected team deltas
    
    Manager-->>T: Return success status
```
