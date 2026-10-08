# 17. Implementation Sequence and Gates

[Back to plan index](README.md).

The phases below are engineering dependencies within one foundational replacement, not separate public runtime generations or optional round-based modes.

Intermediate branch work may be incomplete, but the final deliverable cannot retain an old discussion scheduler as a fallback.

## Phase 0: Freeze contracts and build adversarial fixtures

- Review and freeze the confirmed contracts in Section 19 without reopening institutional decisions or changing confirmed blueprint principles.
- Inventory every call, export, field, config key, callback, test, diagram, and example that depends on discussion rounds.
- Finalize operation scope, activity intent, notification presentation, tool effects, and proposed schema `12`.
- Add deterministic model test doubles, logical-clock fixtures, controllable executors, commit barriers, and publication fault injection.
- Establish identity snapshots proving that relationship changes do not rewrite Agent-owned fields.

Gate: agreed contracts and failing regression tests express the new semantics without calling an old discussion API.

Status: completed on 2026-10-08, with implementation artifacts in the [tracked contract freeze](../../../docs/dev/autonomous_activity/README.md).

The reviewed inventory covers 169 files and 1,571 matching lines, and target effect declarations cover all 55 current built-in tools, including optional memory tools.

All 34 implemented Phase 0 checks and the complete 445-test regression suite pass, together with Ruff and both consumer typechecks.

The separately invoked six-test red gate has five explicit missing-runtime assertions and one schema-target assertion, without skips, expected failures, import errors, or old discussion API calls.

Schema 12 is reserved rather than activated, and no replacement scheduler or later-phase implementation is included.

## Phase 1: Durable primitives and publication safety

- Add activity, notification, execution-evidence, membership-history, relationship, and recovery record foundations.
- Extend immutable delta capture, dependency closure, merge behavior, writer ordering, readers, and strict validators.
- Implement exact commit receipts and post-commit notification dispatch.
- Implement or prototype recoverable restore publication and mutation leases, including late-worker file protection.
- Make unsupported schema preflight and writer ownership tests pass before any feature can dispatch work.

Gate: transaction cancellation, dependency-only updates, dirty merging, corrupt-state rejection, and publication fault tests preserve the original manager and files.

## Phase 2: Personal activity runtime and model boundaries

- Implement one ready admission per person, captured scopes, default ongoing activity, explicit idle or sleep choices, and serial model execution.
- Refactor Text and Native strategies around valid request frames, notification refresh, complete tool batches, and personal checkpoints.
- Route ordinary personal interaction and addressed notifications through this service rather than direct alternate model calls.
- Integrate quota reservation evidence, bounded LLM request and retry budgets, provider waiting instructions, failure recovery admission, and safe cancellation before releasing personal admission.
- Provide durable idle-arrival and arrival-during-activity behavior without an all-member barrier.

Gate: shared Agents never overlap, notifications enter the next valid request, silence stays non-failure, and continuing checkpoints restore committed personal context.

## Phase 3: Team and direct communication

- Implement explicit team publication, membership intervals, historical visibility, independent read state, and bounded summaries.
- Add current-member author-only Markdown revisions, new unread edit reminders, withdrawal timing renewed by committed edits, persistent personal deletion, explicit restoration, and confirmed title and preview extraction.
- Capture immutable departure-time views and prevent later source edits or withdrawals from rewriting those views.
- Keep prior departure snapshots separate after rejoining, exclude absence-period messages, and preserve existing reminder previews and read receipts after source withdrawal.
- Preserve each Agent's authorized frozen chat archive after dissolution while excluding the team from live discovery and further publication.
- Route all relationship changes through the shared ordering transaction, including bootstrap, formation, voting, and dissolution.
- Implement direct conversations, pair-owned controls, stranger allowance, friendship generation, and idempotent admission.
- Keep AT-to-AT Agreement delivery separate while exposing its organizational source correctly.

Gate: join and leave races have unambiguous visibility, previews do not mark read, old history cannot leak through query metadata, and concurrent strangers cannot exceed allowance.

## Phase 4: Execution service and background detachment

- Review every built-in tool's declared effects and implement registered executor contracts.
- Require explicit background whitelist declarations and coordinate conflicting resources across different owners without adding optimistic overwrite prevention.
- Add execution admission, explicit background initiation, automatic detachment, result storage, attention, and supported health observations.
- Integrate Text and Native task-handle observations, batch races, cancellation acknowledgements, and original-scope checks.
- Verify Private DocLib background writes and coordinated exclusion of self-modifying operations.
- Integrate capacity controls and close-time fencing without blocking persistence on an uncooperative executor.

Gate: detachment causes exactly one execution, results reach only the same owner, stale workers cannot write managed state, and cancellation does not invent terminal outcomes.

## Phase 5: Institutional adapters and complete round removal

- Replace governance solicitation rounds with cases and electorate revisions while retaining explicit mail ballots.
- Replace broker queue processing with voluntary approval mail and defer communication wake, while adapting migration decisions, bounded parent failover, autonomous proposal feedback, and initial delegated work.
- Enforce the same AT's ten-minute own-migration cooldown and remove forced team-scoped draft prerequisites.
- Support explicit independent AgentTeams and Agent or AgentTeam parent relations without inferring ancestry from creator provenance, with side-specific approval exemption and non-independent counterpart protection.
- Implement parent-loss detachment, default-enabled configurable unilateral departure, explicit target acceptance for reattachment, and cross-tree real-lineage approval without synthetic approved ballots or implicit Root substitution.
- Implement health assessments using real short-lived teams on the same runtime and replace emergency discussions with incident handling.
- Delete the discussion coordinator, its APIs, team discussion lock, round results, round config, automatic transcripts, and old public exports.
- Audit metadata and memory sanitization for hidden round dependencies and old conversation-completion assumptions.

Gate: no production path runs numbered discussion rounds, and all authorization, consent, failover, audit isolation, and creation-retention tests pass on the new runtime.

## Phase 6: Sleep, complete recovery, and lifecycle integration

- Implement sleep with mandatory finite safeguards and permanent or timed do-not-disturb with sleep-equivalent countdown bounds, protected-notice bypass, and source-and-count unread summaries when suppression ends.
- Persist and restore remaining countdowns using restoration-start anchoring.
- Complete per-domain interruption derivation and the post-publication activation matrix.
- Preserve uncertain executions without automatic business replay, reconnect, or polling.
- Support membership-free active identities and retained death records, with queued-task cancellation, supported pause acknowledgement, termination requests when suspension is unsupported, unsafe-executor fencing, shutdown evidence, and repeated-recovery deduplication.
- Remove ordinary-Agent membership, historical creator, and active-invocation death barriers, preserve Root protection, detach surviving direct child teams when their actual parent disappears, and remove dissolved teams from live discovery without removing personal chat archives.

This phase completes recovery coverage already required in Phases 1 through 5 rather than introducing recovery after the other features have shipped.

Gate: crash, restore failure, unaffected sleep, affected sleep, late result, unacknowledged cancellation, and repeated-load tests all preserve factual evidence and single-person activity.

## Phase 7: Documentation and public contract replacement

- Update README architecture and philosophy paragraphs only where the runtime contract changed.
- Replace Quickstart and user or developer API examples with explicit activity admission, messaging, and task references.
- Update Tool System, Dynamic Delegation, Team Governance, Consensual Team Formation, communication policies, persistence, and supervision documentation.
- Create a dedicated document under `docs/` describing Markdown chat, revisions, previews, read state, withdrawal, personal deletion, rejoining, and the separate live-discovery and archived-chat contracts.
- Document background whitelist registration, resource coordination, accepted serialized overwrite behavior, cooldowns, and the limits of pausing external executors.
- Replace flowcharts that assume member rounds, transcript return, implicit representatives, or emergency discussion loops.
- Reconcile the preliminary asynchronous roadmap with the governing blueprint rather than leave contradictory actor or automatic-broadcast descriptions.
- Update the public consumer typecheck and build smoke examples without keeping obsolete aliases.

Gate: examples use actual signatures, each prose sentence is kept on one source line, paragraphs remain separate, and no unrelated documentation restructuring is introduced.

## Phase 8: Full reliability and quality acceptance

- Run the deterministic contract matrix, randomized interleavings, long slow-writer tests, and process interruption scenarios.
- Run the complete existing suite after replacing obsolete round-based assertions rather than skip them.
- Run Ruff, consumer mypy, branch coverage, wheel build, and installed-wheel smoke checks.
- Validate the supported Python and operating-system CI matrix.
- Inspect success-path logs and callback payloads for unintended retry exhaustion, misclassified LLM errors, invalid governance parsing, audit cascades, or private content.

Gate: every new contract and retained invariant has passing coverage, and no project-root `.att_doc_libs` or leaked background runtime resources remain after tests.
