# Negotiation Broker & Sibling Routing Flowchart

This document details the dynamic P2P sibling and cross-lineage communication permissions negotiated by the `NegotiationBroker` under the ATT framework.

## 1. Sequence of Tools Context Registration & Team Spawning

This sequence diagram outlines the registration of system-wide dependencies and automatic tools binding during dynamic team spawning:

```mermaid
sequenceDiagram
    autonumber
    participant Mixin as AutonomyWorkflowMixin
    participant Manager as ATTManager
    participant Team as AgentTeam
    
    Mixin->>Manager: register_tools_context(context)
    Note over Manager: Save SQLite DB, Vector Store, Gated Reader context
    
    Mixin->>Manager: create_agent_team(creator, member_count=3)
    Note over Manager: Spawn AgentTeam with Creator (Agent/Team)
    Manager->>Team: Instantiate AgentTeam (N >= 3)
    Manager->>Manager: get_default_tools(tools_context, Team)
    Manager->>Team: Bind registered Tools dictionary
    Manager-->>Mixin: Return dynamic AgentTeam bound with Centralized Tools
```

## 2. Sibling & Cross-Lineage Negotiation Flowchart

This flowchart outlines the gating logic executed inside `NegotiationBroker.negotiate_communication` and `NegotiationBroker.establish_peer_agreement` when dynamic teams check or negotiate communication tunnels:

```mermaid
flowchart TD
    %% negotiate_communication flow
    Start1["Call negotiate_communication(sender, recipient)"] --> SiblingCheck{"sender_parent == recipient_parent?\n(Sibling Team Check)"}
    SiblingCheck -- "Yes" --> ParentSiblingTalk{"Evaluates shared parent's rules:\nallow_sibling_talk == True?"}
    ParentSiblingTalk -- "Yes" --> ApproveSibling["Return True"]
    ParentSiblingTalk -- "No" --> DenySibling["Return False"]
    
    SiblingCheck -- "No" --> AgreementCheck{"Symmetric Bidirectional Lookup:\n(sender_id, recipient_id) OR (recipient_id, sender_id)\nin peer_talk_agreements?"}
    AgreementCheck -- "Yes" --> ApproveSibling
    AgreementCheck -- "No" --> DenySibling

    %% establish_peer_agreement flow
    Start2["Call establish_peer_agreement(sender, recipient, rationale, mode)"] --> LineageCheck{"Both sender_parent and\nrecipient_parent exist?"}
    LineageCheck -- "No" --> FailAgreement["Return False\n(Lineage Incomplete)"]
    LineageCheck -- "Yes" --> ResolvePolicy["Resolve policy_name from config\n(or overridden by mode)"]
    
    ResolvePolicy --> PolicyCheck{"Policy strategy matches?"}
    PolicyCheck -- "permissive" --> ApproveCross["Add pair to peer_talk_agreements\nSave State\nReturn True"]
    PolicyCheck -- "rule_gated" --> CheckRules{"Symmetric parent rules match?\n(evaluate rules)"}
    CheckRules -- "Yes" --> ApproveCross
    CheckRules -- "No" --> FailAgreement
    
    PolicyCheck -- "proxied" --> QueryLeaders{"Query parent representatives\nvia LLM evaluation"}
    QueryLeaders -- "Both Approved" --> ApproveCross
    QueryLeaders -- "Any Rejected" --> FailAgreement
```
