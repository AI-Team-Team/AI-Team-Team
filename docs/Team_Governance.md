# Team Governance

ATTConfig defines the institution, AgentTeams hold organizational authority, and Agents act only through their actual invocation scope.

Membership, creator provenance, organizational parenthood, communication channels, personal email, and document permissions are separate relationships.

## 1. The Team Inbox & Communication Protocols

An AgentTeam inbox retains AT-addressed communication and governance references; it is not a shared model conversation.

Each Agent has one continuing personal runtime and identity-owned inbox, even when the Agent belongs to several teams.

Incoming notices are presented at committed personal checkpoints, never inserted into an in-flight provider request.

An Agent may explicitly read a message, discuss it through team chat, and independently submit a governance choice.

Ordinary model output is not automatically published, delivered as a reply, or treated as a ballot.

There are no discussion rounds, compulsory all-member execution barriers, or whole-team discussion-session locks.

Different people may act concurrently; the same person's invocation lock protects their single Working Context and memory across all memberships.

## 2. Peer Communication & Negotiation Broker

`NegotiationBroker` coordinates configured policy, persistent requests, approvals, Agreements, durable messages, and metadata-only events.

It never infers authority from member order, creator identity, role labels, or a Root fallback.

The public communication tools are:

- `send_peer_message(team_id, message)`
- `request_peer_communication(team_id, rationale)`
- `revoke_peer_agreement(agreement_id, reason)`
- `list_peer_requests(status="pending")`
- `list_peer_agreements(active_only=True)`
- `list_peer_messages()`
- `read_peer_message(message_id)`

All team-sensitive tools resolve the current active Agent and AgentTeam from invocation context and validate live membership.

No tool accepts a sender, policy, direction, mode, or approval-principal override.

Message records and their inbox references must commit before the sender receives `DELIVERED`.

An addressed reference does not copy the message body into every member's context, and reading does not imply a reply or governance approval.

Communication Agreements never grant DocLib, managed-link, or file permissions.

## 3. Inter-Team Communication Policies

`ATTConfig.communication` is a strict Pydantic discriminated union with forbidden extra fields and assignment validation.

### A. Permissive Policy (`"permissive"`)

Authenticated endpoint members may send directly without a Request or implicit Agreement.

Two independent AgentTeams also communicate this way under an approval institution.

Independence means an explicit organizational parent of `None`, not a depth label or creator identity.

### B. Parent Approval Policy (`"parent_approval"`)

Each attached endpoint's actual parent principal must approve the channel, with duplicate principals removed.

A parent can be an `agent_team` or an `agent`; Root AI participates only when it is the explicitly recorded Agent parent.

An independent endpoint contributes no parent authority, but does not exempt the other endpoint's actual parent.

### C. Lineage Approval Policy (`"lineage_approval"`)

The sender's request expresses the sender AT's consent.

ATT traverses the actual explicit-parent paths, excludes the sender, and includes the required recipient-side and intermediate authorities.

An independent endpoint exempts its own side only, not an attached endpoint or its authorities.

Separate independent trees do not gain a virtual common Root Agent.

A child of an independent AgentTeam remains attached to that AgentTeam and is not itself independent.

### D. Request Delivery and Direction

Approval configurations accept only `request_delivery="queue"`; `"wake"` is rejected rather than translated into a hidden all-member discussion.

An exact governance case delivers an addressed voting email to each eligible person through the common personal runtime.

Receiving that notice does not force the person to reply, change scope, or start another model persona.

`direction="one_way"` permits source-to-target communication, while `"bidirectional"` permits both directions.

### E. Approval Decisions

A governance case freezes its eligible people, principal, choice schema, electorate revision, and business request.

Each AgentTeam voter submits their own strict structured choice using `submit_governance_choice(case_id, choice)`.

All frozen members must provide valid ballots before a strict majority can authorize an outcome.

Strictly more than half literal `true` votes approve, and strictly more than half literal `false` votes deny.

Missing or invalid choices, a tie, changed eligibility, unavailable people, or failed activity do not create approval.

An Agent principal can submit only its own ballot; another person cannot substitute for it.

A committed ballot is immutable and idempotent within its exact case, and survives cancellation of an observer or a later ordinary activity failure.

An explicit retry after a tie or electorate change can create a fresh case while retaining preceding cases, mail, and choices.

### Personal Email Is Not a Ballot

`open_agent_mail(message_id)` inspects owned mail without changing its read receipt or submitting a choice.

`mark_agent_inbox_read()` changes only mail state.

`list_governance_requests(pending_only=True)` keeps unanswered eligible cases discoverable even after the emails are read.

Formation attitudes remain `accepted`, `declined`, `explicitly_ignored`, and `no_response`.

An explicit `None` withholds a public attitude and externally projects to `no_response`, independently of whether the email was opened.

Communication and migration use strict boolean choices, failover uses eligible model aliases, and membership proposals retain their own Agree/Disagree/Abstain rules.

Optional episodic memory is not required for voting, and a private DocLib is never automatically read to prepare a choice.

### F. Request and Agreement Lifecycle

A governed Request stores immutable policy, ordered approval principals, route evidence, fingerprints, reasons, timestamps, and linked successor references.

Equivalent pending requests reuse the existing request ID.

A valid denial terminates the Request and cancels unfinished Approvals; unavailable or incomplete decisions remain pending.

Before final approval, ATT validates the relevant captured position revisions and authority path.

A relevant path change makes the Request `STALE` and creates a successor under the saved policy; unrelated topology changes do not invalidate it.

All required Approvals and creation of the resulting Agreement commit through the same authoritative transaction.

Existing Agreements survive policy and topology changes until an endpoint explicitly revokes them.

See [Autonomous Communication Governance](flowcharts/Autonomous_Communication_Governance.md) for the complete routing and persistence flow.

## 4. Migration & Reorganization Policies

The organization is an explicit forest: an AgentTeam has no parent, an Agent parent, or an AgentTeam parent.

Creator provenance and team membership never infer organizational parenthood.

`request_migration(target_parent, rationale)` returns an immediate durable operation reference instead of synchronously awaiting the target's model work.

### A. Permissive Policy (`"permissive"`)

Ordinary path approval is unnecessary, but a prospective parent must still explicitly accept attachment.

Permissive migration is not permission to attach to an unwilling parent.

### B. Ancestor Approval Policy (`"ancestor_approval"`)

The actual current parent, target parent, and existing common ancestor decide, with duplicates removed.

No virtual common ancestor is manufactured between independent trees.

### C. Lineage Path Policy (`"lineage_path"`)

Every required explicit authority along the affected path decides through its exact governance case.

An AgentTeam acts through complete personal-email ballots, while an Agent parent acts through that person's own choice.

Final application revalidates availability, cycles, parent acceptance, captured positions, and cooldown under the topology lock.

The serialized admission also rechecks live Host migration and unilateral-detachment switches immediately before accepting the transition, without replacing the request's captured migration institution.

Successful changes to a team's own position start the confirmed 600-second cooldown.

The transition timestamp and cooldown bind together after runtime admission, record queues, JSON preparation, and graph validation have completed.

Durable mode binds that time inside the SQLite transaction immediately before writing its receipt, so waiting for or preparing the database write does not consume the interval.

The coordinator samples the registered clock on its owning event loop and passes immutable time readings to the writer; SQL workers do not inspect live Agents, teams, or formation candidates.

The accepted position event, cooldown, migration projection, and receipt digest use the same canonical time, while remaining-duration accounting retains its monotonic anchor even if observation of the committed result is delayed.

`migration_cooldown_downtime` controls whether offline elapsed time counts, defaulting to `"include"`.

Denied requests, failed commits, inherited subtree movement, and forced parent loss do not charge that cooldown.

`allow_unilateral_detachment=True` permits voluntary detachment independently of ordinary migration enablement.

Retiring an Agent parent or dissolving a parent AT detaches surviving direct children without deleting those children or altering their members' identities.

Topology changes publish one retained event and addressed notices only after their exact receipt.

## 5. Token Budget & Failover Policies

Configured token limits constrain the shared atomic model ledger.

Each provider attempt reserves estimated prompt messages, system instructions, transmitted tool definitions and JSON Schema, and maximum output tokens before dispatch.

The estimate covers ATT's actual request components without promising exact provider billing equivalence.

Settlement uses reported usage when available, refunds unused reservation, and conservatively accounts for sent failures or cancellation.

A token limit of zero disables that alias.

### A. Failover Routing Strategies

- `"auto"` selects a compatible explicitly bound alias with currently available quota.
- `"parent"` requests a choice from the actual organizational parent.
- `"none"` performs no model failover.

Parent failover is a separate durable resource attempt with a total `parent_failover_timeout_seconds=120` deadline.

An AgentTeam parent requires a valid eligible-alias ballot from every frozen member and a strict majority for one alias.

An Agent parent uses its own personal inbox and activity, never an implicit representative.

The request returns `PENDING` while choices are outstanding and does not hold the initiating Agent's model lock waiting for parent work.

Timeout, shared-Agent conflicts, missing majority, invalid aliases, changed topology, stale model bindings, or unavailable quota fail closed without falling back to auto.

Restore expires interrupted attempts instead of replaying them.

An expired execution authority does not delete mail, accepted choices, or personal memory.

## 6. Code Configuration Example

Communication policy is configured in ATTConfig and cannot be overridden by tools.

```python
from ai_team_team import ATTConfig, ParentApprovalCommunicationConfig

config = ATTConfig(
    communication=ParentApprovalCommunicationConfig(
        request_delivery="queue",
        direction="bidirectional",
    ),
    migration_policy="lineage_path",
    allow_unilateral_detachment=True,
    failover_policy="parent",
    parent_failover_timeout_seconds=120,
    model_token_limits={"reasoning": 50_000},
    model_max_output_tokens={"reasoning": 2_048},
)
```

An explicitly supplied `parent=` creates an organizational attachment; omitting it creates an independent team.

Trusted Host bootstrap is distinct from normal consent-bearing formation.

## 7. Health Attention and Escalation

Health assessment is event-driven rather than automatically run after ordinary output.

Typed detector thresholds request inspection, not permission changes, forced model replacement, or termination.

Confirmed permission-execution or integrity faults require immediate deterministic protection and a durable incident without waiting for an LLM audit.

Incidents use stable persisted fingerprints, occurrence counts, and first/latest timestamps, with no TTL or hard drop limit.

`"queue"` delivers addressed attention without forcing activation, while `"wake"` may request ordinary personal activity without changing the recipient's intent or team scope.

Explicit incident claims distinguish handling from mail reading; acknowledgement requires the current occurrence generation.

Failure, cancellation, or interrupted recovery releases claims to pending attention rather than deleting evidence.

Root or whole-ATT incidents propagate through `on_system_event`, not a fabricated parent or direct print.

See [Supervisory Team](Supervisory_Team.md) for fresh temporary audit teams, evidence boundaries, deadlines, and aggregate findings.
