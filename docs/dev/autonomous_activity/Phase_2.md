# Phase 2: Personal Activity Runtime and Model Boundaries

## Implemented Boundary

Phase 2 introduces a real continuing-person runtime through `ATTManager.activate_agent()`, not an outer loop around numbered AgentTeam discussions.

One Agent has one admitted personal activity, one bounded invocation at a time, one Working Context, and the same identity across every membership.

Registration alone is inert.

Addressed mail is accepted and committed before activity is scheduled, while ordinary personal interaction and governance email presentation use this common admission path.

The existing numbered institutional producers remain intermediate branch work until Phase 5 removes them.

They are not a selectable fallback for personal activity.

Schema remains `12`; this phase uses the record foundations installed in Phase 1 rather than introducing another schema version.

## Host API

```python
from ai_team_team import ATTConfig, ATTManager, Agent
from ai_team_team.core.activity.contracts import AgentTeamScope

person = Agent("Researcher", "Researcher", client)
config = ATTConfig(workspace_root="workspace")
async with ATTManager(person, config, db_path="att.sqlite") as manager:
    manager.register_llm_client("research-model", client)
    admission = await manager.activate_agent(person.agent_id)
    checkpoint = await manager.wait_for_activity_checkpoint(admission.admission_id)
    current = manager.inspect_agent_activity(person.agent_id)
    receipt = await manager.deliver_agent_mail(
        person.agent_id, message_type="instruction", payload={"note": "Inspect your inbox."}
    )
```

`ActivityAdmission.status` is `QUEUED` for a new admission and `COALESCED` for an already active person.

A second activation does not replace the current invocation's captured scope or create another copy of that person.

An initial team scope is explicitly supplied with `AgentTeamScope(team_id=...)` and requires current active membership.

Checkpoint waiting is observation, not business completion, conversation closure, mail reading, voting, or cancellation of the owner when the observer is cancelled.

`execute_agent_interaction()` now submits a personal instruction and observes a response or explicit stopping boundary through this service.

Tool-only responses, scope changes, and technical fairness checkpoints do not complete an answer observer.

An instruction not yet presented when the person chooses idle or sleep remains observable across the next admission, and a returned answer records its actual captured scope.

Restore or close explicitly releases observers whose personal response can no longer be delivered by that runtime generation.

Synchronous nested interactions reserve identity dependencies before accepting an instruction and reject self-dependencies and cycles of any length.

A worker waiting for another person's answer temporarily yields its scheduling slot and rejoins the same FIFO capacity gate before continuing, so an acyclic dependency can progress even with one activity slot.

Cancelling that observer releases its dependency reservation without cancelling the downstream person's admitted activity or waiting for the downstream provider.

Cancellation before source acceptance leaves no instruction or admission, while cancellation after its commit cannot discard local admission in the requested scope.

The cancelled observer does not cancel the admitted person's provider request, and coalescing preserves an existing activity's scope.

Its transitional `AgentTurnResult` return type remains until institutional API replacement in Phase 5, and returning an answer does not stop the person's activity.

`clear_agent_model_unavailability(agent_id)` is a Host-only acknowledgement after repairing a model or quota configuration.

It cannot change the person's model, reset spent quota, overlap a still-live local request, or bypass a provider recovery boundary.

## Scheduling and Controls

The runtime deduplicates its ready queue by owner admission and uses bounded invocations for fair continuation.

Technical budgets yield to other ready people without inferring voluntary idle or business completion.

Silence, ordinary answers, malformed tool arguments, missing files, business refusals, and ordinary execution failures remain personal observations rather than team-fatal events.

Two runtime-only tools let the current person make explicit choices:

- `set_activity_intent(intent={"kind": "idle"})` chooses idle.
- `set_activity_intent(intent={"kind": "sleep", "countdown": {"minutes": 5}})` chooses finite sleep.
- `set_operation_scope(scope={"kind": "personal"})` or an authorized `agent_team` scope requests the next invocation's scope.

These tools accept no owner override and are added only to the current personal runtime's tool view.

Every Native sibling retains the original captured scope, and duplicate controls are rejected before any control effect executes.

Controls apply only after all results in the batch are known and its provider-valid window has committed.

A rejected stop checkpoint withdraws its staged intent, sleep timer, and next scope without discarding the person's factual observations.

Inspection reports the committed intent, and cancellation after a successful stop receipt cannot reopen the completed admission.

A scope change never rewrites the admission's original requested scope, earlier invocation evidence, Agent identity, instructions, or membership relationships.

## Durable Notifications and Checkpoints

Mail, its notification reference, and the arrival marker share one authoritative commit receipt.

Ingress revalidates the active recipient after waiting for the activity lock, and every post-append preparation step is covered by rollback until the exact receipt is known.

Retirement or deletion before admission leaves no partial mail, while observer cancellation after acceptance preserves the source and its dispatch.

Before each request, including retries and the request immediately after a foreground wait, the runtime selects eligible unpresented notifications and commits a fresh frame with the sanitized personal window and Journal dependencies.

Every personal checkpoint captures its effective or successfully requested next scope, so a later explicit Host scope cannot restore an obsolete earlier control choice.

Reservation, dispatch, confirmed presentation, and uncertain presentation remain separate facts.

Presentation does not mark mail read, submit a ballot, change an invitation attitude, or acknowledge task attention.

An unanswered but already presented notice does not repeatedly activate an idle owner.

Duplicate ingress and delayed notification tasks check the same presentation evidence, with eligibility rechecked under the activity lock immediately before admission.

The activity lock orders idle release against arrival admission so a source arriving during the idle checkpoint cannot be stranded.

An open Native batch is retained as issued Journal and execution evidence, while its incomplete exchange is excluded from the saved model window.

After a complete batch, all its matching observations and the window commit together.

Private reads and recalled bodies retain their transient treatment and are scrubbed at invocation boundaries, including scope changes and cancellation.

The optional episodic-memory catalog remains disabled by default.

When enabled, new segments use actual invocation provenance; their isolated indexing requests have maintenance evidence and quota claims, not another personal admission or impersonation of the beneficiary.

An identity referenced by retained request or quota evidence must be archived rather than physically deleted, and removing its derived catalog cannot erase cost or forensic facts.

`enable_memory_compression` and the transitional `max_memory_turns` setting bound the recent complete personal exchanges.

Compaction adds a derived reference summary without an extra provider request, while preserving the full personal history and append-only Journal.

## Model Requests and Resource Accounting

Ordinary, ephemeral audit, and optional indexing requests use the same bounded dispatcher and atomic model-alias token ledger.

The trusted service selects the request profile; no tool or model argument can select an audit or maintenance bypass.

Audit requests retain the exact scoped participant and run evidence without ordinary Agent, inbox, Working Context, or private-library foreign keys.

The current supervisory orchestration still uses its transitional institutional discussion producer, whose replacement remains Phase 5 work.

Audit evidence records the configured shared-model budget summary rather than introducing another independent quota or allowing audits to bypass existing model limits.

The common dispatcher estimates the explicit prompt, instructions, notification content, and transmitted tool definitions before reserving prompt and maximum output capacity.

Known usage settles once, confirmed unsent attempts refund their reservation, and sent requests with unknown usage remain conservatively charged across recovery.

Capacity waits, checkpoint time, provider waits, and backoff all consume the whole retry-sequence budget.

Defaults are three additional retries, one-second exponential base, thirty-second jitter cap, 120-second request timeout, 600-second sequence timeout, and sixty-second recovery delay.

Full Jitter applies only to ATT's own exponential delay; a valid provider `Retry-After` is an independent lower bound and may exceed the jitter cap.

The request and availability records retain that earliest-retry evidence instead of dispatching early or waiting beyond the sequence budget.

Permanent authentication, configuration, programming, and validation failures require Host remediation rather than periodic retry.

A timeout or requested cancellation is not proof that a local provider call stopped.

The dispatcher retains the local owner and capacity slot until a cancellation-resistant asynchronous or synchronous call actually ends, and fences its late result from personal memory and authority.

Provider adapters must represent one upstream attempt and disable or explicitly budget hidden SDK retries.

Remote work surviving transport or process loss remains uncertain; ATT does not claim physical control of a remote provider after a crash.

## Foreground Executions

Both backends reuse the same strict parser, tool validation, auditor, classified executor, retry policy, privacy helpers, and result telemetry.

Cancellation of any Native sibling interrupts the batch without waiting for another sibling's external service, retains unresolved execution evidence, and closes the provider exchange with explicit interrupted observations.

Execution admission commits before an executor starts, and every real retry receives its own immutable attempt evidence after validation and auditing.

Rejected arguments and auditor denials do not create fictitious dispatched attempts.

Eligible execution faults create an owner-and-tool cooldown, with a default duration of ten minutes.

Cooldown rejections do not extend the duration or cancel already admitted healthy work.

Concurrent admitted failures of the same tool capture and commit their shared cooldown versions under the activity lock, and the live monotonic deadline changes only after a successful receipt, including when its observer is cancelled.

Downtime is included by default, while `cooldown_downtime="exclude"` samples and restores a remaining monotonic duration.

Undeclared custom tools remain foreground-only.

Each executor and foreground batch receives a revocable invocation-scoped authority inherited by its child tasks and synchronous worker threads.

Batch cancellation revokes that authority before cancelling siblings, and returning from a tool does not implicitly authorize detached work.

An ended executor cannot initiate new managed file operations, identity registration, addressed mail, or authoritative domain commits even if the same Agent starts another admission in the same runtime generation.

Already accepted local transactions and physical file operations may settle, while final resource-generation, ownership, and ACL checks still apply.

Identity and staged-team publication acquire resource authority before the topology lock, but release resource authority while waiting for a contended topology lock and revalidate it before publication.

A cancelled executor, shutdown fence, or restore publication therefore rejects a waiting registration without leaving an Agent or private library and without blocking revocation behind the topology reader.

Phase 2 does not enable background initiation, automatic detachment, replay, polling, reconnection, or cross-owner executor resource coordination.

## Locking, Restore, and Close

The personal invocation guard owns all changes to the person's model window, including exception cleanup.

The short activity-state lock precedes the runtime gate and domain-record commit lock for checkpoint transactions.

No activity-state or domain-record lock is held while waiting on a provider, tool, retry delay, or sleep timer.

Durable writes retain their exact receipt through caller cancellation before runtime scheduling or acknowledgements are published.

Restore requires quiescent personal work, validates and publishes through the existing staging transaction, then derives fresh local scheduling from committed evidence.

Preflight validates the personal checkpoint container, strict activity scope, ordinary-team reference, and current or historical membership evidence before any runtime or file publication.

A legitimate former team scope remains personal history rather than renewed authority; admitting activity in that team still requires current active membership.

Post-publication bookkeeping resets interrupted personal admissions, conservatively settles pending claims, and resumes eligible continuing owners without replaying an external tool action.

Publication and local activity reconstruction share one cancellation-safe finalizer; new admissions remain closed until all session indexes and interrupted-request bookkeeping are coherent.

Explicit saves are rejected throughout that restore lifetime, even when saving to another path, and recheck restore and shutdown admission under the runtime gate after preparatory waits.

Only that finalizer may submit recovery records during restoration, and actual provider execution starts through queue handoffs after the restore boundary reopens.

A failed post-publication recovery commit propagates its persistence error and leaves personal admission and optional indexing suspended until a successful restore repairs the boundary.

Close drains this accepted local recovery work before disposing of its writer, and cancellation of the restore observer cannot skip recovery or hide its commit failure.

A failure before publication preserves the old manager and files; a post-publication scheduling failure is reported against the newly published generation rather than falsely claiming the publication was rolled back.

Finite sleep resumes from the sampled remainder anchored at restoration start, excluding offline time.

Close stops admission, fences managed mutations, cancels external waits, marks unresolved foreground executions uncertain, settles accepted local checkpoints, and drains persistence without an arbitrary flush timeout.

An uncooperative provider or tool cannot indefinitely hold close or regain managed mutation authority after the fence.

## Remaining Phases

- Phase 3 supplies public team/direct-chat streams, revisions, relationship authorization, and historical visibility.
- Phase 4 supplies background execution, detachment, and complete executor/resource coordination.
- Phase 5 converts institutional producers and removes numbered discussion APIs, locks, configuration, transcripts, and round provenance.
- Phase 6 completes do-not-disturb, protected domain-notice wiring, timer precision, death handling, and the full recovery activation matrix.

## Verification

The personal-runtime package promotes all four frozen personal specifications into ordinary discovery and adds deterministic admission, notification, scope, checkpoint, quota, timeout, cooldown, shutdown, and profile tests.

Use `./venv/bin/python -m unittest discover -s test/test_att/test_agent_activity -t test` for this implemented gate.

The separately invoked background-detachment specification remains explicitly red because its public service belongs to Phase 4, not because it is skipped or treated as implemented.

Initial Phase 2 acceptance completed on 2026-10-16 on macOS with Python 3.13.

- The initial 62 personal-runtime tests pass, including the four promoted frozen specifications, restore-context corruption, Native cancellation, committed instruction dispatch, and presented-notice deduplication.
- `./venv/bin/python -m unittest discover -s test` passes all 620 tests in 428.798 seconds.
- The separate full coverage run passes all 620 tests in 778.903 seconds, with 82 percent aggregate branch coverage against the unchanged 70 percent baseline.
- Ruff, both public consumer typechecks, and `git diff --check` pass.
- Isolated source-distribution and wheel builds pass.
- An installed-wheel smoke outside the source tree verifies durable personal and team-scoped activity, retained identity, private-file isolation, quota accounting, checkpoint restoration, and SQLite foreign-key integrity.
- The separately invoked five-specification gate has four passing personal specifications and one explicit missing-background-detachment assertion, with no skips or expected-failure conversion.
- The initial replacement inventory matches 193 files and 1,682 matching lines, and the test suite leaves no project-root `.att_doc_libs` directory.

The second review adds 19 regression tests for the restore lifecycle, dependency cycles and capacity, executor authority, and personal-answer boundaries.

Its reviewed replacement inventory contains 197 files and 1,706 matching lines.

Second-review acceptance on 2026-10-17 passes all 639 tests in 435.324 seconds, including 81 personal-runtime tests.

Ruff, both public consumer typechecks, the reviewed inventory gate, and `git diff --check` pass; no project-root `.att_doc_libs` directory is created.

Third-review transaction hardening adds 15 tests for save/restore exclusion, concurrent cooldown versions, waiting registration and team publication, and mail ingress lifecycle/rollback boundaries.

All 15 new tests pass three consecutive runs, totaling 45 successful test executions in 21.011 seconds.

Third-review acceptance on 2026-10-17 passes all 654 tests in 472.942 seconds, including 96 personal-runtime tests, with the source and test content unchanged throughout the full run.

Ruff, both public consumer typechecks, `git diff --check`, and the exact inventory gate pass; the reviewed inventory contains 201 files and 1,714 matching lines, and no project-root `.att_doc_libs` directory is created.

The supported Python 3.11–3.13 and Linux, macOS, and Windows matrix still requires CI verification; the local results do not substitute for that matrix.
