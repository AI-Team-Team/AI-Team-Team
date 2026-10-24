# Consensual Existing-Agent Team Formation

ATT treats every registered `Agent` as one autonomous identity. Naming an existing `agent_id` in a team proposal does not authorize membership, so ordinary Agent and host APIs create a persistent formation request and require each invited Agent to choose whether to join.

The governing invariant is:

> Joining or leaving an AgentTeam changes only the `team_id ↔ agent_id` membership relationship. It never rebinds, replaces, or clears an Agent's identity, name, role, instructions, model binding, memory, lifecycle state, invocation lock, Private DocLib, Agent inbox, or memberships in other AgentTeams. Invitation and outcome notifications may be appended to the existing Agent inbox as an independent messaging operation.

## Formation Inputs

`member_configs` and `roles_and_presets` describe new Agent identities that will be created only if the AgentTeam commits. `existing_members` and `existing_member_ids` identify already registered Agents who must consent. `initiator_joins=True` is the initiating Agent's explicit consent to become a founding member; initiating a proposal alone does not add that Agent.

Calling `manager.create_agent_team(...)` with only new-Agent specifications still returns an `AgentTeam` immediately. Supplying an existing Agent or `initiator_joins=True` returns a `TeamFormationRequest` without creating an AgentTeam, new Agents, DocLibs, membership rows, or team directories.

The trusted host-only `manager.bootstrap_agent_team(...)` API is the explicit exception for provisioned topology initialization. It bypasses interactive consent, emits a `trusted_team_bootstrap` audit event, and is never registered as an Agent-callable tool.

## Agent Identity Inbox

Every registered Agent owns one persistent `agent_inbox` in addition to any AgentTeam inboxes. Formation invitations and results are delivered to the Agent identity because the same Agent may participate in several AgentTeams and no team should own that Agent's personal decision.

The unread Agent inbox is included in that Agent's next model context together with tools for listing and acknowledging messages.

Audit-scoped supervisory Agents are registered for the lifetime of their managed supervisory AgentTeam, but they do not receive ordinary business tools or invitations; their identities are removed after the audit while audit evidence remains durable.

Host APIs may address an Agent ID directly for administration:

```python
messages = manager.list_agent_inbox(agent_id, unread_only=True)
await manager.mark_agent_inbox_read(agent_id, message_ids=None)
```

Agent-facing tools never accept an acting Agent ID. They derive the identity from the current invocation context:

- `list_agent_inbox(unread_only=True)`
- `mark_agent_inbox_read(message_ids=None)`
- `inspect_team_formation(request_id)`
- `propose_team_formation(proposal, organizational_parent="none")`
- `prepare_team_formation_draft(objective, candidate, request_id=None, organizational_parent="none")`
- `inspect_team_formation_draft(draft_id)`
- `publish_team_formation_draft(draft_id)`
- `revise_team_formation(request_id, base_revision, changes)`
- `respond_team_invitation(request_id, proposal_revision, attitude=None)`
- `create_team_from_formation(request_id, proposal_revision)`
- `abandon_team_formation(request_id, proposal_revision, reason="")`
- `decide_team_formation_late_join(request_id, invitee_agent_id, proposal_revision, approved)`

## Invitation Attitudes

Each invitee has exactly one public attitude:

| Attitude | Meaning | Membership result |
| --- | --- | --- |
| `accepted` | The Agent explicitly agrees to join. | Eligible for founding or late membership. |
| `declined` | The Agent explicitly refuses. | Does not join. |
| `explicitly_ignored` | The Agent explicitly chooses not to engage. | Does not join. |
| `no_response` | The Agent has not published an attitude, either because the invitation is unprocessed or because the Agent deliberately chose `None`. | Does not join. |

The response tool explicitly offers `None` as the choice for withholding a public attitude. An Agent that chooses `None` and an Agent that has not processed the invitation are intentionally indistinguishable as `no_response`; declined, explicitly ignored, and no response have the same membership effect but retain different social meaning.

The initiator and invitees may inspect the proposal. The summary reports all four counts, the membership count that would actually commit, the live configured minimum, `can_create`, and an eligibility reason when creation is currently blocked.

## Proposal Revisions and Exact Consent

Every proposal starts at revision `1`. Each invitation response and every authorization-bearing operation names the exact revision reviewed by its caller. A stale response, creation, abandonment, or late-join decision returns `STALE_REVISION` and cannot affect the current request.

Only the original initiating Agent may revise an open proposal. A material change creates one immutable `TeamFormationRevision`, increments the revision exactly once, recomputes both the normalized content fingerprint and revision-bound fingerprint, resets all retained invitations to `no_response`, notifies retained and added invitees, and notifies removed invitees that their invitation ended. All fields that define the resulting AgentTeam are material; initiator and creator provenance cannot be revised.

A no-op revision returns `UNCHANGED` without a write, notification, revision increment, or consent reset. Decisions remain append-only history bound to the revision on which they were expressed, including an explicit `None` decision recorded as `no_response`.

Public request, invitation, revision, decision, and draft reads are detached from the authoritative registries. Mutating a returned object cannot mutate live governance state.

## Voluntary Design and Optional Candidates

The initiating Agent designs its proposal in its own continuing activity and may seek voluntary advice over authorized channels.

No compulsory creator-Team drafting process or all-member response barrier precedes publication.

Discovery supplies public records on demand, not consent or an automatically selected candidate.

`prepare_team_formation_draft` validates a complete initiator-supplied `TeamFormationDraftCandidate` without invoking any model or other person.

A candidate is immediately `READY`, remains inert until its initiator explicitly publishes it, and records only that initiator as its author.

Draft preparation, publication, and actual creation all validate the configured maximum depth against the intended parent's current position.

Explicit confirmation and automatic creation repeat that check after any consent wait, and the authoritative commit checks it again after any writer wait.

An over-depth proposal remains uncreated rather than bypassing the limit or losing its existing exact-revision consent.

Its provenance can include the initiator's actual invocation, never a detached synthesis job or fabricated discussion identifier.

For a new Host-prepared candidate, `parent=None` means independence even when the initiator currently belongs to a team.

Pass `parent=...` explicitly when preparing an initial Host candidate, or choose `organizational_parent="self"` or `"current_team"` in the tool.

A revision candidate retains its proposal's immutable explicit parent rather than choosing a new one.

```python
draft = await manager.prepare_team_formation_draft(
    actor=initiator,
    objective="Validate my investigation-team design.",
    candidate=candidate,
    parent=None,
)
published = await manager.publish_team_formation_draft(draft.draft_id, actor=initiator)
```

A changed exact base makes a revision candidate `STALE`; its retained candidate remains historical evidence but cannot authorize publication.

Candidate preparation, voluntary feedback, and mail read state never accept another person's invitation.

## Creation and Completion

Only accepted invitees are included. New-Agent specifications and an explicitly joining initiator also count toward `ATTConfig.min_subagent_team_size`.

The initiator may create early from an accepted subset as soon as the real founding membership satisfies every live creation rule. ATT revalidates Agent activity, creator authority, intended parent, uniqueness, model aliases, document inputs, team size, and registry conflicts before publishing the team.

The proposal chooses one unanimous-acceptance behavior:

- `auto_create` creates through the same validated commit path when every invitee accepts.
- `require_confirmation` enters `ready_for_confirmation` and lets the initiator create or abandon the proposal.

When a proposal has no external invitees, includes the initiator, selects `auto_create`, and already satisfies every live team-creation constraint, ATT schedules the same validated formation commit immediately because no invitation response exists to trigger it.

Abandonment is terminal and notifies every invitee. It creates no team entities or files.

## Late Joining

Founding membership is frozen when the AgentTeam is created. A later team departure is an independent membership operation and does not rewrite the old invitation or its `joined_at` audit history.

Non-founding invitees may join later only when the stored policy allows it and only after they explicitly accept:

- `disabled` rejects late joining.
- `open` adds the consenting Agent after live validation.
- `require_initiator_confirmation` records a pending late-join request, then requires the original initiator to approve it.

Late joining changes only the team membership relation. It does not copy, replace, or clear the Agent, memory, model, Private DocLib, Agent inbox, or other memberships; the workflow may append an outcome notification to the existing Agent inbox.

## Asynchronous Self-Membership

An initiator may explicitly join its proposed AgentTeam. ATT commits formation without synchronously nesting another invocation inside the formation tool call.

If the proposal includes initial instructions, ATT retains addressed mail and admits eligible personal activity after creation without waiting for child business work.

Creation references certify only creation, not business completion.

The manager-wide wait-for graph remains the final guard for other synchronous personal observation dependencies.

## Atomicity and Persistence

Revision, response, explicit creation, automatic creation, abandonment, and late joining are serialized per request. Candidate publication has an independent lock, and publication acquires the relevant request lock before it can change consent-bearing state. At most one concurrent path can create the AgentTeam or commit a particular revision.

Creation stages new Agents, Private DocLibs, the Team DocLib, and initial files outside the live registries. It revalidates under the creation locks, publishes topology and files as one operation, commits the authoritative state before returning `CREATED`, and restores runtime, inbox, formation, and filesystem state if persistence fails.

Final acceptance rechecks the initiator's current creating-team or intended-parent membership, active founding identities, minimum size, and live depth limit after admission waits.

Draft preparation, formal proposal publication, and revision publication also revalidate the live creator relationship at their acceptance boundary, including an unchanged candidate published without a new revision.

Asynchronous formation changes use operation-local candidate projections and publish only their changed entities after the exact receipt; unrelated proposals and independently accepted inbox arrivals remain intact.

Full saves and independent incremental commits capture accepted formation projections and exclude another operation's pending team, new identities, libraries, relationship facts, and mail.

Rollback withdraws only the exact identities, libraries, initial relationship facts, and newly appended mail owned by that operation; it never restores a manager-wide snapshot or overwrites another operation's accepted messages and read receipts.

Cancelling candidate publication before acceptance leaves the candidate ready and removes its unaccepted request and invitations, while an accepted receipt preserves the published proposal or created team and its automatic-creation or initial-work dispatch even if its observer loses the response.

The same receipt boundary applies to revisions, invitation responses, abandonment, and late joining, so pre-acceptance cancellation does not change the published revision, public attitude, or lifecycle state.

Persistence schema 15 stores Agent inbox messages, current formation projections, immutable revision snapshots, append-only invitation decisions, detached drafts, timestamps, completion policy, late-join policy, and the resulting team reference.

Restore validates complete contiguous revision history, exact fingerprints and material fields, creator provenance, decision-to-revision membership, draft publication provenance, and every related identity reference in detached staging; malformed data raises `StateRestoreError` without changing the current manager or its Agent inboxes and DocLibs.

Personal inbox delivery, opening, and read receipts remain independent of all four formation attitudes.

Marking an invitation read never changes its public attitude, and responding with `accepted`, `declined`, `explicitly_ignored`, or `None` never marks the email read.

Personal-email governance for communication, migration, and failover uses its own choice schemas rather than replacing or reinterpreting this formation vocabulary.
