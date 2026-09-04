# ATT System Architecture

This master diagram presents the major runtime modules, their ownership boundaries, and the primary data flows across ATT. It is intentionally broader than the subsystem-specific diagrams in this directory while still showing the important concurrency, governance, privacy, and persistence boundaries.

```mermaid
flowchart TB
    subgraph Host["Host Runtime and Configuration"]
        HostApp["Host Application"]
        Config["Validated ATTConfig<br/>topology, communication, migration,<br/>failover, tools, audit, limits, workspace"]
        Bindings["Runtime Bindings<br/>LLM clients, stable model aliases,<br/>generator handler, custom tools, auditors"]
        Manager["ATTManager<br/>public facade and domain coordinator"]
        RuntimeLifecycle["Runtime Gate and Shutdown<br/>stop admissions, cancel external calls,<br/>flush state and callbacks"]
        Events["Ordered Background Event Dispatcher<br/>callbacks, logs, status, system events"]

        HostApp --> Manager
        Config --> Manager
        Bindings --> Manager
        Manager --> RuntimeLifecycle
        Manager --> Events
        Events --> HostApp
    end

    subgraph Identity["Stable Identity, Lifecycle, and Recursive Topology"]
        Root["Root AI Agent<br/>stable Agent UUID and root governance principal"]
        AgentRegistry["Agent Registry<br/>active, retained, archived identities"]
        AgentState["Agent-Owned State<br/>identity role, instructions, model binding,<br/>memory, locks, lifecycle, Private DocLib ID"]
        Membership["Role-Neutral Membership Relation<br/>team_id ↔ agent_id only"]
        TeamRegistry["AgentTeam Registry<br/>creator, members, parent, children, purpose"]
        Topology["Recursive AgentTeam Lineage<br/>top-level, child, and descendant teams"]
        Delegation["Dynamic Delegation<br/>depth and team-size gates, presets,<br/>new identities or existing Agent IDs"]
        TeamCreation["Atomic Team Creation<br/>validate → stage Agents and DocLibs → publish"]
        AgentLifecycle["Explicit Agent Lifecycle<br/>register, retire, reactivate, confirmed delete"]
        TeamStateLock["Per-AgentTeam state_lock<br/>membership, proposals, votes, and inbox structure"]
        TopologyLock["Manager Topology Lock<br/>revalidate before atomic mutation"]

        Root --> AgentRegistry
        AgentRegistry --> AgentState
        AgentRegistry --> Membership
        Membership --> TeamRegistry
        TeamRegistry --> Topology
        Root -->|top-level governance| Topology
        Delegation --> TeamCreation
        TeamCreation --> AgentRegistry
        TeamCreation --> TeamRegistry
        AgentLifecycle --> AgentRegistry
        TeamRegistry --> TeamStateLock
        TeamStateLock --> Membership
        TopologyLock --> TeamRegistry
    end

    subgraph Discussion["Serialized AgentTeam Discussions"]
        DiscussionEntry["Normal, Emergency, or Governance Discussion"]
        DiscussionLock["Per-AgentTeam discussion_lock<br/>one active session per AgentTeam"]
        Session["Discussion Session<br/>discussion ID, running state, migration counter"]
        InboxClaim["Claim Pending Inbox Items<br/>restore on failure, acknowledge on success"]
        Round["Round Coordinator<br/>freeze active membership for this round"]
        ParallelTurns["Concurrent Member Turns<br/>different Agents may run in parallel"]
        RoundResult["DiscussionRoundResult<br/>completed and incomplete member turns"]
        Transcript["Transcript with Team and Discussion Provenance"]
        DiscussionResult["DiscussionResult<br/>COMPLETED or PARTIAL"]
        DiscussionCleanup["Cleanup and Deferred Changes<br/>release session state and persist deltas"]

        DiscussionEntry --> DiscussionLock
        DiscussionLock --> Session
        Session --> InboxClaim
        TeamStateLock -. protects .-> InboxClaim
        InboxClaim --> Round
        Round --> ParallelTurns
        ParallelTurns --> RoundResult
        RoundResult -->|next round context| Round
        RoundResult --> Transcript
        Transcript --> DiscussionResult
        DiscussionResult --> DiscussionCleanup
    end

    subgraph Execution["Invocation-Scoped Agent and Tool Execution"]
        InvocationContext["ContextVars<br/>active Agent, AgentTeam, discussion, tool call"]
        AgentInvocationLock["Per-Agent invocation lock<br/>serializes one shared Agent across teams"]
        Prompt["Prompt Assembly<br/>identity, current AgentTeam, topology, experts,<br/>inbox, proposals, previous round, bounded memory"]
        ToolView["Invocation-Scoped Tool Resolver<br/>hide unavailable delegation or escalation tools"]
        Strategy{"Reasoning Strategy"}
        TextMode["Text ReAct<br/>balanced Action scanner and literal parser"]
        NativeMode["Native Tool Calling<br/>provider-neutral List[Tool]"]
        ToolExecutor["Shared ToolExecutor<br/>context, signature, strict type and schema validation"]
        ToolAuditor["Optional ToolAuditor Gate"]
        RetryPolicy["Typed Error Classification<br/>argument correction and safe execution retry budgets"]
        ToolResult["Structured ToolResult<br/>status, error kind, attempts, safe observation"]
        TurnResult["AgentTurnResult<br/>COMPLETED or INCOMPLETE"]
        Memory["Continuous Agent Memory<br/>team_id and discussion_id provenance"]
        Window["Bounded Model Window<br/>compression and team-aware selection"]
        Adapter["LLM Adapter Layer<br/>sync, async, streaming, structured response normalization"]
        TokenLedger["Atomic Token Ledger<br/>reserve maximum budget → settle actual usage → refund"]
        Provider["Bound Model or Generator Handler"]
        FailoverGate["Configured Failover<br/>auto selection or governed parent decision"]

        ParallelTurns --> InvocationContext
        InvocationContext --> AgentInvocationLock
        AgentInvocationLock --> Prompt
        Memory --> Window
        Window --> Prompt
        ToolView --> Prompt
        ToolView --> ToolExecutor
        Prompt --> Strategy
        Strategy --> TextMode
        Strategy --> NativeMode
        TextMode --> Adapter
        NativeMode --> Adapter
        Adapter --> TokenLedger
        TokenLedger --> Provider
        TokenLedger -->|quota exhausted| FailoverGate
        FailoverGate --> Adapter
        TextMode --> ToolExecutor
        NativeMode --> ToolExecutor
        ToolExecutor --> ToolAuditor
        ToolAuditor --> RetryPolicy
        RetryPolicy --> ToolResult
        ToolResult --> Strategy
        Strategy --> TurnResult
        TurnResult --> Memory
        TurnResult --> RoundResult
    end

    subgraph Governance["Autonomous Governance and Cross-Team Coordination"]
        MembershipProposal["Membership Proposal<br/>atomic identity-validated ballots"]
        CommunicationConfig{"Communication Institution<br/>permissive, parent approval, lineage approval"}
        Broker["NegotiationBroker<br/>routing, requests, approvals, agreements, delivery"]
        CommunicationLocks["Broker State and Transaction Locks<br/>claim and commit without awaiting LLM under lock"]
        DirectDelivery["Permissive Durable Delivery<br/>no implicit Agreement"]
        CommRequest["CommunicationRequest<br/>immutable policy snapshot, ordered principals,<br/>route fingerprint, PENDING or PROCESSING"]
        ApprovalRecords["Per-Principal Approvals and Agent Ballots<br/>pending, processing, approved, denied, cancelled"]
        DeliveryMode{"Request Delivery<br/>queue or wake"}
        PrincipalDecision["Explicit Principal Decision<br/>AgentTeam full-member ballot or Root Agent decision"]
        PathCheck["Final Route Revalidation<br/>changed route → STALE and successor Request"]
        Agreement["Directional CommunicationAgreement<br/>one-way or bidirectional, endpoint-revocable"]
        PeerMessage["Idempotent Peer Message Delivery<br/>durable message and recipient inbox record"]
        MigrationPolicy{"Migration Policy<br/>permissive, ancestor approval, lineage path"}
        MigrationDecision["Explicit Migration Principals<br/>AgentTeam ballot or Root Agent decision"]
        MigrationCommit["Revalidate lineage, cycle, parent, and limit<br/>then atomically relink topology"]
        FailoverPolicy{"Failover Policy<br/>auto, parent, none"}
        ParentResourceDecision["Parent AgentTeam Model Ballot<br/>or Root Agent model decision"]

        ToolExecutor --> MembershipProposal
        MembershipProposal --> TeamStateLock
        ToolExecutor --> Broker
        CommunicationConfig --> Broker
        Broker --> CommunicationLocks
        CommunicationLocks -->|permissive| DirectDelivery
        CommunicationLocks -->|approval required| CommRequest
        CommRequest --> ApprovalRecords
        ApprovalRecords --> DeliveryMode
        DeliveryMode -->|queue| InboxClaim
        DeliveryMode -->|wake| DiscussionEntry
        DiscussionResult --> PrincipalDecision
        PrincipalDecision --> ApprovalRecords
        ApprovalRecords -->|all approved| PathCheck
        PathCheck --> Agreement
        Agreement --> PeerMessage
        DirectDelivery --> PeerMessage
        PeerMessage --> InboxClaim
        ToolExecutor --> MigrationPolicy
        MigrationPolicy -->|governed| MigrationDecision
        MigrationPolicy -->|permissive| MigrationCommit
        MigrationDecision --> MigrationCommit
        MigrationCommit --> TopologyLock
        FailoverPolicy -->|parent| ParentResourceDecision
        FailoverPolicy -->|auto| Adapter
        ParentResourceDecision --> Adapter
        FailoverGate --> FailoverPolicy
        PrincipalDecision -. uses .-> DiscussionLock
        PrincipalDecision -. Root Agent .-> AgentInvocationLock
        MigrationDecision -. uses .-> DiscussionLock
        ParentResourceDecision -. uses .-> DiscussionLock
    end

    subgraph Knowledge["Team Knowledge and Private Agent Workspaces"]
        TeamLibrary["Team DocLib<br/>owned by one AgentTeam"]
        TeamACL["Real-Time Prefix ACL<br/>READ and WRITE by current AgentTeam authority"]
        PrivateLibrary["Private Agent DocLib<br/>one workspace per identity, never disclosed automatically"]
        PrivateOwner["Active Invocation Agent Ownership Check<br/>team ACL cannot grant private access"]
        GatedReader["Gated Reader<br/>outline fallback and bounded line windows"]
        WorkspaceReader["Workspace GatedFileReader<br/>size gate, outline fallback, bounded line windows"]
        ManagedLinks["Managed Team-Library File Links<br/>registered targets and live ACL checks"]
        Publish["Explicit Private-to-Current-Team Publish<br/>copy ordinary file, never implicit disclosure"]
        LibraryLocks["Per-Library Locks<br/>ordered acquisition for cross-library operations"]

        TeamRegistry --> TeamLibrary
        AgentRegistry --> PrivateLibrary
        InvocationContext --> TeamACL
        InvocationContext --> PrivateOwner
        TeamACL --> TeamLibrary
        PrivateOwner --> PrivateLibrary
        TeamLibrary --> GatedReader
        TeamLibrary --> ManagedLinks
        ManagedLinks --> TeamACL
        PrivateLibrary --> Publish
        Publish --> TeamACL
        AgentLifecycle --> PrivateLibrary
        LibraryLocks --> TeamLibrary
        LibraryLocks --> PrivateLibrary
        ToolExecutor --> TeamACL
        ToolExecutor --> PrivateOwner
        ToolExecutor --> WorkspaceReader
    end

    subgraph Supervision["Independent Content and Operational Supervision"]
        AuditInput["Complete Transcript<br/>incomplete placeholders and redacted failure metadata"]
        Supervisors["Three-Agent Supervisory Audit<br/>integrity, continuity, deadlock"]
        ContentStatus{"AuditStatus<br/>HEALTHY, UNHEALTHY, UNKNOWN"}
        OperationalMode["Operational Decision Mode<br/>framework, supervisor, framework then supervisor"]
        OperationalStatus{"OperationalStatus<br/>HEALTHY, DEGRADED, UNKNOWN"}
        AlertRegistry["Persistent Deduplicated Alerts<br/>fingerprint, occurrence count, first and last time"]
        AlertRoute{"Configured Escalation<br/>none, queue, or wake"}
        ParentInbox["Parent AgentTeam Inbox<br/>processing acknowledgement and retry"]
        RootEvent["Root-Level System Event and Callback"]

        Transcript --> AuditInput
        RoundResult --> OperationalMode
        OperationalMode --> OperationalStatus
        AuditInput --> Supervisors
        Supervisors --> ContentStatus
        ContentStatus --> AlertRegistry
        OperationalStatus --> AlertRegistry
        AlertRegistry --> AlertRoute
        AlertRoute -->|queue| ParentInbox
        AlertRoute -->|wake| DiscussionEntry
        AlertRegistry -->|root level| RootEvent
        ParentInbox --> InboxClaim
    end

    subgraph Persistence["Asynchronous Incremental Persistence and Atomic Recovery"]
        DirtyTracking["Entity-Level Dirty Tracking<br/>Agent, AgentTeam, proposal, inbox, agreement,<br/>library metadata, permission, file path, token usage"]
        PersistedConfig["Persisted Configuration Metadata<br/>ATTConfig, model configs, presets, token usage"]
        Suppression["Task-Local Nested Auto-Save Suppression<br/>ContextVar batches one consistent delta"]
        Snapshot["Versioned Copy-on-Write Snapshot<br/>consistent shallow capture under state locks,<br/>authoritative updates and insert-only dependencies"]
        Materialize["Background Materialization<br/>deep copy, JSON serialization, ORM record assembly"]
        Coordinator["Single-Writer Coordinator<br/>one executing delta plus one coalesced pending delta"]
        Lease["Exclusive Cross-Process Writer Lease<br/>second writer fails immediately"]
        Database[(SQLite Schema 6<br/>foreign keys, WAL, busy timeout)]
        RestoreRead["Read Schema Version Before Mutation<br/>load all records into detached staging"]
        RestoreValidate["Strict Restore Validation<br/>identity, topology, model aliases, governance,<br/>DocLib ownership, ACL, links, deliveries"]
        RestoreFiles["Stage DocLib Files in Temporary Directories"]
        RestorePublish["Atomic Runtime and DocLib Publication<br/>failure leaves current manager unchanged"]

        AgentRegistry --> DirtyTracking
        TeamRegistry --> DirtyTracking
        Memory --> DirtyTracking
        MembershipProposal --> DirtyTracking
        Broker --> DirtyTracking
        MigrationCommit --> DirtyTracking
        TeamLibrary --> DirtyTracking
        PrivateLibrary --> DirtyTracking
        AlertRegistry --> DirtyTracking
        TokenLedger --> DirtyTracking
        Config --> PersistedConfig
        PersistedConfig --> DirtyTracking
        DirtyTracking --> Suppression
        Suppression --> Snapshot
        Snapshot --> Materialize
        Materialize --> Coordinator
        Lease --> Coordinator
        Coordinator --> Database
        Database --> RestoreRead
        RestoreRead --> RestoreValidate
        RestoreRead --> RestoreFiles
        RestoreValidate --> RestorePublish
        RestoreFiles --> RestorePublish
        Bindings -. runtime only .-> RestorePublish
        RestorePublish --> Manager
    end

    Manager --> Root
    Manager --> AgentRegistry
    Manager --> TeamRegistry
    Manager --> Delegation
    Manager --> DiscussionEntry
    Manager --> InvocationContext
    Manager --> ToolView
    Manager --> CommunicationConfig
    Manager --> MigrationPolicy
    Manager --> FailoverPolicy
    ToolExecutor --> Delegation
    RuntimeLifecycle --> Coordinator
    RuntimeLifecycle --> Events
    DiscussionCleanup --> DirtyTracking
    DiscussionCleanup --> Events
    ToolResult --> Events
    AlertRegistry --> Events
    Broker --> Events

    classDef host fill:#eceff1,stroke:#455a64,stroke-width:1.5px;
    classDef identity fill:#e3f2fd,stroke:#1976d2,stroke-width:1.5px;
    classDef discussion fill:#e0f7fa,stroke:#00838f,stroke-width:1.5px;
    classDef execution fill:#fffde7,stroke:#f9a825,stroke-width:1.5px;
    classDef governance fill:#fce4ec,stroke:#c2185b,stroke-width:1.5px;
    classDef knowledge fill:#e8f5e9,stroke:#388e3c,stroke-width:1.5px;
    classDef supervision fill:#fff3e0,stroke:#ef6c00,stroke-width:1.5px;
    classDef persistence fill:#ede7f6,stroke:#5e35b1,stroke-width:1.5px;

    style Host fill:#f4f7f9,stroke:#455a64,stroke-width:2px,color:#1f2937;
    style Identity fill:#eff6ff,stroke:#1976d2,stroke-width:2px,color:#1f2937;
    style Discussion fill:#ecfeff,stroke:#00838f,stroke-width:2px,color:#1f2937;
    style Execution fill:#fffbeb,stroke:#f9a825,stroke-width:2px,color:#1f2937;
    style Governance fill:#fff1f2,stroke:#c2185b,stroke-width:2px,color:#1f2937;
    style Knowledge fill:#f0fdf4,stroke:#388e3c,stroke-width:2px,color:#1f2937;
    style Supervision fill:#fff7ed,stroke:#ef6c00,stroke-width:2px,color:#1f2937;
    style Persistence fill:#f5f3ff,stroke:#5e35b1,stroke-width:2px,color:#1f2937;

    class HostApp,Config,Bindings,Manager,RuntimeLifecycle,Events host;
    class Root,AgentRegistry,AgentState,Membership,TeamRegistry,Topology,Delegation,TeamCreation,AgentLifecycle,TeamStateLock,TopologyLock identity;
    class DiscussionEntry,DiscussionLock,Session,InboxClaim,Round,ParallelTurns,RoundResult,Transcript,DiscussionResult,DiscussionCleanup discussion;
    class InvocationContext,AgentInvocationLock,Prompt,ToolView,Strategy,TextMode,NativeMode,ToolExecutor,ToolAuditor,RetryPolicy,ToolResult,TurnResult,Memory,Window,Adapter,TokenLedger,Provider,FailoverGate execution;
    class MembershipProposal,CommunicationConfig,Broker,CommunicationLocks,DirectDelivery,CommRequest,ApprovalRecords,DeliveryMode,PrincipalDecision,PathCheck,Agreement,PeerMessage,MigrationPolicy,MigrationDecision,MigrationCommit,FailoverPolicy,ParentResourceDecision governance;
    class TeamLibrary,TeamACL,PrivateLibrary,PrivateOwner,GatedReader,WorkspaceReader,ManagedLinks,Publish,LibraryLocks knowledge;
    class AuditInput,Supervisors,ContentStatus,OperationalMode,OperationalStatus,AlertRegistry,AlertRoute,ParentInbox,RootEvent supervision;
    class DirtyTracking,PersistedConfig,Suppression,Snapshot,Materialize,Coordinator,Lease,Database,RestoreRead,RestoreValidate,RestoreFiles,RestorePublish persistence;
```

## Reading Guide

- Solid arrows represent primary runtime or data flow.
- Dotted arrows represent a shared serialization boundary rather than ownership.
- Colored containers represent major ATT subsystems; nodes inherit the color of their owning subsystem even when another subsystem invokes them.
- This master diagram covers every top-level runtime subsystem; the linked subsystem diagrams expand internal state machines and failure branches without duplicating them here.

For narrower sequence and lifecycle diagrams, return to the [flowchart index](README.md).
