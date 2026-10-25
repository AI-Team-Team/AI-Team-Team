# Phase 6: Sleep, Recovery, and Retained Lifecycle

Phase 6 completes sleep, personal reminder suppression, operation-specific recovery, and ordinary-Agent retained death over the existing common runtime.

Governance, Team Formation, communication, migration, resource decisions, and supervision keep their own rules, authority, and durable state.

Activation, notification presentation, a timeout, and an ordinary answer never supply consent or a missing ballot.

## Sleep and Reminder Preferences

`set_activity_intent` retains mandatory finite sleep with optional source or owned-execution conditions.

Sleep and timed do-not-disturb share positive day, hour, and minute inputs and the Host's default five-minute through two-day bounds.

`set_notification_suppression`, `list_notification_suppressions`, and `remove_notification_suppression` operate on the current person without Agent or policy overrides.

Preferences may be permanent or timed and cover all ordinary notifications, one Agent, or one active ordinary AgentTeam.

A source filter grants no membership, message-body access, or file permission.

Protected membership, position, permission, health, and recovery notices bypass personal filters, while explicit Host delivery modes remain separate scheduling policy.

Removing or expiring a preference atomically records summary coverage and an ordinary owner-addressed summary.

Presentation recomputes eligible source counts without titles, previews, bodies, changing read state, restoring hidden messages, or replaying every covered reminder.

Remaining suppression still filters those counts, including when another preference is added after a summary was created.

Frozen departure archives remain explicitly readable but never become current unread sources in these summaries.

Elapsed countdowns use monotonic deadlines, and a manager-owned sampler batches remaining-duration checkpoints with `activity.countdown_checkpoint_seconds=30.0` by default.

Checkpoint error includes the sampling interval and scheduling or commit delay rather than a promise to persist the final millisecond before a crash.

A lost team scope cannot remove the finite safeguard; the next valid personal invocation has no authority from that former membership.

Lawfully received model output remains personal history, while calls issued for an ended scope receive denied observations without executing.

An unavailable model ends voluntary sleep at the finite deadline but remains a separate resource block requiring the applicable retry boundary or Host remediation.

Restoration preserves that safeguard even for interruption-affected owners, and a later provider retry boundary cannot extend the saved sleep countdown.

An admitted expiry or countdown checkpoint owns its runtime through lock waits and local receipt settlement, including the brief unlocked interval before a queued waiter resumes.

Restore rejects that active handoff; dormant timers wait for restoration to finish, and a rejected restoration releases their original deadlines without resetting elapsed time.

## Recovery Publication

Recovery settles normal, audit, and indexing request evidence, quota claims, unfinished executions, resource attempts, and interrupted audit evidence in a detached manager.

Institutional services reconcile their own records without manufacturing votes, invitation attitudes, model choices, or business completion.

Required existing-record changes join recovery notifications and the publication decision before the synchronous live-registry switch.

The publication manifest retains exact before-images for the affected record identities so a failed registry switch can restore previous versions instead of only deleting newly added alerts.

Crash reconciliation defers restrictive foreign-key checks until the complete inverse transaction has restored the dependency graph.

Runtime scheduling and timer handoffs occur only after successful publication, using restoration-start anchors for saved remainders and stable checkpoint/attempt identities for deduplication.

An affected owner can wake without any prior model activity, while unaffected sleep remains intact and confirmed terminal history alone creates no restart activation.

An already recorded uncertain execution does not repeatedly wake an idle owner merely because the same checkpoint is loaded again.

Recovery never launches, reconnects, or polls an old external execution.

## Retained Death and Retirement

`preview_agent_death(agent_id)` reports affected memberships, unresolved execution identities, and the explicit terminal-death warning.

`await mark_agent_dead(agent_id, confirm=True)` is Host-only and preserves the ordinary person's ID, history, instructions, saved model alias, private artifacts, and historical creator references.

The exact receipt closes current memberships, archives the private library, cancels the sleep plan, ends active suppression, and detaches surviving direct child teams from the lost actual parent.

Other members and surviving teams remain, including a team whose size falls below its ordinary creation minimum because of the privileged death transition.

New admissions are provisionally fenced while the transition is pending, but directory readers retain the last published identity until the receipt succeeds.

Before capturing death, the transition drains already returned execution outcomes for that owner and rechecks under the domain locks for outcomes received while waiting.

This local settlement preserves live ownership and memberships until its receipt, revalidates source ACLs and bindings, and never waits for an outstanding external operation or another owner's result.

Restore rejects an admitted lifecycle task throughout its wait, commit, and cleanup, including before it acquires a membership or lifecycle lock.

A rejected death withdraws its temporary fence and rechecks original countdown deadlines and pending addressed arrivals without resetting elapsed time or waking a committed dead identity.

Committed death directly terminates outstanding checkpoint and personal-interaction observers, including queued admissions whose workers never started, while preserving already completed factual checkpoints.

Candidate lifecycle, permission, and summary Journal events are excluded from unrelated full exports until their own receipt publishes them.

Historical creation provenance never selects another creator, and leaving the last team never changes an active person's lifecycle or private state.

Creator retirement under `retain` or `archive` is permitted, and reactivation requires an explicit stable model alias.

`dead` is terminal even for the Host, and `reactivate_agent()` accepts only `retained` or `archived` identities.

Root protection and the separate disposal of temporary audit identities remain unchanged.

## External Controls and Shutdown

Queued work is cancelled without dispatch, while an executor declaring `suspension="provider"` must implement `async suspend(execution_id)` and return literal `True` to confirm suspension.

Suspension remains separate control evidence over the existing five execution states and does not manufacture completion or cancellation.

Unacknowledged suspension falls back to the supported stop protocol, and an unacknowledged stop retains uncertainty with a Host risk event.

Per-owner fencing covers personal and indexing provider waits and blocks late managed writes without stopping unrelated people.

Hooks have bounded external wait periods and no ordinary mutation authority, while already returned factual outcomes and accepted local commits settle without an arbitrary persistence timeout.

Retained or uncertain execution ownership never transfers to another Agent.

## Persistence and Verification

Schema 16 adds suppression lifecycle and duration-bound evidence, ordinary summary coverage, and recoverable existing-record before-images.

Schema 15 and earlier databases are rejected before DDL without migration.

Regression tests are organized by functionality under `test/test_att/test_agent_activity/`, `test/test_att/test_agent_lifecycle/`, `test/test_att/test_background_tasks/`, and `test/test_att/test_state_persistence/`.

They include real SQLite receipts, logical clocks, concurrent lifecycle operations, denied late writes, corruption matrices, and abrupt subprocess termination after the recovery commit.

Local implementation acceptance passed on 2026-10-25 with Python 3.13.17 on macOS.

- `./venv/bin/python -m unittest discover -s test`: 1101 tests passed in 555.683 seconds, without skips.
- The 67 focused sleep, notification, lifecycle, and recovery regressions passed, including returned-outcome settlement, queued-observer termination, countdown admission across lock handoffs, rejected restoration, lifecycle admission, and resource-blocked recovery.
- The five separately invoked frozen runtime specifications passed.
- Ruff and both public consumer mypy contracts passed.
- Source-distribution and wheel builds passed with installed build dependencies and `--no-isolation`.
- An installed-wheel smoke outside the editable source tree verified suppression, source-count summaries, private artifact retention, terminal death, and schema 16 recovery.
- All 284 Python source modules matched the final wheel byte for byte, and tests left no project-root `.att_doc_libs`.

Broader Phase 7 documentation replacement, Phase 8 extended reliability acceptance, and the supported cross-version and operating-system CI matrix remain separate work.
