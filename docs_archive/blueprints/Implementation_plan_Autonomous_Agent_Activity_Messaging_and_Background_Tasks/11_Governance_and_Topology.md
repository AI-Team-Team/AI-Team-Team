# 11. Round-Free Governance, Formation, Migration, and Failover

[Back to plan index](README.md).

## 11.1 Governance cases

Rename the ballot solicitation model to a proposed `GovernanceCase`, with a stable case ID and explicit electorate or proposal revision rather than `round_number`.

Retain principal, business request, strict choice schema, frozen voter IDs, accepted immutable ballots, status, timestamps, and relevant source references.

A team decision remains attributable to `agent_team`, while each ballot remains attributable to its actual Agent voter.

Root decisions remain attributable to `agent` using Root's immutable Agent ID.

Mail opening, read receipts, notification presentation, ordinary answers, and shared messages are not ballots.

Every voter receives an addressed notice explaining that an explicit tool choice is available and that the voter may leave the matter unanswered.

No separate ballot worker directly invokes a person while another activity owns its personal slot.

Strict JSON literal booleans and eligible model aliases remain the only valid submissions for their respective case schemas.

When an institution requires all frozen members to submit valid ballots, missing, invalid, or unanswered ballots keep authority pending.

For existing AgentTeam boolean approvals, complete valid participation is followed by a strict majority of literal true or false votes, with a tie producing no authority.

Parent model selection likewise requires a strict majority for one legal alias after complete valid participation, with no replacement selected from a tie or partial electorate.

Every principal required after applying the independent-endpoint exemption must approve, and a valid principal denial terminates the request and cancels its unfinished approvals under the existing contract.

Record an independent side as exempt rather than inventing an approved ballot, and do not remove principals required by a non-independent side merely because the other endpoint is independent.

An accepted ballot survives a later ordinary tool failure because committed public choice is an authoritative fact, while a missing ballot is never supplied by interpreting incomplete output.

Electorate changes invalidate the old solicitation and require a new explicitly identified case version without reusing votes for a changed electorate.

Retain communication policy snapshots, stale requests and successors, active Agreement uniqueness, and endpoint-only revocation, and include endpoint independence and its relevant explicit parent relations in route validation.

## 11.2 Voluntary approval mail and deferred wake

Communication approval requests are delivered as personal mail to the AI voters selected by the remaining required principals after applying endpoint independence.

For an AgentTeam principal, these are its eligible members' explicit ballots and the final authority remains the AgentTeam rather than an implicit representative.

For an Agent principal, the addressed Agent acts through its own serial personal runtime without a replacement voter.

`request_delivery='queue'` is the default and means the recipient may choose when, or whether, to process the request.

Do not require a later normal discussion or independently initiated team-scoped activity before delivering the approval mail.

Notification admission follows ordinary personal-mail, sleep, and do-not-disturb rules and does not force a ballot or create a parallel model invocation.

The future `wake` direction requests immediate approval handling rather than voluntary scheduling, but its meaning and safeguards require further design.

Do not implement or advertise communication `wake` in this update, and do not silently map an unsupported `wake` setting to queue.

The deferral applies to communication-approval handling, not to existing protected system notices, sleep timers, or independently configured health escalation.

An unread, read, presented, or unanswered request supplies no authority, and every non-exempt required principal must still produce the valid decisions required by Section 11.1.

## 11.3 Consent and formation

Preserve accepted, declined, explicitly ignored, and no-response invitation attitudes independently of mail read state.

Explicit `None` remains a choice not to disclose a public attitude and remains externally indistinguishable from an unanswered invitation.

Material proposal revisions require renewed exact-revision consent, while no-op revisions do not fabricate new consent.

Accepted-subset creation, minimum team size, initiator final confirmation, abandonment notices, and explicit late joining retain their existing rules.

Trusted bootstrap remains host-only and cannot be reached through model tools.

Apply successful creation and membership intervals in one authoritative topology transaction, then admit any requested initial activity through committed message or notification references.

A subsequent ordinary activity failure does not roll back an already created team or become a fabricated task-completed result.

`dispatch_subagent()` returns creation or consent-request references rather than synchronously waiting for the child team to finish business work.

No synchronous delegation waits for an initiating or shared Agent to re-enter its own invocation.

## 11.4 Autonomous proposal design and feedback

An initiating AI designs a proposed AgentTeam and sends invitations through the existing consent-bearing formation tools.

Invited Agents receive personal mail and may explicitly accept, decline, ignore, or withhold a public attitude using `None`.

Invitees, intended participants, and other interested Agents may voluntarily communicate feedback through channels and resources they are authorized to use.

This voluntary feedback does not grant access to private proposals, make somebody a member, or substitute for an invitation response.

The initiator may inspect attitude counts and feedback, then revise the current proposal or publish a separate new proposal through strict validated tools.

Material revisions retain exact-version consent requirements, while ordinary advice and no-op revisions do not fabricate consent.

Remove the mandatory `required_when_team_scoped` draft prerequisite instead of replacing it with another required advisory process or all-member response barrier.

Optional collaboration and candidate-validation helpers may remain, but synthesis belongs to the same initiator's serial activity and ready drafts are not membership authority.

## 11.5 Migration

Preserve permissive, ancestor-approval, and lineage-path institutions with explicit existing principal types.

Apply the confirmed independent-side exemption to requirements for the moving independent team's own parent or ancestors without exempting another non-independent affected side, and require explicit acceptance from the prospective parent for reattachment.

Prepare approval requests without waiting inside an issuing Agent's tool invocation for other personal activity to finish.

After all required authority exists, revalidate topology, original parent, target parent, cycle conditions, the captured migration institution's approval path, and applicable live constraints before one atomic migration commit.

Invalidate descendant depth caches and issue deduplicated affected-position or permission notices without changing members' owned fields.

Remove reset-on-discussion migration counters rather than retain a synthetic session just to reset them.

A migration request executes at most once, and normal parent-to-parent migration can retain its separate explicit enable/disable policy.

Voluntary unilateral detachment has its own confirmed Host-controlled permission, enabled by default, rather than silently inheriting an old-parent approval requirement from a migration institution.

The confirmed replacement is a ten-minute cooldown between successful migrations initiated for the same AgentTeam.

Check and record the successful migration boundary atomically at commit time, so concurrent requests cannot both consume the same interval.

Failed or denied requests do not consume the interval, and prior approval does not bypass live cooldown validation.

Movement inherited from an ancestor does not count as the descendant's own migration and does not reset its cooldown.

Persist the cooldown evidence across restart and use the confirmed default of counting real offline elapsed time, with host-configurable downtime exclusion as described in Section 5.5.

## 11.6 Parent failover

Convert parent model choice into a bounded resource-decision case that collects explicit eligible ballots through the common personal runtime.

Keep the existing 120-second parent-failover timeout and fail-closed behavior, with no fallback to auto.

Do not retain the failing person's invocation lock while awaiting activity that would require that same person to vote.

The issuing invocation yields a pending resource attempt or ends with a structured availability result rather than synchronously nest parent discussions.

Retain self-parent and shared-electorate fail-closed protections without replacing an unavailable required voter, excluding that voter to invent a majority, or inferring its choice from another person's response.

The resource attempt has its own lifetime and deadline, so returning a pending handle or ending the issuing invocation does not immediately expire its case.

Expire the case when that resource attempt is explicitly cancelled, superseded, resolved, or reaches its deadline, reject late ballots, and do not replay it after restoration.

Apply any authorized model change through that person's coordinated state transition, with live alias and atomic budget revalidation.

Automatic failover remains an independently configured resource policy rather than borrowing another person's approval or silently substituting a representative.

## 11.7 Independent AgentTeams and explicit organizational parents

An AgentTeam may remain active without an organizational parent and may later attach beneath an explicitly identified Agent or AgentTeam.

Keep immutable creation provenance, active membership, and the current organizational-parent relation separate rather than equate a creator with a permanent parent.

Represent the optional parent explicitly using the existing `agent` or `agent_team` principal kinds, with no parent distinct from an explicit Root Agent parent.

Do not select an Agent's first membership as its organizational ancestry or select a replacement parent merely because its creator retires or dies.

When an actual Agent parent dies or retires, or an actual parent AgentTeam dissolves, detach its surviving direct child AgentTeams into explicit independence as part of the topology transition.

Keep descendants attached to their surviving immediate parents, and do not flatten the whole branch, dissolve surviving teams, substitute Root, or rewrite members' personal state.

A team whose only change was forced detachment from a disappearing parent is not initiating its own migration, so the existing own-migration distinction must be preserved.

Independent teams retain their own identities, chat, documents, and memberships when they later choose to attach beneath another Agent or AgentTeam.

Reattachment requires explicit acceptance from the prospective parent even though the attaching independent team has no own-parent or ancestor approvals to obtain.

Address an Agent parent through that Agent's own strict personal decision and an AgentTeam parent through the confirmed collective-governance mechanism, with no representative substitution.

Until the target accepts, retain the current topology and keep the request pending or denied according to its factual decision state.

Acceptance binds the exact attaching team and proposed parent, and commit must revalidate that both remain eligible and the resulting topology is cycle-free.

Friendship, a communication Agreement, unrelated membership consent, creator provenance, or silence is not acceptance of an organizational child.

An attached AT may voluntarily become independent without approval from its current parent or ancestors by default.

Expose a strict Host-controlled unilateral-detachment permission with a confirmed default of `True`, with the candidate field name `allow_unilateral_detachment` subject only to interface review.

When that permission is `False`, the unilateral operation is unavailable and must not silently execute through another permissive path.

This setting governs voluntary unilateral departure, not forced detachment caused by the actual parent's retirement, death, or dissolution.

Enabling unilateral departure intentionally lets the AT change its effective communication institution by choosing independence, without treating that authorized organizational choice as a policy violation.

The voluntary operation still validates current acting authority, original parent, the ten-minute own-position cooldown, cycle and state integrity, and atomic topology publication.

A parent change is a topology transaction and must preserve cycle protection, authority revalidation, relevant route fingerprints, and the confirmed cooldown for the team's own position changes.

Independent AgentTeams are exempt from policies requiring their own parents or ancestors to approve, including `parent_approval`, `lineage_approval`, and analogous ancestor authorization requirements.

This is a confirmed institutional exemption, not an error fallback for corrupt topology, an approval inferred from silence, or a literal rewrite of the Host's global configuration.

| Endpoint relationship | Effective communication behavior |
| --- | --- |
| Independent to independent | Permissive in either direction, with no required Request or Agreement. |
| Independent to non-independent under global permissive | Direct delivery after ordinary identity and invocation-scope validation. |
| Independent to non-independent under parent or lineage approval | Exempt the independent side and retain the non-independent side's configured approvals and applicable channel requirement. |
| Non-independent to non-independent | Preserve the configured approval institution for both sides. |

Evaluate the same side-based rule regardless of which endpoint initiates the operation rather than treating an independent sender as permission to bypass the recipient's institution.

An attached child of an independent team is not itself independent merely because its branch root is independent.

An independent AgentTeam can still be an explicitly required approval principal for its attached child, because its own endpoint exemption does not erase the child's required parent authority.

For parent approval, collect the explicit parent principals of non-independent endpoints and deduplicate them without adding a Root for an exempt side.

For a mixed independent and non-independent lineage case, preserve the non-independent side's applicable real lineage requirements without adding a common Root absent from the topology or demanding ballots from the exempt endpoint on its own behalf.

When two non-independent endpoints belong to different independent organizational trees, collect the required principals along each endpoint's actual lineage through its own independent top-level AgentTeam.

Include those real top-level teams when they are approval authorities for their attached descendants, deduplicate shared principal identities, and do not add a virtual connection or common Root voter.

Preserve the existing rule that the initiating AT's action expresses its own consent and the recipient AT remains a required principal under lineage approval when it is non-independent.

For example, if independent `P` directly parents `A` and independent `Q` directly parents `B`, an `A`-to-`B` lineage request requires `P`, `Q`, and `B`, while `A` has already consented by initiating it.

Within one connected organizational tree, retain the configured real-path algorithm rather than unnecessarily require unrelated ancestors above its applicable path.

Commit-time topology validation must reconsider independence, stale affected requests when their relevant parent relation changes, and never reuse approvals for a changed required-principal set.

Existing active Agreements retain their confirmed lifetime and are not automatically revoked merely because an endpoint becomes independent or reattaches.

The exemption does not bypass identity checks, current member authority, membership consent, current DocLib ACLs, quotas, cycle checks, or the confirmed own-migration cooldown.

The exemption does not supply a parent resource provider or select a failover model when no such provider exists.

Target acceptance, default-enabled configurable unilateral detachment, and cross-tree real-lineage approval are confirmed contracts rather than unresolved institutional choices.
