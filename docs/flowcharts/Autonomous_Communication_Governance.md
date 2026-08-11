# Autonomous Communication Governance

This document maps the complete lifecycle of ATT communication authority, channel approval, durable delivery, recovery, and revocation.

`ATTConfig` defines the communication institution for every AgentTeam at every topology depth.

An Agent performs the tool invocation, but all communication authority comes from its invocation-scoped AgentTeam.

## 1. Authority Boundary and Public Operations

Communication tools resolve both the active Agent and active AgentTeam from invocation `ContextVar` state.

The Agent must be active, registered, and a current member of that AgentTeam.

The tools do not accept sender, policy, direction, mode, or approval-principal overrides.

```mermaid
flowchart TD
    Invoke["Agent invokes communication tool"] --> TeamContext{"Active AgentTeam ContextVar exists?"}
    TeamContext -- "No" --> Closed["Fail closed with structured result"]
    TeamContext -- "Yes" --> AgentContext{"Active Agent ContextVar exists?"}
    AgentContext -- "No" --> Closed
    AgentContext -- "Yes" --> Registered{"Agent and AgentTeam are registered?<br/>Agent is active and is a current member?"}
    Registered -- "No" --> Closed
    Registered -- "Yes" --> Operation{"Requested operation"}
    Operation -- "send_peer_message" --> SendFlow["Durable delivery flow"]
    Operation -- "request_peer_communication" --> RequestFlow["Request lifecycle"]
    Operation -- "revoke_peer_agreement" --> RevokeFlow["Endpoint revocation flow"]
    Operation -- "list_peer_requests" --> RequestView["Show endpoint or AgentTeam-principal requests"]
    Operation -- "list_peer_agreements" --> AgreementView["Show endpoint Agreements"]
```

The Root AI is an `agent` governance principal and is never a communication endpoint.

| Operation | Structured statuses |
| --- | --- |
| `send_peer_message` | `DELIVERED`, `NO_AGREEMENT` |
| `request_peer_communication` | `APPROVED`, `PENDING_APPROVAL`, `DENIED`, `ALREADY_ACTIVE` |
| `revoke_peer_agreement` | `REVOKED`, `ALREADY_REVOKED`, `FORBIDDEN` |

## 2. Communication Institution Selection

The policy is read from `ATTConfig.communication` and is copied into each governed request as an immutable policy snapshot.

`CommunicationConfig` is a strict Pydantic discriminated union with forbidden extra fields and runtime assignment validation.

```mermaid
flowchart TD
    Start["Validated invocation context"] --> Policy{"ATTConfig.communication.policy"}
    Policy -- "permissive" --> Direct["No Request and no implicit Agreement<br/>Proceed directly to durable message delivery"]
    Policy -- "parent_approval" --> ParentRoute["Resolve sender and recipient parent principals<br/>Remove duplicate principals"]
    Policy -- "lineage_approval" --> LineageRoute["Resolve unique sender-to-recipient topology route<br/>Exclude sender and include recipient"]
    ParentRoute --> Governed["Create or reuse CommunicationRequest"]
    LineageRoute --> Governed
```

Approval configurations also define `request_delivery` as `queue` or `wake` and `direction` as `one_way` or `bidirectional`.

Changing `ATTConfig.communication` later does not modify an existing request snapshot or revoke an active Agreement.

Approval institutions create persistent channels only and do not provide a single-message approval mode.

## 3. Approval Principal Path Algorithms

Every approval authority is an immutable `ApprovalPrincipal(kind="agent_team" | "agent", principal_id=...)`.

### Parent Approval

An ordinary AgentTeam parent becomes an `agent_team` principal.

A top-level AgentTeam has the Root AI Agent as its parent principal.

```mermaid
flowchart LR
    Sender["Sender AgentTeam"] --> SenderParent{"Has AgentTeam parent?"}
    SenderParent -- "Yes" --> SP["agent_team: sender parent"]
    SenderParent -- "No" --> RootA["agent: Root AI"]
    Recipient["Recipient AgentTeam"] --> RecipientParent{"Has AgentTeam parent?"}
    RecipientParent -- "Yes" --> RP["agent_team: recipient parent"]
    RecipientParent -- "No" --> RootB["agent: Root AI"]
    SP --> Deduplicate["Preserve order and remove duplicate principal keys"]
    RootA --> Deduplicate
    RP --> Deduplicate
    RootB --> Deduplicate
```

### Lineage Approval

The sender's act of requesting the channel is the sender AgentTeam's consent, so the sender is excluded from the approval path.

The recipient and every intermediate AgentTeam on the unique route are included.

The Root AI Agent is included only when the route crosses separate top-level branches.

```mermaid
flowchart LR
    Sender["Sender AgentTeam<br/>excluded"] --> SenderAncestors["Sender ancestors up to LCA"]
    SenderAncestors --> LCA{"Shared AgentTeam LCA exists?"}
    LCA -- "Yes" --> RecipientBranch["Descend from LCA toward recipient"]
    LCA -- "No" --> Root["agent: Root AI"]
    Root --> RecipientTop["Recipient top-level AgentTeam"]
    RecipientTop --> RecipientBranch
    RecipientBranch --> Recipient["Recipient AgentTeam<br/>included"]
    Recipient --> Ordered["Ordered and deduplicated ApprovalPrincipal route"]
```

## 4. CommunicationRequest Creation and Deduplication

`request_peer_communication()` never sends a message and never creates a request under the permissive institution.

Under an approval institution, the request operation first checks for an already sufficient Agreement and then checks for an equivalent pending request.

```mermaid
sequenceDiagram
    autonumber
    participant Agent as Calling Agent
    participant Team as Sender AgentTeam
    participant Broker as NegotiationBroker
    participant DB as Single SQLite Writer
    participant Approvers as Approval Principals

    Agent->>Broker: request_peer_communication(recipient_id, rationale)
    Broker->>Broker: Validate registered endpoints and initiating membership
    Broker->>Broker: Read policy snapshot, direction, ordered principals, and route fingerprint
    alt Sufficient active Agreement exists
        Broker-->>Agent: ALREADY_ACTIVE with agreement_id
    else Equivalent PENDING or PROCESSING Request exists
        Broker-->>Agent: PENDING_APPROVAL with existing request_id
    else New governed Request
        Broker->>Broker: Create Request and one ordered Approval per principal
        Broker->>Broker: Add one notification for every AgentTeam principal
        Broker->>DB: Commit Request, Approvals, and inbox deltas
        alt Commit fails
            DB-->>Broker: Persistence error
            Broker->>Broker: Remove only the newly created state and notifications
            Broker-->>Agent: Propagate persistence error
        else Commit succeeds
            DB-->>Broker: Durable confirmation
            Broker->>Approvers: Schedule according to stored request_delivery
            Broker-->>Agent: PENDING_APPROVAL with request_id
        end
    end
```

Equivalent pending requests are matched by endpoints, direction, and policy snapshot.

A denied request does not prevent a later request with a new request ID and rationale.

## 5. Queue and Wake Delivery

AgentTeam and Agent principals use different scheduling because only AgentTeams have discussion inboxes.

```mermaid
flowchart TD
    Approval["Pending Approval"] --> Principal{"Principal kind"}
    Principal -- "agent" --> AgentWorker["Schedule serialized Agent approval worker immediately"]
    Principal -- "agent_team" --> Delivery{"Stored request_delivery"}
    Delivery -- "queue" --> Queue["Keep notification in AgentTeam inbox<br/>Wait for next normal discussion"]
    Delivery -- "wake" --> Wake["Schedule governance discussion immediately"]
    Queue --> TeamLock["Wait for the same discussion_lock used by normal and emergency sessions"]
    Wake --> TeamLock
    AgentWorker --> AgentLock["Wait for that Agent's invocation lock"]
```

Scheduling is deduplicated by `request_id + principal`.

Approval tasks are never awaited inside the initiating communication tool stack.

Different AgentTeams may process approvals concurrently, while the same AgentTeam remains serialized.

## 6. AgentTeam Governance Decision

The active member set is frozen only after the AgentTeam discussion lock has been acquired.

The governance discussion must reach its successful session boundary before ballots may begin.

```mermaid
sequenceDiagram
    autonumber
    participant Broker as NegotiationBroker
    participant Team as Approval AgentTeam
    participant Members as Frozen Active Members
    participant DB as Single SQLite Writer

    Broker->>Team: Claim Approval as PROCESSING
    Broker->>DB: Queue PROCESSING delta
    Team->>Team: Acquire discussion_lock
    Team->>Team: Freeze active member set
    Team->>Members: Run formal governance discussion
    alt Discussion, audit, or member reasoning fails
        Team-->>Broker: Incomplete decision
        Broker->>DB: Restore Approval and Request to PENDING
    else Discussion succeeds
        Team->>Members: Request one strict final JSON ballot from every frozen member
        Members-->>Team: {"approved": true|false, "reason": "..."}
        alt Membership changed or any ballot is missing/invalid
            Team-->>Broker: PENDING
        else Strictly more than half true
            Team-->>Broker: APPROVED with durable ballots
        else Strictly more than half false
            Team-->>Broker: DENIED with durable ballots
        else Tie
            Team-->>Broker: PENDING with durable ballots
        end
    end
```

Strings, numbers, null, missing fields, and extra fields are invalid ballots.

Every frozen member must produce a valid ballot before a majority can become authoritative.

## 7. Agent Governance Decision

An Agent principal may decide only for its own explicitly listed authority.

No other Agent can substitute for an unavailable Agent principal.

```mermaid
sequenceDiagram
    autonumber
    participant Broker as NegotiationBroker
    participant Agent as Explicit Agent Principal
    participant DB as Single SQLite Writer

    Broker->>Broker: Claim Approval as PROCESSING
    Broker->>Agent: Wait for Agent invocation lock
    Broker->>Agent: Request strict JSON literal boolean decision
    alt Explicit literal true
        Agent-->>Broker: APPROVED
    else Explicit literal false
        Agent-->>Broker: DENIED
    else Invalid JSON, unavailable Agent, model failure, or cancellation
        Agent-->>Broker: PENDING with reason
    end
    Broker->>DB: Commit resulting Approval state
```

Root AI approvals use this exact Agent path without a special Root principal type.

## 8. Approval Completion, Denial, and STALE Successors

Approval completion mutates communication state under the manager-level communication transaction lock without holding that lock during LLM work.

```mermaid
flowchart TD
    Outcome{"Principal outcome"} -- "PENDING" --> Retry["Approval=PENDING<br/>Request=PENDING<br/>Keep notification for retry"]
    Outcome -- "DENIED" --> Denied["Approval=DENIED<br/>Request=DENIED<br/>Cancel unfinished Approvals<br/>Remove request notifications"]
    Outcome -- "APPROVED" --> Mark["Approval=APPROVED<br/>Remove this principal notification"]
    Mark --> All{"Every required Approval is APPROVED?"}
    All -- "No" --> Waiting["Request=PENDING"]
    All -- "Yes" --> Recompute["Recompute principals from stored policy snapshot"]
    Recompute --> Fingerprint{"Route fingerprint unchanged?"}
    Fingerprint -- "No" --> Stale["Old Request=STALE<br/>Create linked successor Request<br/>Enqueue successor principals"]
    Fingerprint -- "Yes" --> Agreement["Request=APPROVED<br/>Create CommunicationAgreement"]
    Retry --> Commit["Commit exact Request, Approval, ballot, Agreement, and inbox delta"]
    Denied --> Commit
    Waiting --> Commit
    Stale --> Commit
    Agreement --> Commit
    Commit --> Result{"Persistence result"}
    Result -- "Success" --> Publish["Emit metadata-only system event"]
    Result -- "Failure" --> Rollback["Restore only affected communication records and notifications<br/>Preserve unrelated concurrent inbox changes"]
```

A relevant topology change produces a linked successor instead of applying an authorization from the old route.

An unrelated topology change does not alter the route fingerprint and does not invalidate the request.

## 9. CommunicationAgreement Direction and Supersession

An approved request creates exactly one persistent Agreement.

```mermaid
flowchart TD
    Approved["Approved Request"] --> Direction{"Stored direction"}
    Direction -- "one_way" --> OneWay["Permit source → target only"]
    Direction -- "bidirectional" --> Both["Permit source ↔ target"]
    Both --> Existing{"Active one-way Agreements exist for same endpoints?"}
    Existing -- "Yes" --> Supersede["Atomically deactivate old channels<br/>Record superseding agreement_id"]
    Existing -- "No" --> Active["Activate new Agreement"]
    Supersede --> Active
    OneWay --> Active
```

An active bidirectional Agreement satisfies later requests in either endpoint order.

Opposite one-way Agreements may coexist until a bidirectional Agreement supersedes them.

Agreements remain active until an endpoint revokes them explicitly.

## 10. Durable Peer Message Delivery and Consumption

`send_peer_message()` performs delivery only and never creates a Request automatically.

```mermaid
sequenceDiagram
    autonumber
    participant Agent as Calling Agent
    participant Broker as NegotiationBroker
    participant Recipient as Recipient AgentTeam
    participant DB as Single SQLite Writer
    participant Discussion as Recipient Discussion

    Agent->>Broker: send_peer_message(recipient_id, message)
    Broker->>Broker: Validate endpoints and initiating membership
    alt Current policy is permissive
        Broker->>Broker: agreement_id remains null
    else No active Agreement covers this direction
        Broker-->>Agent: NO_AGREEMENT and request guidance
    else Active Agreement covers this direction
        Broker->>Broker: Attach agreement_id
    end
    Broker->>Broker: Check tool invocation idempotency key
    alt Same key and identical message already exists
        Broker-->>Agent: DELIVERED with existing message_id
    else Same key is bound to different content or route
        Broker-->>Agent: Fail with idempotency conflict
    else New delivery
        Broker->>Recipient: Append durable peer-message inbox record
        Broker->>DB: Commit PeerMessage and recipient inbox delta
        alt Commit fails
            Broker->>Recipient: Remove only this inbox record
            Broker->>Broker: Remove this PeerMessage
            Broker-->>Agent: Propagate persistence error
        else Commit succeeds
            Broker-->>Agent: DELIVERED with message_id
        end
    end
    Discussion->>Recipient: Consume message during a successful discussion
    alt Discussion succeeds
        Discussion->>DB: Mark delivery consumed and remove inbox record
    else Discussion fails or is cancelled
        Discussion->>Recipient: Keep pending inbox record
    end
```

Callbacks and system events contain IDs, endpoints, paths, operation types, and results without logging peer-message content.

## 11. Endpoint Revocation

Only the source or target AgentTeam may revoke an Agreement.

Approval principals and unrelated AgentTeams cannot revoke the channel.

```mermaid
sequenceDiagram
    autonumber
    participant Agent as Calling Agent
    participant Endpoint as Invocation AgentTeam
    participant Broker as NegotiationBroker
    participant DB as Single SQLite Writer

    Agent->>Broker: revoke_peer_agreement(agreement_id, reason)
    Broker->>Broker: Resolve actor AgentTeam from ContextVar
    alt Actor is not an endpoint
        Broker-->>Agent: FORBIDDEN
    else Agreement is already inactive
        Broker-->>Agent: ALREADY_REVOKED
    else Actor is source or target endpoint
        Broker->>Broker: Set inactive, timestamp, endpoint ID, and reason
        Broker->>DB: Commit Agreement delta
        alt Commit fails
            Broker->>Broker: Restore active Agreement state
            Broker-->>Agent: Propagate persistence error
        else Commit succeeds
            Broker-->>Agent: REVOKED
        end
    end
```

Revocation does not delete historical requests, approvals, ballots, Agreements, or delivery records.

## 12. Persistence, Restore, and Shutdown

Schema 6 stores requests, ordered approvals, ballots, Agreements, peer deliveries, and correlated AgentTeam inbox records.

```mermaid
flowchart TD
    Open["Open SQLite state database"] --> Preflight["Read schema version before create_all or DDL"]
    Preflight --> Version{"Schema version is 6?"}
    Version -- "No" --> Reject["StateRestoreError<br/>Database remains unmodified"]
    Version -- "Yes" --> Stage["Read into detached staging manager and staged DocLib root"]
    Stage --> Validate["Validate endpoints, initiators, principal kinds and references,<br/>approval ordering and state combinations,<br/>ballots, fingerprints, successor chains,<br/>Agreement uniqueness and source requests,<br/>delivery routes and inbox correlation"]
    Validate --> Valid{"All invariants valid?"}
    Valid -- "No" --> Preserve["StateRestoreError<br/>Original manager and DocLibs remain unchanged"]
    Valid -- "Yes" --> Reset["Reset persisted PROCESSING Request and Approval states to PENDING"]
    Reset --> Publish["Atomically publish staged runtime state and DocLib directories"]
    Publish --> Resume["Resume pending Root Agent workers and wake-mode AgentTeam work"]

    Shutdown["manager.close()"] --> Stop["Stop accepting new tasks and cancel external LLM waits"]
    Stop --> Release["Reset claimed PROCESSING Approvals to PENDING"]
    Release --> Flush["Commit accepted communication and other state deltas without arbitrary flush timeout"]
    Flush --> Close["Release SQLite engine, writer thread, and writer lease"]
```

Restore rejects missing endpoints, missing initiating Agents, unauthorized Agent principals, malformed status combinations, duplicate routes, broken successor chains, invalid Agreement sources, and orphaned peer-delivery notifications.

Each SQLite database permits only one active writer manager through a cross-process writer lease.

The persistence coordinator keeps at most one active delta and one coalesced pending delta.

## 13. Isolation Invariants

* Communication Agreements never grant DocLib ACL, public-discovery, managed-link, or file permissions.
* A communication AgentTeam cannot use an Agent's Private DocLib unless that Agent explicitly invokes a private tool as its owner.
* Communication rationale and peer-message content do not become authority credentials.
* Root AI governance authority does not make Root AI a peer-message endpoint.
* AgentTeam authority is recorded as the AgentTeam even though individual Agents provide ballots and tool invocations.
* Member order, creator identity, role labels, and model availability never create implicit communication authority.
