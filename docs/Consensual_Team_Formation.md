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

The unread Agent inbox is included in that Agent's next model context together with tools for listing and acknowledging messages. Framework-only runtime auditors are not registered identities and do not receive fabricated Agent inboxes.

Host APIs may address an Agent ID directly for administration:

```python
messages = manager.list_agent_inbox(agent_id, unread_only=True)
await manager.mark_agent_inbox_read(agent_id, message_ids=None)
```

Agent-facing tools never accept an acting Agent ID. They derive the identity from the current invocation context:

- `list_agent_inbox(unread_only=True)`
- `mark_agent_inbox_read(message_ids=None)`
- `inspect_team_formation(request_id)`
- `discuss_team_formation_proposal(objective, request_id=None)`
- `inspect_team_formation_draft(draft_id)`
- `retry_team_formation_draft(draft_id)`
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

## Collaborative Proposal Deliberation

An initiating Agent may ask its invocation-scoped current AgentTeam to shape an initial proposal or a possible next revision. The work is advisory: it runs later as a detached job under the creator AgentTeam's normal serial discussion lock, freezes the participating members, does not consume unrelated inbox work, and never accepts an invitation for another Agent.

The initiating Agent synthesizes a strict complete `TeamFormationDraftCandidate` after the discussion. Failed, incomplete, cancelled, invalid, or membership-changing deliberation produces no publishable proposal revision. A ready draft remains inert until that same Agent explicitly publishes it, and revision publication fails closed when its immutable base revision has become stale.

`ATTConfig.formation_deliberation_policy` defaults to `"optional"`. Setting it to `"required_when_team_scoped"` requires this draft workflow before a team-scoped initial proposal or revision is published; a standalone Root Agent may still formulate a proposal directly.

```python
draft = await manager.discuss_team_formation_proposal(
    actor=initiator,
    objective="Design an incident investigation team.",
)
```

After the initiating Agent receives the `team_formation_draft_completed` notification in its personal inbox, it can inspect the detached result and explicitly publish only a ready candidate:

```python
ready = manager.get_team_formation_draft(draft.draft_id, actor=initiator)
if ready.status.value == "ready":
    published = await manager.publish_team_formation_draft(
        ready.draft_id,
        actor=initiator,
    )
```

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

An initiator may explicitly join its proposed AgentTeam. ATT commits formation without synchronously running the first discussion inside the formation tool call, so the call returns and releases the initiating Agent's invocation lock before the new team needs that Agent.

If the proposal includes an initial task, ATT schedules that discussion after creation and later delivers a completion or privacy-safe failure notification to the initiator's Agent inbox. The manager-wide wait-for graph remains the final guard for any other synchronously awaited Agent dependency.

## Atomicity and Persistence

Revision, response, explicit creation, automatic creation, abandonment, and late joining are serialized per request. Draft jobs have independent locks, and publication acquires the relevant request lock before it can change consent-bearing state. At most one concurrent path can create the AgentTeam or commit a particular revision.

Creation stages new Agents, Private DocLibs, the Team DocLib, and initial files outside the live registries. It revalidates under the creation locks, publishes topology and files as one operation, commits the authoritative state before returning `CREATED`, and restores runtime, inbox, formation, and filesystem state if persistence fails.

Persistence schema 9 stores Agent inbox messages, current formation projections, immutable revision snapshots, append-only invitation decisions, detached drafts, timestamps, completion policy, late-join policy, and the resulting team reference. Restore validates complete contiguous revision history, exact fingerprints and material fields, creator provenance, decision-to-revision membership, draft publication provenance, and every related identity reference in detached staging; malformed data raises `StateRestoreError` without changing the current manager or its Agent inboxes and DocLibs.
