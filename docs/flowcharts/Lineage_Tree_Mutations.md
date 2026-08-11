# Lineage Tree Mutations Flowcharts

This document consolidates the sequence flows that govern how the AgentTeam topology grows, restructures itself, and authorizes cross-team communication.

## 1. Dynamic Spawning & Tool Binding

This flowchart outlines the logic executed when an `Agent` or `AgentTeam` launches a dynamic sub-team:

```mermaid
flowchart TD
    Start["Call creator.launch_att(manager, member_configs)"] --> EnforceSize{"Configured minimum team size satisfied?"}
    EnforceSize -- "No" --> RaiseError["Raise ValueError<br/>Spawning blocked"]
    EnforceSize -- "Yes" --> GenerateID["Generate unique team_id: AT-xxxxxx"]
    GenerateID --> SpawnMembers["Create or reuse member Agents<br/>with stable Agent UUIDs"]
    SpawnMembers --> RegisterAgents["Register every Agent through ATTManager<br/>Reuse or create one private DocLib each"]
    RegisterAgents --> CreateTeam["Instantiate AgentTeam with creator link"]
    CreateTeam --> CreateDocLib["Create and register built-in team DocLib<br/>Populate initial documents"]
    CreateDocLib --> BindTools["Bind default and global tools<br/>att_manager context is already reserved"]
    BindTools --> RegisterTeam["Register team in manager.teams"]
    RegisterTeam --> CreatorIsTeam{"Is creator an AgentTeam?"}
    CreatorIsTeam -- "Yes" --> AddChildLink["Add child reference and parent mapping"]
    CreatorIsTeam -- "No" --> Save["Queue incremental entity and file deltas"]
    AddChildLink --> Save
    Save --> End["Dynamic AgentTeam active"]
```

## 2. Communication Request Routing

Communication policy comes only from `ATTConfig.communication`.

An Agent supplies the action for its invocation-scoped AgentTeam, but that action does not grant the Agent independent institutional authority.

```mermaid
sequenceDiagram
    autonumber
    participant Agent as Current Agent
    participant Sender as Sender AgentTeam
    participant Broker as NegotiationBroker
    participant Config as ATTConfig.communication
    participant Recipient as Recipient AgentTeam

    Agent->>Broker: request_peer_communication(recipient_id, rationale)
    Broker->>Sender: Validate invocation-scoped membership
    Broker->>Config: Read policy, delivery, and direction
    alt permissive
        Broker-->>Agent: APPROVED (Agreement not required)
    else parent_approval or lineage_approval
        Broker->>Broker: Resolve ordered explicit ApprovalPrincipals
        Broker->>Broker: Persist Request, Approvals, policy snapshot, and route fingerprint
        Broker->>Recipient: Queue or wake each AgentTeam principal
        Broker-->>Agent: PENDING_APPROVAL
    end
```

## 3. Autonomous Approval & Agreement Sequence

AgentTeam principals decide through a serialized discussion and full-member ballots, while an explicit Agent principal decides under its own invocation lock.

The Root AI participates as `ApprovalPrincipal(kind="agent")` only when the configured topology path requires it.

```mermaid
sequenceDiagram
    autonumber
    participant Broker as NegotiationBroker
    participant Team as AgentTeam Principal
    participant Members as Frozen Team Members
    participant Root as Explicit Agent Principal
    participant DB as Persistence Writer

    Broker->>Team: Queue or wake governance request
    Team->>Team: Acquire normal discussion_lock
    Team->>Members: Run governance discussion
    Members-->>Team: Every member returns strict JSON boolean ballot
    opt Route includes Root AI Agent
        Broker->>Root: Run serialized strict Agent decision
        Root-->>Broker: APPROVED, DENIED, or transient PENDING
    end
    alt Any principal denies
        Broker->>DB: Persist DENIED and cancel unfinished Approvals
    else Failure, cancellation, tie, or incomplete participation
        Broker->>DB: Restore affected Approval to PENDING
    else Every principal approves and route is unchanged
        Broker->>DB: Atomically persist APPROVED Request and Agreement
    else Relevant route changed
        Broker->>DB: Persist STALE Request and successor Request
    end
```

The complete communication state machine is documented in [Autonomous Communication Governance](Autonomous_Communication_Governance.md).

## 4. Dynamic Lineage Migration (Overview)

This sequence diagram illustrates how an active AgentTeam requests a topology migration under the configured migration policy:

```mermaid
sequenceDiagram
    autonumber
    participant T as Migrating AgentTeam
    participant Manager as ATTManager
    participant Policy as Migration Policy
    participant Principals as Explicit Approval Principals
    participant Old as Old Parent AgentTeam
    participant New as New Parent AgentTeam

    T->>Manager: request_migration(target_parent_id, rationale)
    Manager->>Manager: Validate migration limit and cycle constraints
    Manager->>Policy: authorize_migration outside topology lock
    Policy->>Principals: AgentTeam ballots or Root Agent decision
    Principals-->>Policy: Strict governance outcomes
    Policy-->>Manager: Authorization result and approved path
    Manager->>Manager: Acquire topology lock
    Manager->>Manager: Revalidate parents, path, cycle, and migration count
    alt Revalidation fails
        Manager-->>T: Fail closed
    else Revalidation succeeds
        Manager->>Old: Remove child pointer
        Manager->>New: Add child pointer
        Manager->>T: Replace parent pointer and invalidate descendant depth caches
        Manager->>Manager: Commit topology and inbox deltas
        Manager-->>T: Return success status
    end
```

## 5. Democratic Membership Voting Sequence

This sequence diagram illustrates the lifecycle of a membership proposal from initiation to atomic execution:

```mermaid
sequenceDiagram
    autonumber
    participant A1 as Initiating Agent
    participant T as AgentTeam
    participant A2 as Other Member
    participant A3 as Other Member
    participant Manager as ATTManager

    A1->>T: initiate_membership_vote(action, target, proposed_details)
    Note over T: Acquire state_lock<br/>Create proposal<br/>Record initiator ballot
    T-->>A1: Return proposal ID
    A2->>T: cast_vote(proposal_id, ballot)
    Note over T: Under the same state_lock<br/>Validate active identity and reject duplicates
    A3->>T: cast_vote(proposal_id, ballot)
    alt Participation and threshold requirements pass
        T->>Manager: Execute add/remove action at most once
        Manager-->>T: Register or remove member atomically
    else Proposal remains incomplete or is rejected
        T-->>A3: Persist current or terminal proposal state
    end
```

## 6. Lineage Migration Arbitration (Deep Dive)

The default `ancestor_approval` policy uses only explicit authorities.

```mermaid
sequenceDiagram
    autonumber
    participant T as Migrating AgentTeam
    participant Manager as ATTManager
    participant Policy as AncestorApprovalMigrationPolicy
    participant Old as Current Parent Principal
    participant New as Target Parent Principal
    participant LCA as LCA Principal

    T->>Manager: request_migration(target_parent_id, rationale)
    Manager->>Manager: Capture current parent, target parent, LCA, and topology version
    Manager->>Policy: authorize_migration(T, target, Manager, rationale)
    Note over Policy: Ordinary authorities are agent_team principals<br/>Root-level authority is the Root AI agent principal<br/>Duplicate principals are removed
    Policy->>Old: Request strict AgentTeam ballot or Agent decision
    Old-->>Policy: Governance outcome
    Policy->>New: Request strict AgentTeam ballot or Agent decision
    New-->>Policy: Governance outcome
    Policy->>LCA: Request strict AgentTeam ballot or Agent decision
    LCA-->>Policy: Governance outcome
    alt Every required principal approves
        Policy-->>Manager: approved=True
        Manager->>Manager: Lock and revalidate the exact authorized topology path
        Manager->>Manager: Atomically relink pointers and invalidate moved branch depth cache
        Manager->>Old: Queue migration alert
        Manager->>New: Queue migration alert
        Manager->>T: Queue migration confirmation
        Manager-->>T: Success
    else Any decision is invalid, unavailable, pending, or denied
        Policy-->>Manager: approved=False
        Manager-->>T: Fail closed without topology mutation
    end
```
