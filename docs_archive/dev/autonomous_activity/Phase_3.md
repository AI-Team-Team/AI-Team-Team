# Phase 3: Team Conversations and Direct Personal Chat

## Scope

Phase 3 adds explicit Markdown publications, authorized personal chat views, and pair-owned friendship controls on the existing continuing-person runtime.

It activates incompatible [schema 13](Schema_13.md), without migrating schema 12 or earlier.

Advanced episodic memory remains optional and disabled by default.

Team chat, personal direct chat, personal mail, and organizational AT-to-AT Agreement delivery are independent information surfaces.

An ordinary answer or tool observation is never automatically published to any chat.

## Source and Relationship Transactions

[`MessagingService`](../../../src/ai_team_team/core/manager/messaging/) commits immutable source records, exact command evidence, recipient views, and addressed notifications together before returning `SourceDeliveryReceipt`.

Tool idempotency uses the framework execution ID, not a provider call ID that may be reused in a later request.

Host publications require an explicit registered actor and may supply a stable operation key for lost-response retry.

Reusing that key for different input fails rather than replacing an accepted message.

Team publication, edits, withdrawals, and accepted membership changes share `team.state_lock` and one stream sequence.

The synchronous fresh-team provisioning path publishes its initial relationship boundaries inside its registry critical section; a provisional formation defers its boundaries and chat authority until its authoritative commit.

Formation late joining, administrative membership tools, and approved membership proposals use the same staged replacement adapter.

Live member lists and frozen-view references are published only after the relationship receipt settles, including when its observer is cancelled.

Membership proposal edits and new Agent registrations are also staged off-registry until that same receipt, so concurrent ordinary saves cannot capture an executed proposal without its accepted member.

Private workspace provisioning reserves names without exposing callable or discoverable Agents, and cancellation or rejection releases every unaccepted reservation and directory.

Queued proposal snapshots cannot overwrite an authoritative replacement while its receipt publication is settling.

The writer derives current SQL membership from accepted intervals rather than a progress snapshot's potentially older member list.

No join or leave changes an existing Agent's identity, model, instructions, memory, or private DocLib.

## Personal Visibility

Queries filter exact personal views before counts, search, previews, opaque pagination, and references.

Leaving freezes the latest authorized revision and withdrawal references at that exact event boundary.

Subsequent source changes do not rewrite that archive, and rejoining opens a new interval without revealing absence-period messages or refreshing old frozen views.

Former participants can inspect authorized archives in personal scope without acquiring current-team posting or DocLib authority.

`close_team_conversation(team_id)` is a Host-only archive finalization primitive, not an AI dissolution tool or a substitute for institutional consent.

It closes all remaining intervals, freezes eligible views, removes live memberships and directory visibility, and prevents later shared publication.

The primitive rejects live child-parent relationships that have not first been resolved; autonomous dissolution decisions and forced parent-loss orchestration remain Phase 5 institutional work.

Archive finalization reserves the team's topology before checking its children and retains that reservation until receipt settlement, without holding a synchronous lock during persistence IO.

Synchronous creation rechecks that reservation at publication, migration and finalization serialize their topology commits, and migration revalidates active published endpoints and the original parent both at admission and after approval.

Failed finalization releases the reservation without changing the live lifecycle, while cancellation after acceptance waits for settlement before releasing it.

State replacement cannot cross an unfinished topology transition, and SQL and detached validation independently reject active teams' parent edges to dissolved teams.

An already dissolved team's retained parent reference is historical provenance, not current topology authority, and does not prevent later finalization of that parent.

## Revisions, Read Controls, and Withdrawal

The first level-one Markdown heading outside fenced or indented code supplies the title; untitled messages are valid.

Titles default to at most 200 Unicode characters, and previews default to 500 body characters without marking the source read.

Original authors append revisions; team mutations additionally require current membership in the captured team scope.

Direct edits redeliver content through the current block/refusal checks and consume one remaining stranger delivery when the pair is not friends.

An edit updates only eligible live views, makes the new revision unread, and adds recipient reminders without restoring personally deleted views.

Withdrawal defaults to 600 seconds after the latest committed edit or original send, but any finite positive configured window is supported.

The source becomes a marker; previous live revision bodies and withdrawn-body search are unavailable.

Existing recipient read facts and captured unread reminder previews remain separate personal evidence, and earlier departure archives remain unchanged.

`list_chat_reminders()` offers paginated inspection of those exact captured previews without granting access to a withdrawn source body or advancing read state.

A monotonic revision watermark distinguishes already read versions from later unread edits, even when operations share the same clock timestamp.

Explicit body reads reuse the file content-token gate, strict effective-model counters, Unicode character continuation, and opaque source versions.

A failed or stale read returns no body and commits no read marker; a successful partial read marks only that authorized source read.

Personal-runtime reads acknowledge delivery in the same checkpoint as their actual tool observation, not when a tool merely prepares a body or a Native sibling is still running.

Cancelling an accepted observation checkpoint preserves both the durable body and its read fact, while a cancelled batch that never appends the observation leaves the source unread.

An unreturned Host read restores its exact prior personal read fields before propagating cancellation, using a receipt-bound compensation that cannot change other projection fields or retract an intervening update.

Ordinary watermark regression remains invalid; both SQL and in-memory validation restrict compensation to that exact preparation receipt.

Restore admission rejects unfinished local read deliveries and their receipt cleanup instead of replacing their owner or projection midway through settlement.

Explicit read/unread, personal deletion, restoration, and detail preferences affect only the acting person's view and do not fabricate a new arrival.

Personal detail changes hold the Agent lifecycle gate and revalidate the same active identity after waiting, so retirement cannot authorize a new preference operation.

## Direct Relationships

Root is an ordinary personal endpoint.

Canonical pair transactions lock both endpoint lifecycles and serialize allowance, friendship, request, block, refusal, message, and recipient-notification updates.

Each sender has three stranger deliveries per relationship generation; failed writes do not charge allowance and accepted retries do not charge twice.

Crossed requests do not establish friendship without explicit acceptance.

Either block ends friendship and prevents both delivery directions.

Only the owner's operation clears its block or refusal; clearing the final block or removing an established friendship starts a new generation with three allowances per sender and no automatic friendship.

Removing nonexistent friendship, cancelling, or resubmitting a request does not reset allowance.

Older accepted requests retain their historical outcome but cannot establish current friendship.

## Personal Presentation and Privacy

Every real model request receives fresh bounded eligible unread summaries, independently of whether an earlier arrival reference was already presented.

Counts remain visible when details are disabled, while hidden, frozen, and suppressed sources do not produce current unread previews or wakeups.

Notification frame persistence retains source references rather than preview bodies.

An explicitly read chat observation carries its authorized source ID in personal history; no message body is copied into generic callback, directory, or operation-receipt metadata.

## Verification

Run `./venv/bin/python -m unittest discover -s test/test_att/test_conversations -t .` for the focused implementation gate.

Tests cover real Text and Native publication, reused Native call IDs, concurrent fourth-message rejection, independent quotas and controls, frozen history, absence gaps, source-version races, read failures, deletion, withdrawal evidence, retained previews, exact receipts after cancellation and restore, SQL projection races, unrelated-row preservation, schema rejection, and corrupt-reference rollback.

Additional adversarial cases cover creation staged before archive admission, blocked-writer finalization, cancelled or failed finalization, migration against dissolved or provisional endpoints, late approval revalidation, and command-specific corruption of nonpublication receipts.

Historical receipts validate their original authorized references and evidence rather than requiring their result to equal today's friendship, view controls, preferences, or latest source projection.

The full regression suite, Ruff checks, consumer type contracts, and package build remain required alongside the existing Phase 1 and Phase 2 adversarial tests.

Phase 4 background execution, Phase 5 institutional round removal and complete topology/lifecycle adapters, and Phase 6 full recovery integration are not implemented by this gate.

### Verification Evidence

Verified locally on 2026-10-19 with Python 3.13:

- Focused conversation suite: 74 tests passed, including 21 membership-publication, read-delivery, and preference-lifecycle regressions added during the second review repairs.
- `./venv/bin/python -m unittest discover -s test`: 787 tests passed.
- Branch-enabled coverage run: 787 tests passed, with 83.29 percent combined statement/branch coverage.
- Ruff, both consumer type contracts, and `git diff --check` passed.
- Source distribution and wheel builds passed, followed by isolated wheel installation and real staged-membership, private-library ownership, chat-read, and SQLite restore checks.
- No `.att_doc_libs` directory was created in the repository root.

The final source/test/typecheck checksum is `4422decc4fab1285be0e3ad8618d6b4a1fcfc88b34547c5fcfd26cfbdc16086c`.
The final full test run includes a strengthened copy-on-write proposal assertion added after the coverage run started; the implementation code was unchanged between these runs.

The supported Python and operating-system matrix still requires CI verification; these local results do not claim that CI has run.
