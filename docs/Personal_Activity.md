# Continuing Personal Activity

ATT allows each Agent to act independently and continue its work across team memberships while preserving its identity and personal state.

This document explains how ATT schedules personal activity and manages invocation scope, checkpoints, sleep, notifications, resource availability, and recovery.

Joining or leaving an AT changes membership relationships while the Agent retains its Working Context, personal inbox, Private DocLib, and serial model invocation mechanism.

The Autonomous Agent Runtime schedules that person's work; Governance, Team Formation, communication, migration, resource decisions, and supervision retain their own authority and durable protocols.

## Admission, Answers, and Checkpoints

| Observation | What it establishes |
| --- | --- |
| `ActivityAdmission(status="QUEUED")` | Personal activity was accepted for scheduling, with an admission ID and explicit durability mode. |
| `ActivityAdmission(status="COALESCED")` | The same person's existing activity receives the input without a concurrent model-driven copy or scope replacement. |
| `InteractionResult` | That person returned an answer with actual Agent, team, and invocation provenance. |
| `ActivityCheckpoint` | The admitted activity committed a personal context boundary with an intent of `continuing`, `idle`, or `sleep`. |
| `SourceDeliveryReceipt` | A deliberately published source and its delivery references were committed. |
| `BackgroundTaskHandle` | An owned execution was admitted; it does not establish execution completion. |

An ordinary answer does not publish a message, cast a ballot, certify business completion, or choose idle.

Technical model-request and tool-batch budgets provide fair scheduling boundaries rather than discussion rounds or whole-team completion barriers.

The Agent continues until it explicitly chooses idle or finite sleep, or a distinct resource, lifecycle, shutdown, or integrity boundary intervenes.

See the [complete offline Quickstart](user/Quickstart.md#a-complete-offline-example) for a runnable admission, explicit idle, persistence, and restoration sequence.

For an already configured manager, the Host can admit a person without waiting for an answer:

```python
from ai_team_team.core.activity.contracts import PersonalScope

admission = await manager.activate_agent(person.agent_id, scope=PersonalScope())
checkpoint = await manager.wait_for_activity_checkpoint(admission.admission_id, intent="idle")
```

This waits for the Agent's actual idle choice; it is not a Host command to force that choice.

`execute_agent_interaction(person, prompt, team=None)` instead delivers a personal instruction and observes an answer from the same activity.

Cancelling an answer or checkpoint observer does not cancel the person, undo an accepted operation, or acknowledge an unread source.

## Work, Conversation, and Completion

An Agent is the continuing owner of personal state, while an AgentTeam supplies organizational relationships and authority.

A conversation identifies an exchange or subject, and a background task identifies one registered execution; neither defines the complete business objective.

`WorkItem` is a conceptual distinction for the outcome or activity the Agents describe, not a required runtime object, database table, or measurable-result contract.

Agents may maintain their own plans, criteria, reviews, and completion judgments in personal or team DocLibs.

ATT does not require business work to have a requester, external verifier, mandatory progress field, or deadline; participants choose those arrangements when useful.

One piece of work may involve several conversations and executions, and one team may pursue several pieces of work.

Personal work remains personally owned, and a message or conversation does not need a WorkItem association.

Agents may exchange or record votes about whether they consider work complete, but ATT supplies no general completion-vote API, fixed electorate, threshold, requester-acceptance gate, or automatic binding effect for those judgments.

Any work-specific procedure is chosen by the participants and does not replace membership consent, institutional ballots, live permissions, or other framework authority.

Choosing not to speak can coexist with reading, tools, writing artifacts, or other activity; it does not choose idle, leave the team, retire the Agent, cancel owned tasks, or close the conversation for other members.

An ended invocation, empty queue, read receipt, acknowledged notification, or stopped utterance does not certify a business outcome.

Migration and conversation interruption do not themselves complete, delete, or replace work artifacts; ordinary file authority and explicit lifecycle policies still apply.

## Scope and Tool Availability

Every invocation captures personal scope or one authorized AgentTeam scope.

An unfinished Native batch retains that scope for all required calls and observations.

| Scope | Available authority |
| --- | --- |
| Personal | Own private artifacts, personal mail and direct chat, authorized historical conversation reads, discovery, permitted formation operations, and registered tools whose scope permits them. |
| AgentTeam | The same person plus the current team's live membership authority for deliberate team publication, peer communication, governance, and team DocLib operations. |
| Restricted audit | Only the exact admitted evidence, scoped audit conversation, structured findings, and explicit idle controls supplied by the temporary assessment profile. |

Configuration, current depth, live membership, and optional features further filter the tool view on each request.

Membership voting and episodic-memory tools appear only when their corresponding features are enabled.

An Agent requests a subsequent scope explicitly:

```text
Action: set_operation_scope(scope={"kind": "agent_team", "team_id": "AT-example"})
```

The result is `PENDING_BOUNDARY`, and the new scope takes effect only after the complete current batch and its checkpoint.

The Host cannot replace an already active person's scope by submitting another admission or interaction with a different requested scope.

If a former team scope ends, the next valid personal invocation grants no posting, voting, or file authority from that membership.

## Explicit Idle, Sleep, and Reminders

Idle is an explicit personal choice:

```text
Action: set_activity_intent(intent={"kind": "idle"})
```

Sleep always has a finite safeguard, even when early wake conditions are supplied:

```text
Action: set_activity_intent(intent={"kind": "sleep", "countdown": {"hours": 1}, "early_conditions": [{"kind": "message", "source_kind": "agent", "source_id": "person-id"}]})
```

Supplied day, hour, and minute components must be positive integers; omit unused units rather than supplying zero or null.

The Host's default total bounds are five minutes through two days.

Early conditions may refer to an authorized team source, a registered Agent, or an execution owned by the sleeping person.

An ordinary reminder wakes sleep early only when it matches an admitted condition and is otherwise eligible for presentation.

Protected membership, position, permission, health, and interruption notices bypass personal suppression.

Scheduling policy still applies: a queue-mode health notice does not itself activate an idle or sleeping person, while a wake-mode protected notice may end sleep without an ordinary early condition.

Permanent or timed do-not-disturb preferences suppress ordinary reminders rather than source delivery or deliberate inspection:

```text
Action: set_notification_suppression(preference={"scope": "all", "countdown": {"minutes": 30}})
```

Omit `countdown` for a permanent preference, or select `scope="agent"` or `scope="agent_team"` with its `source_id`.

These preferences belong to the Agent across memberships and grant no access to the selected source.

Removing or expiring a preference summarizes eligible unread sources and counts without titles, previews, bodies, read changes, or replaying every individual reminder.

Another active preference still filters those summaries.

The Host equivalents accept an explicit `actor`; model tools never accept another Agent's identity.

## Resource Availability Is Separate from Intent

`ActivityView.intent` describes personal continuation, idle, or sleep, while `availability` describes such runtime facts as `waiting_model`, `waiting_tool`, or `unavailable`.

A provider failure does not mean the Agent chose idle or became unhealthy.

Per-request timeouts, the whole retry-sequence budget, provider earliest-retry instructions, and atomic model quotas constrain model admission independently.

Hard quotas reserve estimated input, system instructions, full tool definitions, and maximum output before dispatch, then settle reported or estimated usage.

Accounting estimates can differ from a provider's tokenizer; concurrent requests still share one atomic ledger and cannot reserve the same remaining capacity twice.

The finite sleep deadline remains effective while a provider is unavailable, but ending sleep does not bypass its retry boundary or Host-remediation requirement.

Parent-governed model selection remains a separate bounded resource decision under the actual designated Agent or AgentTeam parent.

## Recovery, Lifecycle, and Memory

Durable sessions require an explicit database path; intentionally volatile receipts carry no restart guarantee.

Restoration validates detached state and managed files, commits required recovery facts, publishes the new runtime, and only then schedules eligible people and timers.

Saved sleep and timed-suppression remainders resume from restoration start without consuming offline time.

An admitted timer handoff excludes restore through its local lock waits and receipt settlement, while dormant timers wait for publication or rollback.

Affected active owners receive interruption evidence through their own activity; old external tasks are not replayed, polled, or reconnected automatically.

Unchanged persistent UUIDs identify the same people after restore, although Python Agent and configuration objects are reconstructed.

The Host must reacquire current objects, using `manager.root_ai` or its active Agent index and saved IDs, before further operations.

Host-confirmed Agent death is terminal, retains personal history and private artifacts, closes current relationships, and settles outstanding personal observers even if no worker started.

`reactivate_agent()` applies only to retained or archived identities.

Advanced episodic memory remains optional and disabled by default; personal activity and voting do not depend on indexing.

See [API Reference](user/API_Reference.md), [State Persistence](State_Persistence.md), [Team Governance](Team_Governance.md), and [Selective Episodic Memory](Selective_Episodic_Memory.md) for the corresponding contracts.

The [personal activity flowchart](flowcharts/Personal_Activity.md) summarizes admission, intent, and resource boundaries.
