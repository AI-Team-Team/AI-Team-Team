# Phase 5: Institutional Activity and Round Removal

Phase 5 preserves Governance, Team Formation, communication, topology, resource decisions, and health supervision as distinct institutional mechanisms while adapting their Agent execution to the continuing-person runtime.

The Autonomous Agent Runtime owns personal activity coordination, scheduling, provider requests, and execution context.

Institutional services own their rules, authorization, proposals, ballots, decisions, and authoritative state transitions.

Replacing discussion-round execution does not infer votes from activity, turn notifications into consent, or delegate institutional authority to the scheduler.

The Phase 5 local implementation and post-review hardening gate passed on 2026-10-24 with Python 3.13 on macOS; the supported cross-version and operating-system matrix still requires CI verification.

## Execution and Identity

The Manager no longer exposes team discussion APIs, numbered member rounds, team-wide discussion locks, or discussion result/transcript generation.

`execute_agent_interaction()` observes an answer from a continuing personal activity and returns an `InteractionResult` with its actual invocation and team provenance.

An answer does not stop activity, publish a chat message, or declare business completion.

The model explicitly chooses idle or finite sleep through `set_activity_intent`, while technical request/batch limits provide fairness checkpoints rather than all-member barriers.

Membership changes only update relationships and do not rewrite a person's identity, instructions, model, private workspace, or memory.

Optional episodic memory is indexed at committed personal invocation boundaries and remains available in personal scope as well as authorized team scope.

## Governance and Communication

Each governance case captures a principal, business reference, strict choice schema, electorate revision, and exact frozen eligibility.

Voters receive personal mail and voluntarily use explicit tools; opening, reading, notification presentation, and ordinary answers are not votes.

All frozen voters must submit valid choices before a strict majority supplies AgentTeam authority.

Missing votes, invalid choices, ties, changed eligibility, or unavailable people supply no authority.

Cases and ballots become visible only after the exact domain operation is acknowledged, and accepted choices survive later observer cancellation or ordinary activity failure.

Communication retains immutable policy snapshots, real parent/lineage paths, independent-side exemptions, durable channels, and endpoint-only revocation.

An explicit renewed communication request may solicit a fresh case after a tie while retaining the original pending business request and its history.

Unsupported communication `wake` is rejected; queue means voluntary personal-mail handling, not waiting for another team discussion.

Peer delivery is idempotent within a tool invocation and becomes `DELIVERED` only after its receipt, while message bodies require explicit authorized reading.

## Organization and Formation

Organizational parents are explicitly `agent`, `agent_team`, or absent; creator provenance and membership never select a substitute parent.

Attachment requires prospective-parent acceptance, and successful own-position changes atomically record a ten-minute cooldown.

Voluntary detachment has its own default-enabled Host permission, while parent retirement or dissolution detaches surviving direct children without charging an own-migration cooldown.

Formation retains exact-revision consent, four invitation attitudes, independent mail state, accepted-subset creation, final confirmation, abandonment, and explicit late joining.

`propose_team_formation` accepts the initiating person's design directly, and `prepare_team_formation_draft` is an optional validated artifact rather than a compulsory advisory process.

`dispatch_subagent` returns creation or consent references without awaiting child business work or fabricating a completed result.

## Resource and Health Boundaries

Parent failover owns an independent default 120-second resource attempt and requires explicit eligible ballots without self-reentry, shared-electorate substitution, or fallback to automatic selection.

Every model switch rechecks the current binding, organizational position, electorate, deadline, and atomic quota before acceptance.

Each health assessment creates fresh scoped people in a real managed temporary AT and runs them through the common scheduler, provider service, ToolExecutor, and writer.

Auditors can inspect admitted evidence, share permitted findings, read their restricted conversation, submit their own finding, or explicitly choose idle.

Complete valid findings followed by a strict majority form the conclusion; missing findings, failures, ties, or deadline expiry produce `UNKNOWN`.

The default total assessment deadline is 600 seconds from admission, including queueing, and is independent of the resource-decision deadline.

Health findings authorize no business repair, membership change, permission change, or model replacement.

Three consecutive model-protocol failures or five same-tool same-category argument failures within 600 seconds request assessment without declaring a person unhealthy.

Provider availability failures are not personal health findings, and semantic detectors require explicit Host enablement and an authorized evidence provider.

Confirmed permission or integrity faults require immediate deterministic protection and an incident without awaiting an audit.

Incidents use stable durable fingerprints and explicit claim/acknowledgement, with no TTL, hard dropping limit, or automatic acknowledgement on activity termination.

See [Schema 15](Schema_15.md) for persistence and recovery boundaries.

## Publication and Shutdown Regressions

Governance cases and choices, migration requests and parent positions, resource selection, and communication records publish only with their corresponding accepted receipts.

Insert-only causal personal mail cannot overwrite a newer independent read receipt, including when both forms coalesce in one writer delta.

First partial exports retain optional-candidate invocation sources and the identity, relationship, position, and cooldown prerequisites needed to validate them.

A rejected or cancelled candidate commit leaves no ready artifact, while observer cancellation after accepted settlement does not undo it.

Shutdown fencing rejects new effects but lets a tool's already returned factual outcome finish local settlement before personal activity unwinds.

Background heartbeat and progress deadlines remain independent, with one accepted timeout per signal and corresponding sample deadline even when another signal expires during a slow receipt.

Known shutdown admission closure leaves retained governance notice outboxes deferred rather than reporting a false governance failure; genuine writer and integrity errors retain their error path.

Incident claims and acknowledgements revalidate actual-parent and member authority at acceptance, including after an unrelated topology commit wins the runtime gate.

Creation depth is checked consistently across direct provisioning, optional candidates, explicit confirmation, automatic creation, staging publication, and receipt acceptance.

A depth-limit denial is a business result rather than tool-argument health evidence, and independent or Agent-parented choices remain available at a current AT's depth limit.

Clock binding is frozen before time-bearing admissions await their receipts, covering ordinary activity, executions, audits, resource decisions, cooldowns, and health-detection windows, including restoration and completed audit teardown.

Temporary audit-workspace filesystem failure preserves incident evidence and ordinary personal activity without retaining staged identities or directories.

Concurrent activities of distinct ordinary Agents and temporary audit participants retain their respective provider contexts and personal memory, with each audit limited to its own admitted evidence and durable checkpoints.

Ordinary activity continues in its original scope after the temporary audit teams dissolve.

Creation rollback now owns exact staged entities and appended-mail identities rather than restoring a manager-wide registry or inbox snapshot, and another operation cannot reconcile its unaccepted mail as a new arrival.

Formation acceptance revalidates creating-team and intended-parent membership after waits, and explicit publication and creation receipts distinguish unaccepted cancellation from accepted facts whose automatic or initial-work dispatch must survive a lost response.

All asynchronous formation transitions now use operation-local candidate registries and publish per-entity patches with the accepted receipt, preserving unrelated proposals and independent mail instead of restoring complete inbox snapshots.

Full snapshots exclude other operations' pending team identities, libraries, mail, and formation changes, so a successful unrelated save cannot resurrect a later-cancelled creation or revision during restoration.

Draft preparation, initial publication, material revisions, and unchanged draft publication revalidate creator authority at final acceptance.

Migration binds its position timestamp and cooldown after serialized admission, background record serialization, and detached validation, while revalidating live Host switches at final acceptance and preserving the exact receipt digest.

For durable commits, an event-loop clock handoff supplies immutable readings inside the SQLite transaction after its own materialization and validation, and the writer returns the canonical receipt and time anchor for runtime publication.

Pending-delta coalescing retains this binding, rejected clock reads roll back the entire transaction, and accepted transitions survive observer cancellation without resetting a remaining-duration anchor to the later observation time.

## Verification

`./venv/bin/python -m unittest discover -s test` passes all 1034 tests in 492.678 seconds.

The three post-review fix sets add 95 regression tests in total, including 36 from the third review, and the focused institutional runtime package passes all 130 tests.

All six documented representative performance workloads resolve and pass, including the additional ordinary-activity and parallel-audit isolation regression; the supervision lifecycle suite passes all 15 tests.

The five separately invoked frozen runtime specifications pass, and completed specifications remain in ordinary discovery without skips or expected-failure conversion.

The earlier Phase 5 coverage gate measured 83.84 percent aggregate coverage with branch tracking enabled, exceeding the unchanged 70-percent gate; the post-review results above are functional test measurements rather than a new coverage measurement.

The final deadline, health-transition, cancellation, timer-start, and shutdown group passes 23 tests, while the notification-outbox and topology lifecycle group passes ten tests.

Ruff, both public consumer mypy contracts, and `git diff --check` pass.

Source-distribution and wheel builds pass using already installed build dependencies with `--no-isolation`.

An installed-wheel smoke outside the editable source tree verifies personal activity, fresh scoped assessment, retained identity, independent topology, private artifacts, and SQLite save/restore.

A second installed-wheel smoke verifies receipt-owned consensual creation, stable member identity, independent detachment, persisted cooldown evidence, retained team files, and restoration after institutional notice settlement.

The wheel contains the new supervision package and no deleted discussion, solicitation-round, or legacy strategy modules.

The test suite leaves no project-root `.att_doc_libs`, `att.db`, or `att_state.db`.

Phase 6 lifecycle and complete recovery integration, Phase 7 broader documentation replacement, and Phase 8 extended reliability acceptance remain separate work.
