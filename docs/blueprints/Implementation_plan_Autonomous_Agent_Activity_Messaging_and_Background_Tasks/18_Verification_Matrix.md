# 18. Verification Matrix

[Back to plan index](README.md).

Tests below are framework correctness tests rather than acceptance criteria for the AIs' business work.

| Area | Required adversarial cases |
| --- | --- |
| Identity | One shared person in many teams, continuous memory, membership-free activity, Root as Agent, and unchanged personal fields on relationship changes. |
| Activity serialization | Many concurrent sources, governance plus chat, delayed locks, cancellation, unavailable models, and different persons progressing independently. |
| No rounds | One silent member never blocks another, no automatic answer publication, and no legacy API, config, metadata, or export remaining. |
| Notification boundaries | Arrivals during model wait, tool wait, Native multi-tool batches, checkpoint capture, and active-to-idle transitions. |
| Presentation semantics | Unanswered and unread notices do not loop, returned unread changes do not fabricate arrivals, and uncertain provider receipt is not a false read or vote. |
| Scope | Multiple-team summaries do not combine permissions, scope changes do not alter an in-flight batch, and ambiguous or missing authority fails closed. |
| Team history | Join and leave races, frozen departure views, post-departure edit and withdrawal isolation, prior snapshots retained after rejoining, absence-gap exclusion, authorized personal archives surviving team dissolution, no post-dissolution publication, hidden counts, searches, previews, and references. |
| Chat read state | Preview independence, returned-body read marking, partial reads, per-person state, explicit unread overrides, and atomic read failures. |
| Message changes | First level-one heading outside code, untitled messages, oversized-title rejection, body-preview budgets, current-member author-only edits or withdrawal, new unread edit reminders, latest-committed-edit withdrawal deadlines, failed edits preserving deadlines, append-only versions, existing unread reminders and captured previews surviving withdrawal, unchanged read receipts, marker-only live source reads, personal deletion surviving edits, and authorized restoration. |
| Direct admission | Atomic fourth-message rejection, idempotent retry, failed-write refund, separately counted senders, refusal, and crossed requests. |
| Friendship and blocks | Either block stops both directions, final unblock resets only the intended generation, removal resets only established friendship, and stale acceptance cannot restore friendship. |
| Tool contracts | Missing or false background declarations, external registration, unknown operation, ordinary auditors, strict nested validation, denied scope, and self-mutation exclusion. |
| Resource conflicts | Same-file writes across different Agents, independent-file concurrency, move source and target ordering, managed-link aliases, external resource declarations, and accepted last-writer overwrite without file corruption. |
| Tool availability and retries | Correctable arguments, missing paths, permission denials, new-call-only cooling, unaffected healthy admitted executions, remaining-time responses, no cooldown extension or automatic replay, distinct LLM retries, Full Jitter bounds, and provider wait instructions. |
| Model retry boundaries | Per-model request timeouts, ten-minute whole-sequence limits, one-minute recovery admission, provider waits over the jitter cap, waits exceeding the remaining budget, no hidden SDK retry multiplication, non-transient remediation, uncertain usage, late-result fencing, and no overlapping unacknowledged local requests. |
| Cooldown recovery | Real downtime counted by default, explicit downtime-excluded mode, persisted accounting evidence, no restart reset, and separation from voluntary sleep timers. |
| Detachment | Explicit and automatic paths, threshold races, retry timing, one slow batch member, one execution only, and later personal result notification. |
| Artifact execution | Private ownership, archive rejection, symlink and path attacks, atomic writes, live ACL revocation, managed links, and fixed cross-library lock order. |
| Cancellation | Queued cancellation, running cooperative pause or terminal cancellation, unsupported stop, uncooperative thread, external provider, factual acknowledgement, managed-resource fence, Host risk report, completed-before-ack, and late result. |
| Task dimensions | Failed and acknowledged, running and stalled, completed and requiring attention, unsupported heartbeat, and uncertain historical running. |
| Governance | Explicit personal mail tools, voluntary queue handling, unsupported communication wake, strict boolean or alias schema, immutable votes, complete electorate, missing vote, tie, membership change, stale routes, and Root identity. |
| Independence and approval | Independent-to-independent direct delivery under every communication policy, mixed endpoints in both initiating directions, non-independent-side approval and channel requirements, explicit non-independent parent-principal deduplication, independent parents approving attached children, cross-tree lineage through both real independent tops without a common Root, unchanged within-tree routing, no branch-wide inherited exemption, relevant independence transitions staling requests, and active Agreements not automatically revoked. |
| Formation | Four attitudes, deliberate `None`, exact revisions, partial acceptance, initiator confirmation, abandonment, late joining, advisory drafts, and created-team retention. |
| Migration and failover | No nested representative invocation, full path revalidation, once-only execution, atomic ten-minute own-migration limits, inherited movement exclusion, original-parent changes, bounded failover expiry, and late-choice rejection. |
| Supervision | Genuine ephemeral teams, fresh auditors, predefined full participation, structured majority, missing or failed findings and ties as UNKNOWN, immediate deterministic integrity protection, evidence-specific triggers, teardown, and no business-progress authority. |
| Sleep | Mandatory countdown, positive-integer day, hour, and minute input, seconds rejection, default five-minute and two-day total bounds, host-adjusted bounds, any-condition wake, invalidated conditions, protected notices, and background progress while owner sleeps. |
| Do-not-disturb | Permanent and countdown scopes, sleep-equivalent duration bounds, no forced expiration for permanent settings, ordinary reminder suppression without message loss, explicit inspection, protected notices, source-and-count summaries without previews on expiry or removal, remaining-suppression filtering, unchanged read state, and personal independence. |
| Independent identity and death | No automatic death on last departure, membership-free discovery and invitation, explicit host-only death, retained history and Private DocLib, current-member and creator death without team destruction, active-call termination, Root protection, queued-task cancellation, supported task termination when suspension is unavailable, unacknowledged-stop uncertainty, and no accidental owner replacement. |
| Independent teams and live discovery | Explicitly parentless active teams remain discoverable, creator retirement preserves team identity and provenance, actual Agent-parent retirement or death and parent-AT dissolution detach only surviving direct children, descendants retain surviving immediate parents, Agent or AgentTeam reattachment preserves personal fields, no implicit Root or first-membership ancestry, no topology cycles, and dissolved teams disappear from the current directory without erasing personal archives. |
| Voluntary topology changes | Default unilateral departure without old-parent consent, strict Host permission validation and runtime disablement, cooldown and actor checks, forced-parent-loss distinction, target Agent or AT accepting reattachment, unanswered and denied acceptance leaving topology unchanged, exact-target binding, target retirement or membership-change races, cycle rejection, and no acceptance inferred from friendship or communication channels. |
| Countdown recovery | Offline time excluded, restoration start used, slow restore expiry, failed publication, bounded checkpoint error, and idempotent timer firing. |
| Incremental persistence | Every new record group, immutable snapshots, insert-only dependency closure, unrelated rows unchanged, pending-delta coalescing, and commit cancellation. |
| Schema and ownership | Schema `11` rejection before DDL, unsupported schema unchanged, competing managers and processes, WAL, foreign keys, and busy timeout. |
| Durability modes | Durable by default, missing-database rejection, explicit volatile selection, explicit receipt durability guarantees, and no silently created project-root database. |
| Restore corruption | Missing identities, impossible intervals, unauthorized sources, wrong pair generations, invalid sleep plans, dangling execution references, malformed ballots, and broken manifests. |
| Crash boundaries | Process termination before dispatch, after dispatch, after outcome observation, before result commit, during file publication, and before recovery-notice dispatch. |
| Recovery policy | Zero automatic external replay, polling, or reconnect; affected-owner wake; unaffected sleep; terminal-history exclusion; and explicit later rerun identity. |
| Runtime replacement | Old worker writes before result, writes after close, stale callbacks, stale provider responses, failed restore rollback, and safe mutation-lease revocation. |
| Privacy | No private body or raw parameters in counts, events, callbacks, generic discovery, team publication, or unauthorized audit inputs. |
| Optional memory | Disabled mode needs no indexer, correct provenance with new invocation IDs, transient recall cleanup, and no personal catalog reset on membership change. |
| Stress and cleanup | Continuous producers, slow disk, many memberships, bounded scheduling handles, fair admission, callback blocking or failure, temporary workspaces, and no leaked tasks or writers. |

Use `unittest.IsolatedAsyncioTestCase`, deterministic event barriers, and a controllable clock rather than make normal unit tests sleep for 120 seconds.

Add focused packages such as `test_agent_activity`, `test_notifications`, `test_team_chat`, `test_direct_chat`, `test_background_tasks`, and `test_activity_recovery`, with small package-local support fixtures.

Parameterize shared execution and message tests across Text ReAct and Native rather than maintain different behavioral contracts.

Use subprocesses only for writer ownership, actual process termination, and external-worker lifetime cases that cannot be proven inside one event loop.

The full implementation acceptance commands remain:

```bash
./venv/bin/python -m unittest discover -s test
./venv/bin/ruff check src test typecheck
./venv/bin/mypy typecheck/consumer_contract.py
./venv/bin/coverage run -m unittest discover -s test
./venv/bin/coverage report
./venv/bin/python -m build
```

Python 3.11, 3.12, and 3.13 must pass on Linux, macOS, and Windows according to the existing CI matrix.

Do not weaken the existing coverage baseline or treat skipped new behaviors as successful acceptance.
