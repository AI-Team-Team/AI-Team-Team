# Lineage Tree Mutations Flowcharts

ATT tracks an explicit forest with Agent, AgentTeam, or absent parents.

Creator provenance and membership never manufacture an organizational edge.

## 1. Dynamic Spawning & Tool Binding

```mermaid
flowchart TD
    Invoke["create_agent_team, launch_att or dispatch_subagent"] --> Parent["Validate explicit parent, depth, models and documents"]
    Parent --> Existing{"Existing identities or initiator membership?"}
    Existing -- "No" --> Stage["Stage fresh identities, Private DocLibs and Team DocLib"]
    Existing -- "Yes" --> Proposal["Persist exact proposal revision and invitations"]
    Proposal --> Mail["Address stable people through personal inboxes"]
    Mail --> Choice["Accepted, declined, explicitly ignored or no response"]
    Choice --> Revise{"Initiator revises material content?"}
    Revise -- "Yes" --> Reset["Append revision, reset consent and notify"]
    Reset --> Mail
    Revise -- "No" --> Eligible{"Accepted subset satisfies live minimum and rules?"}
    Eligible -- "Not yet" --> Mail
    Eligible -- "Yes" --> Create{"Explicit confirmation or configured unanimous auto-create?"}
    Create -- "Abandon" --> Abandon["Persist abandonment and notify every invitee"]
    Create -- "Create" --> Stage
    Stage --> Receipt["Commit staged membership and publication"]
    Receipt --> Live["AT exists; return reference immediately"]
    Live --> Initial["Optional initial task becomes addressed personal mail"]
    Live --> Late{"Explicit late acceptance and live policy permit joining?"}
    Late -- "Yes, including required confirmation" --> Join["Update relationship only"]
    Join --> Live
```

The initiator may optionally prepare and publish a validated candidate authored in current activity.

There is no compulsory draft discussion, detached synthesis, synchronous wait for invitees, or wait for child business completion.

Failure of later activity does not undo a successfully committed team.

## 2. Communication Request Routing

Communication policy comes only from ATTConfig.

Permissive endpoints and two independent endpoints deliver without an implicit channel.

Approval institutions retain actual path evidence and solicit exact personal-mail cases without a team execution barrier.

See [Autonomous Communication Governance](Autonomous_Communication_Governance.md) for the complete routing algorithm.

## 3. Autonomous Approval & Agreement Sequence

```mermaid
sequenceDiagram
    participant Broker
    participant Cases as Exact Governance Cases
    participant People as Eligible Continuing Agents
    participant Writer as Single Writer
    Broker->>Cases: Capture actual principals and frozen eligibility
    Cases->>Writer: Commit case and addressed mail
    Writer-->>People: Present personal notice at checkpoint
    People->>Writer: Explicit immutable case choices
    Note over People,Writer: Mail opening and read state are not votes
    alt Complete valid strict majority for every principal
        Broker->>Writer: Revalidate path and commit Agreement
    else Explicit denial
        Broker->>Writer: Deny Request and cancel unfinished Approvals
    else Missing, tied, failed or unavailable
        Broker->>Writer: Preserve pending authority
    end
```

No member order, creator identity, or virtual Root selects a substitute principal.

## 4. Dynamic Lineage Migration

```mermaid
sequenceDiagram
    participant AT as Moving AT
    participant Manager
    participant Parent as Actual Target Parent
    participant Cases as Required Authority Cases
    participant Writer
    AT->>Manager: request_migration(explicit parent or null, rationale)
    Manager->>Manager: Validate availability, cycles and cooldown
    alt Voluntary detachment allowed
        Manager->>Writer: Commit own-position change and cooldown
    else Attachment or migration
        Manager->>Writer: Persist request and captured real path
        Manager-->>AT: PENDING with durable request ID
        Manager->>Parent: Require explicit target acceptance
        Manager->>Cases: Solicit additional configured path approvals
        Cases-->>Manager: Receipt-backed explicit outcomes
        Manager->>Manager: Lock topology and revalidate exact authority
        Manager->>Writer: Commit position, acceptance, cooldown and one topology event
    end
    Writer-->>Manager: Exact acknowledgement
    Manager->>Manager: Publish pointers and invalidate descendant depth caches
    Manager-->>AT: Retained result and addressed notices
```

Successful changes to the team's own position start the confirmed 600-second cooldown.

Denial, failed publication, inherited movement, and forced parent loss do not charge it.

## 5. Democratic Membership Voting Sequence

Membership proposals retain identity-validated Agree/Disagree/Abstain ballots under the team's structural lock.

Eligible execution updates membership intervals and runtime relationships with one receipt rather than waiting for a round boundary.

Adding or removing a relationship never resets any existing person's identity, instructions, model, memory, or private workspace.

## 6. Parent Loss and Independent Reattachment

Retiring an Agent parent or dissolving an AgentTeam parent detaches surviving direct children.

Their descendants remain attached to those surviving children.

No virtual Root adoption or automatic membership change occurs.

An independent AT may later seek a new actual parent, whose explicit acceptance remains required even under permissive migration.
