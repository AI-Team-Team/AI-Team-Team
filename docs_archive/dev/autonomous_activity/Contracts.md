# Frozen Engineering Contracts

## Authority and Value Records

The confirmed institutions govern these contracts, and later implementation must not infer additional consent, representatives, work-completion rules, or sharing rights.

Records in `core.activity.contracts` use strict Pydantic validation, reject unknown fields, and are immutable with immutable nested collections.

IDs are nonblank opaque references, while registration, ownership, canonical Agent UUIDs, and live eligibility are independently verified by the authoritative service.

Validating a record does not authorize its producer or prove that its referenced objects exist.

Model tools resolve the current person from invocation context and never accept an actor, sender, approver, runtime generation, or producer-classification override.

Durable operation receipts are returned only after the exact accepted domain transaction succeeds.

Explicit volatile mode preserves identity and authorization but reports `durability='volatile'` rather than promise restart safety.

Durable mode requires a configured database and never creates an unexpected database or silently falls back to volatile mode.

## One Captured Scope

`OperationScope` is the discriminated union of `PersonalScope(kind='personal')` and `AgentTeamScope(kind='agent_team', team_id=...)`.

`InvocationScope` binds the actual registered Agent, invocation, positive runtime generation, and one operation scope.

An AI requests a scope change through `set_operation_scope(scope=...)`, with membership revalidated when the change is admitted and at protected resource access.

The change applies after the current complete tool batch and authoritative commit boundary, not retroactively to a submitted model request or an admitted execution.

A Native batch retains its captured scope for every call even if a sibling requests another scope.

Several conversation summaries do not confer their combined authority.

Repeated activation of a busy person coalesces admission and cannot silently switch that person's captured scope or start a second model invocation.

Historical-chat queries use personal entitlement without restoring current membership or file permissions.

## Activity Intent and Fair Yields

After admission, activity continues by default without a required continuing declaration.

Only `set_activity_intent(intent={'kind': 'idle'})` or a validated sleep choice deliberately stops model-driven continuation.

Registration or construction alone does not issue an external model request before host bindings and authoritative admission are ready.

Ordinary model answers remain personal and do not publish messages, declare idle, certify work completion, or close a shared stream.

Per-invocation request and tool-batch budgets cause a checkpoint and fair yield, not a stop requiring another message to restart continuing activity.

One ready entry per owner and bounded global model admission provide fairness without a team barrier or an always-running coroutine per membership.

One Native batch may contain at most one activity-intent change and one scope-change request, and contradictory duplicates are invalid arguments before control effects execute.

Self-control operations are serial and never detachable.

An explicit stop applies only after issued calls have complete results or valid task-handle observations and accepted transactions have known outcomes.

## Sleep and Suppression

`SleepIntent` requires a finite countdown and may contain message-source or owned-execution early conditions, any of which may wake the same person.

Countdowns accept positive integer days, hours, and minutes and use the Host's bounds, defaulting to five minutes through two days on their combined total.

The admitting service validates referenced sources, execution ownership, and live configured bounds rather than accept model-supplied bounds.

An explicitly supplied null duration unit is invalid, while omitted units are represented internally as absent.

Duration wire serialization omits absent units.

Permanent ordinary suppression has no countdown, while timed suppression uses the same duration bounds as sleep.

Suppression scopes are all ordinary notices, a selected Agent, or a selected AgentTeam and never suppress protected notices or sleep's finite safeguard.

Ending suppression presents an authorized source-and-count summary without previews, titles, bodies, fabricated read receipts, or replay of every suppressed reminder.

Sleep and timed suppression persist remaining countdowns and exclude offline time, with restoration start as their anchor.

Migration and tool cooldowns instead count real downtime by default unless Host configuration explicitly selects exclusion.

## Source, Notice, Frame, and Presentation

A `NotificationSource` points to a shared team message, direct message, personal mail, execution, or system event.

`NotificationReference` records the recipient, trusted classification, arrival generation, and stable deduplication key without a source body.

Only trusted membership, permission, health, and recovery transactions may generate protected classifications.

Generic host mail and model chat are ordinary even if their titles or payloads claim urgency.

`PresentationClaim` associates a source notice with one model request and frame as `reserved`, `dispatched`, `presented`, or `uncertain`.

Reservation and dispatch do not prove presentation, and presentation never marks mail read, supplies a ballot, acknowledges task attention, or accepts a friendship.

Fresh eligible information is sampled before each model request after any unfinished Native batch closes, including the request immediately following a foreground tool wait.

A notification already presented does not continually re-admit an owner who deliberately left it unread or unanswered.

Marking a source unread again does not create a fresh arrival generation.

An active-to-idle transition commits its checkpoint and compares arrival generation under the admission protection so an intervening event cannot be stranded.

## Host Entry Points

`ActivityRuntimeAPI` freezes the first shared-runtime signatures without making the current Manager implement them.

| Method | Contract |
| --- | --- |
| `register_runtime_clock(clock)` | Host-only runtime binding before activity or timers are admitted, never persisted or changed underneath live operations. |
| `await activate_agent(agent_id, *, scope=None)` | Admit or coalesce the same active registered person and return `ActivityAdmission`, with personal scope by default. |
| `inspect_agent_activity(agent_id)` | Read an internally consistent `ActivityView` including its captured scope, not a business-success judgment. |
| `await wait_for_activity_checkpoint(admission_id, *, intent=None)` | Observe a committed boundary, optionally a particular explicit intent, without waiting for team completion or forcing a stop. |
| `await deliver_agent_mail(agent_id, *, message_type, payload)` | Host ordinary addressed mail with source and notification committed before `SourceDeliveryReceipt`. |
| `list_team_messages(team_id, *, actor)` | Metadata and preview page filtered by the actor's live or frozen entitlement before counts, with no implicit read marking. |

The waiting API is observational, supports caller cancellation, and never changes the observed admission merely because its observer stops waiting.

Persisted notices remain the delivery authority when a process-local scheduling handle disappears.

The initial control-tool names are `set_activity_intent` and `set_operation_scope`, with actor identity exclusively from invocation context.

Background initiation is `start_background_task(tool_name=..., arguments=...)`, without arbitrary callables, executor selection, sender, or policy arguments.

## Effects, Resources, and Execution

`ToolExecutionContract` declares one or more reviewed effects, explicit `background_allowed`, required scope, mutation safety, cancellation capability, and supported health signals.

`required_scope='personal'` denotes the current person's own authority and remains valid inside an AT invocation, while `agent_team` requires its one captured current-team authority.

Neither value changes captured provenance or lets a personal operation borrow other teams' permissions.

Effects are `read_only`, `artifact_write`, `domain_mutation`, `self_modification`, or `undeclared`.

Any self-modifying or undeclared effect prohibits background execution regardless of retry safety.

Detachable mutations require managed mutation leases, actual isolation, or an explicitly trusted host responsibility, and the last option is not an ATT sandbox guarantee.

Built-in tools use managed leases for ATT mutations and resolve resource keys before dispatch, including both move paths and managed-link targets.

Resource keys are canonical physical library-and-path identities or declared external resource identities, not the spelling of an alias path.

Conflicting resource access is serialized across owners in deterministic key order, while independent resources may proceed concurrently.

The initial implementation deliberately does not add optimistic version checks or overwrite confirmation and therefore accepts semantic last-writer overwrite.

The [effect manifest](tool_effects.json) freezes built-in target declarations, including optional memory tools, for their replacement implementations rather than certify that their current implementations are safe to detach.

Externally registered tools may omit the whole execution contract only to remain foreground-only with undeclared effects, while any supplied contract requires an explicit boolean background declaration.

Retry safety remains the separate existing `Tool.retry_safe` property and cannot grant background permission.

Explicit and automatic background execution use the ordinary tool view, signature and schema validation, auditor, live authorization, and one durable admission before side effects.

Automatic detachment measures from actual executor start, includes retry and backoff elapsed time, excludes preflight and queueing, and uses the confirmed configurable 120-second default.

A detached Native call receives one `BackgroundTaskHandle` observation with its execution ID and durability, while later outcome delivery uses personal notification rather than another tool result for that call ID.

The executor cannot retain an owner's mutable window, unfinished tool batch, personal invocation guard, or an open caller transaction after detachment.

Managed mutation leases validate owner eligibility, captured scope, runtime generation, and live ACLs at protected access and publication, not only when reporting final success.

## Failures, Cooldowns, and Cancellation

Argument failures, unknown tools, missing files, permission denials, and business refusals are classified observations without stopping continuing activity or imposing a tool cooldown.

Confirmed execution faults and exhausted typed transient retries may start the confirmed ten-minute same-Agent/tool cooldown for new calls only.

A denied call during cooldown neither extends it nor cancels previously admitted healthy executions.

LLM request timeout, total retry budget, Full Jitter, provider waiting instructions, and recoverable re-admission use the confirmed D15 defaults independently from tool replay.

Authentication, programming, and configuration faults require Host remediation instead of periodic transient retries.

The five execution states, five health states, and three attention states stay independent, with interruption and uncertain outcome represented as separate evidence.

A cancellation request is not a cancellation acknowledgement, and a confirmed completion wins against an unacknowledged cancellation request.

Meaningful queued cancellation prevents dispatch, while a running executor requires its declared stop capability and must not be called cancelled just because a local wait ended.

Unstoppable or unconfirmed executors lose access to ATT-managed mutation paths and produce a Host risk report rather than a fabricated terminal state.

Shutdown and restore never time-limit accepted persistence writes, and they never wait forever for an uncooperative external model or executor.

## Confirmed Institutional Boundaries

Communication queue delivers voluntary personal ballots immediately without a discussion prerequisite, while communication wake remains deferred.

Independent sides are exempt only from their own parent or ancestor authority and do not erase an attached counterpart's requirements.

Voluntary detachment is Host-configurable and enabled by default, while reattachment requires the prospective parent's explicit acceptance.

Cross-tree lineage collects actual required principals up to each independent top without inventing Root ancestry.

Formation preserves all four attitudes, explicit `None`, exact-revision consent, voluntary feedback, and no mandatory advisory workflow.

Audits use fresh real restricted ATs, full valid structured participation and strict majority, with missing or tied conclusions as UNKNOWN and no business-completion or repair authority.

The same runtime and execution services support both ordinary and audit-scoped identities, with a trusted persistence profile determined by their registered lifecycle rather than selected by a model.

Audit-scoped requests, token claims, restricted conversation, and execution evidence reference retained audit snapshots rather than require ordinary persisted Agents, teams, memberships, or libraries.

Audit snapshots are forensic subjects rather than executable registrations, and restore never activates them or substitutes Root's identity for their actual caller.

Retained ordinary-Agent death is Host-only, preserves personal history and artifacts, protects Root, and detaches surviving children rather than deleting their organizations.

Chat departure snapshots, absence-period exclusions, recipient-owned reminder previews, read facts, personal hiding and restoration, and post-dissolution archives remain separate from membership and DocLib authority.

No topics, immediate approval wake, long-lived auditors, Git-backed library workflow, or WorkItem acceptance interface is introduced in Phase 0.
