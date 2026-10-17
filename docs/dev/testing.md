# 🛠️ AI-Team-Team Test Suite Development Guide

The `AI-Team-Team` project has an extensive suite of `unittest` test cases to ensure framework stability. When modifying or contributing to the framework, ensure all existing tests pass and appropriate coverage is added for new features.

## 1. Running Tests

The test suite is located in the `test/` directory. You can run all tests using standard module discovery from the project root:

```bash
./venv/bin/python -m unittest discover -s test
```

For an individual test package:

```bash
./venv/bin/python -m unittest discover -s test/test_att/test_state_persistence
```

The repository CI runs the suite on Python 3.11 through 3.13 across Linux, macOS, and Windows.

The Ubuntu/Python 3.13 matrix entry measures branch coverage with a 70 percent minimum and uploads HTML/XML reports with a 14-day retention period.

Reports are generated after successful or failed test execution, but not after a failed Coverage installation or a cancelled job.

The quality job runs Ruff and both public mypy contracts, while a separate wheel-smoke job builds, installs, and imports the package.

The autonomous-activity replacement has a [Phase 0 contract freeze](autonomous_activity/README.md), [Phase 1 durability gate](autonomous_activity/Phase_1.md), and [Phase 2 personal-runtime gate](autonomous_activity/Phase_2.md), with deterministic fixtures and a separately invoked `spec_*.py` gate for remaining unimplemented services.

Ordinary discovery includes schema activation, publication safety, and the four implemented personal specifications in `test/test_att/test_agent_activity/`.

`./venv/bin/python -m unittest discover -s test/test_att/test_autonomous_activity_phase0 -t . -p 'spec_*.py'` still exposes the unimplemented background-detachment requirement explicitly, without skips or expected-failure success.

Use `./venv/bin/python -m unittest discover -s test/test_att/test_agent_activity -t test` to verify coalescing, continuing activity, batch scope, mail presentation, request/claim settlement, finite timers, late fencing, and scoped audit/index profiles.

Tests needing a finite personal interaction must script the Agent's explicit idle control rather than treat a final answer as a runtime stop.

Wait for real worker registration, commit receipts, and lock-attempt barriers instead of assuming a fixed count of event-loop yields establishes synchronization.

The five-Agent dependency-chain regression uses one 60-second end-to-end watchdog, including final idle settlement, to accommodate slower CI runners without changing runtime safety limits.

Watchdog failures report dependency edges, worker locations, queue sizes, model-call counts, and lock states without including prompts, responses, or tool payloads.

Personal-runtime regressions include corrupt activity-context restore preflight, Native sibling cancellation, instruction cancellation on both sides of source acceptance, and delayed or duplicate notification dispatch after confirmed presentation.

Additional transaction regressions queue an explicit save before restore admission, complete same-tool Native faults concurrently, revoke identity and team publication while topology is contended, and retire a mail recipient while ingress waits for the activity lock.

These tests distinguish rejected preparation from a successful receipt followed by observer cancellation, and verify that no unaccepted inbox row, cooldown deadline, identity, or private directory remains.

Run `./venv/bin/mypy typecheck/activity_contract.py` alongside the existing public consumer contract when editing the frozen value records.

Do not interpret the current round-based regression suite passing as acceptance of the replacement runtime, and promote completed specifications into ordinary discovery in their implementing phase.

Run the same quality checks locally with:

```bash
./venv/bin/ruff check src test typecheck
./venv/bin/mypy typecheck/consumer_contract.py typecheck/activity_contract.py
./venv/bin/coverage run -m unittest discover -s test
./venv/bin/coverage html --fail-under=0
./venv/bin/coverage xml --fail-under=0
./venv/bin/coverage report
./venv/bin/python -m build
```

## 2. Asynchronous Execution

Because the `ATTManager` utilizes standard python `asyncio` routines for core reasoning steps and message handling, the entire test suite must execute asynchronously.

All core tests MUST inherit from `unittest.IsolatedAsyncioTestCase` rather than `unittest.TestCase`.

```python
import unittest

class TestFeature(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Async initializations
        pass
        
    async def test_something_async(self):
        await self.manager.process_message()
```

## 3. Pathing and Imports

Be mindful of python's module path resolution. Always ensure `sys.path` is pre-pended with the `src` directory before attempting relative framework imports in a test file:

```python
import sys
import os

CURRENT_DIR = os.path.dirname(__file__)
ROOT_DIR = os.path.abspath(os.path.join(CURRENT_DIR, "..", ".."))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)
```

## 4. Test Isolation (Sandbox Environments)

Because `ATTManager` and `DocumentLibrary` dynamically generate directories (e.g. `.att_doc_libs`, `DL-AT-xxx`) and persist SQLite databases, **you must ensure tests run in an isolated sandbox** to prevent polluting the project root.

Directory-based suites may place shared clients and fixture base classes in a package-local `_support.py`. Keep assertions and behavior-specific setup in the individual test module so changes to one support fixture do not silently alter unrelated test domains.

To achieve this, inject a temporary directory sandbox into the `setUp()` method of every test class. This guarantees that `workspace_root` (which defaults to the current working directory) points to an ephemeral folder that is cleanly destroyed after the test.

```python
    def setUp(self):
        import tempfile, os, shutil
        self._test_old_cwd = os.getcwd()
        self._test_tmpdir = tempfile.mkdtemp(prefix="att_test_")
        
        # Lock CWD into the isolated temp directory
        os.chdir(self._test_tmpdir)
        
        # Ensure cleanup runs after tearDown()
        self.addCleanup(shutil.rmtree, self._test_tmpdir, ignore_errors=True)
        self.addCleanup(os.chdir, self._test_old_cwd)
        
        # Initialize your manager now (workspace_root will default to CWD which is tmpdir)
        # self.manager = ATTManager(...)
```

Cleanup callbacks run in reverse registration order, so register directory removal first to restore the working directory before deleting the sandbox.

## 5. Mocking LLM Responses

Since production code is strictly forbidden from importing `unittest.mock` or containing test-specific conditional branches (Issue 9 compliance), you **must** mock LLM responses by registering a mock handler callback on the `ATTManager` or passing a compliant `LLMClientAdapter`.

Do **NOT** attempt to pass raw `MagicMock` or `AsyncMock` objects expecting the framework to automatically handle them via `isinstance` checks.

### A. Register a Mock Handler Callback

```python
        # ATT installs its reserved manager context automatically.
        async def mock_generate(prompt, system_instruction=None, tools=None, temperature=0.3, require_json=False):
            return '{"thought": "test", "commands": []}'
            
        self.manager.generator_handler = mock_generate
```

## 6. Concurrent State Mutations

When writing tests that evaluate `AgentTeam` mutations, respect `team.state_lock` and the task-local `manager.suppress_auto_save()` context.

To test these protected blocks without triggering actual DB hits or risking deadlocks in the test loop:

```python
        async with self.manager.suppress_auto_save():
            async with team.state_lock:
                team.proposals["VP-123"] = {"status": "active"}
            self.manager._auto_save(teams={team.team_id})
```

Wrap the real per-team session lock in the test fixture so `second_a_attempted` is set immediately before the competing task awaits acquisition, with no intervening suspension.

With AT-A's first discussion paused and competing discussions started on both teams, wait for the actual lock attempt and verify that AT-B runs while AT-A's next discussion waits:

```python
await asyncio.wait_for(second_a_attempted.wait(), timeout=10)
await asyncio.wait_for(b_started.wait(), timeout=10)
self.assertFalse(second_a_started.is_set(), execution_order)

release_first_a.set()
await asyncio.wait_for(asyncio.gather(first, emergency, other_team), timeout=10)
```

Record the first discussion's actual lock release and assert the order `A1-start → B-start → A1-released → A2-start`, rather than treating an LLM Mock returning as the end of the full session.

Release blocking events and cancel and await unfinished tasks in `finally`, and verify that deliberately bypassing the session lock makes the test fail.

`asyncio.sleep(0)` yields an execution opportunity but does not establish that a particular task has reached the protected boundary.

## 7. Persistence & I/O

Persistence tests must await `save_state`, `load_state`, `flush_state`, and `close`.

To test crash recovery, pause the relevant provider or executor at an explicit barrier, freeze a SQLite backup, and restore that fixed checkpoint through a fresh Manager after releasing and closing the original runtime.

Do not read an in-flight detached snapshot, let its original Journal advance, and apply the old snapshot back to the same database; that is a stale-restore rejection case, not an isolated crash checkpoint.

- Use `asyncTearDown` or `async with ATTManager(...)` so writer threads and SQLite engines are released.
- Direct mock clients used by persisted agents must be registered with `manager.register_llm_client(alias, client)` before the first auto-save.
- Close the writer manager before constructing another manager for the same database; tests that intentionally verify contention should assert `DatabaseOwnershipError`.

After saving a file delta and closing the original writer, restore it into a fresh Manager with the required model binding:

```python
restored.register_llm_client("test", self.client)
await restored.load_state(db_path)
restored_team = restored.teams[team.team_id]
self.assertIn(
    "persisted delta",
    restored_team.doc_library.read_file("delta/note.txt"),
)
```

Schema 11 and earlier databases must be rejected before DDL.

### Reliability

Reliability changes should cover:

- Schema preflight without mutation, competing processes, abrupt writer termination, pending-delta coalescing.
- Cancellation, shared-agent context/tool scope.
- Durable UNKNOWN alert states, callback ordering and isolation, and hanging-provider shutdown behavior.

The suite's `test/test_att/test_high_hardening/` package contains reference patterns for these cases.

### Volatile Relationship History

Volatile relationship tests must exercise:

- Normal member tools, consensual late joins, nested suppression.
- Checkpoint export followed by further changes.
- Unchanged Agent-owned fields and the absence of implicit disk writes.

### Message Withdrawal

Withdrawal tests must cover source-projection consistency in domain merges, direct SQL writes, corrupt and detached checkpoints, while preserving recipient-owned frozen views, read evidence, and captured previews.

### Topology Recovery

Topology recovery tests must keep the Manager and its parent resolver on the same authoritative index across successful restore, failed restore publication, and team creation rollback.

- Exercise save, migrate, restore, and tool-view lookup to reject obsolete parents, then force a parent-cache miss after a new migration to verify that the restored index remains live.

The `test/test_att/test_state_persistence/test_topology_index.py` module covers these parent-index recovery cases.

## 8. Feature-Specific Test Requirements

### LLM Mocks and Retries

Successful LLM mocks must accept the arguments used by their selected mode; a mock is native-capable only when `supports_native_tool_calling()` returns the literal boolean `True`.

Retry tests must use typed transient failures such as `ConnectionError` or an exception with `retryable=True`; arbitrary `RuntimeError` instances intentionally do not retry.

### Callback Dispatch

Callbacks are background observations.

Call `await manager.flush_callbacks()` before asserting their effects.

With the callback appending events to `observed`, emit from a worker thread and check order after flushing:

```python
for index in range(8):
    await asyncio.to_thread(manager._emit_callback, "on_system_event", index, {})
await manager.flush_callbacks()
self.assertEqual(observed, list(range(8)))
self.assertEqual(manager._callbacks.deferred, [])
```

Callback tests must include:

- Worker-thread emissions both before and after the dispatcher starts.
- Mixed thread/event-loop ordering, automatic wake, flush completion, neutral invocation context.
- Observer-raised and task self-cancellation, cancelled flush callers.
- Cancellation-resistant shutdown and late emissions after shutdown.

### Tool Execution and Parsing

Tool execution tests should separately cover argument correction and execution replay.

- Use malformed syntax, unknown tools, strict type mismatches, or JSON Schema violations for `max_tool_argument_retries`; assert that the callable was never invoked.
- Use `RetryableToolError` for `max_tool_execution_retries`, select the intended `tool_execution_retry_policy`, and opt into `Tool(retry_safe=True)` when testing the `retry_safe` policy.
- A custom result string beginning with `Error:` is a successful ordinary string unless the callable raises a typed exception.
- Native parallel invalid-call tests must assert that the batch consumes one correction opportunity rather than one per failed call.

With the team, Agent, and imports supplied by the fixture, an error-looking string is still a successful result:

```python
tool = Tool("custom", "Custom string", lambda: "Error: domain text")
result = await ToolExecutor(self.team, self.agent, self.manager).execute(
    "custom", tools={"custom": tool}
)
self.assertIs(result.status, ToolResultStatus.SUCCESS)
self.assertEqual(result.content, "Error: domain text")
```

Text parser tests must include:

- Nested containers, parentheses inside strings, escaped and triple quotes, multiline content.
- Markdown fences, Unicode, truncation, duplicate keywords, expanded arguments, and multiple actions.

### Discussions and Operational Audits

Discussion tests should use `execute_reasoning_step_detailed()` and `execute_team_discussion_detailed()` when asserting failure semantics.

- Default isolate policies produce `AgentTurnStatus.INCOMPLETE` and `DiscussionStatus.PARTIAL`, preserve peer results, and let the failed member rejoin the next round with a reset correction budget.
- Abort-policy tests should assert `AgentTurnIncompleteError`.
- Strict governance tests must prove that any incomplete turn leaves requests and approvals pending.

When the mock gives the first member malformed tool syntax, inspect the detailed discussion result:

```python
result = await self.manager.execute_team_discussion_detailed(
    self.team, "work", rounds=2, skip_audit=True
)
self.assertIs(result.status, DiscussionStatus.PARTIAL)
self.assertIs(result.rounds[0].turns[0].status, AgentTurnStatus.INCOMPLETE)
```

Operational audit tests must cover framework, supervisor, and framework-then-supervisor authority; content and runtime status combinations; and none/queue/wake degraded escalation.

- Durable operational alerts must be tested for stable fingerprint merging, occurrence timestamps/counts, active-wake deduplication, success removal, and failure/cancellation requeue without private tool arguments or bodies.

### Supervisory Lifecycle

Supervisory lifecycle tests must verify that direct audits and ordinary discussions:

- Use distinct registered teams and Agent identities under concurrency.
- Preserve each active audit context.
- Hide temporary auditors from ordinary recruitment.
- Keep completed evidence after database restore and dissolve the team on completion, cancellation, or shutdown.

A full save taken during an audit must not persist its temporary team, auditor identities, or DocLibs; restoring that snapshot must not recreate an abandoned audit.

### Team Creation and Shared Membership

Team creation fault-injection tests should fail before validation, during Agent/DocLib staging, and during final publication, then compare the complete Agent, team, library, parent/child, private-library, dirty-state, and filesystem snapshots.

A successfully committed team must remain registered if its first later discussion fails.

Shared-membership tests must use the consensual formation workflow for ordinary APIs or `bootstrap_agent_team()` only in fixtures that explicitly provision topology.

Tests must:

- Assert exact object identity across teams and after restore.
- Verify that every Agent-owned field remains unchanged and confirm that removing one membership leaves every other membership, invitation history, Agent inbox, and Private DocLib intact.

`member_configs` is reserved for creating new Agent identities and must reject legacy existing-Agent forms.

With the same Agent added to both teams and `identity_before` captured before joining, check object identity and unchanged Agent-owned state:

```python
self.assertIs(
    next(member for member in team_a.members if member is self.shared), self.shared
)
self.assertIs(
    next(member for member in team_b.members if member is self.shared), self.shared
)
self.assertEqual(self._identity_state(), identity_before)
```

### Consensual Formation

Formation tests must cover:

- All four public invitation attitudes, explicit `None` as externally indistinguishable no-response.
- Exact-revision authorization, material and no-op revisions, renewed consent.
- Detached collaborative drafts, explicit publication, accepted-subset eligibility.
- Zero-invitee automatic creation, confirmed completion, abandonment notifications.
- Optional late joining, initiator self-membership with deferred discussion.
- Per-request concurrency, trusted bootstrap auditing/tool exclusion, Agent inbox persistence, schema corruption, and restore rollback after inbox publication.

### Private Agent DocLib

Private Agent DocLib tests must create agents through `register_agent` or a supported team-creation path.

Cover:

- One-library-per-UUID ownership, shared-agent reuse.
- Missing invocation context, team-ACL/public/link denial, archive read-only behavior.
- Explicit publish collision/overwrite behavior, lifecycle rollback, current-schema corruption, and the absence of private body text from transcripts, callbacks, and message history.

The `test/test_att/test_private_doclib/` package contains the baseline end-to-end cases.

### Selective Episodic Memory

Selective episodic-memory tests must cover:

- Disabled-mode zero indexing/tool exposure, one card per completed or incomplete turn, cancelled-turn exclusion.
- Isolated label calls, owner-only search and recall.
- Character- and token-bounded continuation that reconstructs long single lines and Unicode without gaps or duplication, Segment-version mismatch rejection.
- Ephemeral recall cleanup, explicit compact retention, Journal immutability, private/tool-body redaction.
- FTS5 gating, Agent deletion semantics, restore corruption, and membership changes that leave all Agent-owned memory untouched.

The suite's `test/test_att/test_episodic_memory/` package contains the baseline end-to-end cases for this optional mode.

### Incremental Memory Persistence

Incremental memory tests use real SQLite and independently gated member/indexer responses to verify commits before a discussion's auto-save batch exits, both with constructor-bound persistence and after restore.

Cover:

- New nested teams whose identity registration is still batched, segment/card/reference-only deltas.
- Index failure and cancellation, actual recovery of processing index jobs.
- Distinct parent/creator dependencies after migration, immutable source replay, and insert-only dependencies that leave existing Agent, team, and DocLib rows and files unchanged.

### Agent Instructions and Synchronous Delegation

Reasoning-strategy tests must assert that persistent Agent `system_instructions` reach Text ReAct, Native, auto-selected Native, and no-tool business turns together with the invocation-scoped AgentTeam instructions.

Synchronous delegation tests must reject direct self-inclusion and inherited ancestor invocation dependencies before creating any Agent, AgentTeam, or DocLib, while retaining a passing idle-Agent delegation control.

Detached tasks that inherit a completed ContextVar chain must not be treated as active dependencies.

### Token-Based File Reading

Token-based file-reading tests must cover:

- Many short lines, extremely long single lines, Unicode, normalized mixed line endings.
- Exact continuation without gaps, range validation, file-version changes.
- Registered/provider/host/conservative/strict counters, failover counter changes.
- Private and team reads, ACL and managed-link checks, decoding failures, and the rule that only returned content counts against `max_read_tokens`.

Invoke model-facing reads through `ToolExecutor` or establish both active Agent and AgentTeam ContextVars; direct `Tool.__call__()` has no model identity from which to resolve a counter.

The suite's `test/test_att/test_file_reading/` package contains the model-context integration cases, while `test/test_gated_reader.py` covers the standalone reader.

### Communication

Communication changes must cover:

- Strict tool context, all three institutions, explicit Root Agent principals, parent deduplication, lineage routes.
- Full-member strict ballots, queue/wake delivery, stale successors, directionality, endpoint revocation.
- Idempotent delivery, rollback, restart recovery, and malformed request/approval/agreement combinations.

Use bounded, condition-based waits for detached personal voting and authoritative commits rather than short sleeps or a one-second completion budget.

A discussion returning does not mean its subsequent personal ballots have finished, and a staged terminal status is not ready until the communication transaction completes.

Timeout diagnostics should show request and approval states, vote counts, and worker locations without exposing rationale, message bodies, or tool arguments.

Observe background tasks when they are registered and retain their completion outcomes so removed or replaced live entries cannot hide failures in negative-path tests.

Only report an observer timeout when its deadline actually expires, and propagate worker exceptions without relabeling them.

Register asynchronous cleanup as soon as a fixture owns a Manager so failures and cancellations still close every writer before the working directory is restored and its workspace is removed.

### Agent and AgentTeam Discovery

Run the focused cases with `./venv/bin/python -m unittest discover -s test/test_att/test_discovery -t .`.

Cover:

- One-based inclusive entity positions, the 30-result default without an explicit-range cap, empty and truncated range metadata.
- Strict integers, type selection, case-insensitive OR substring matching, and deterministic `A, a, B, b` ordering with stable ties.
- Verify active Root, idle, busy, shared, membership-free, and dependency-chain Agents remain discoverable while inactive and audit-scoped identities and teams are excluded.
- Assert the exact public field allowlist, no private-content search, no Agent-owned mutation or depth-cache update, and unchanged consent, communication Agreement, and document ACL checks.
- Capture actual Text ReAct, Native, personal, governance, and formation inputs to reject automatic global directory injection while preserving personal identity and existing memory.
- Check explicit tool observations, unsupported actor or pagination-mode overrides, live-page changes, internally consistent counts under parallel changes, migration freshness, and save/restore without a discovery index.
- Exercise synchronous discovery through the real background callback dispatcher while registering, archiving, reactivating, and deleting Agents.
- Use controlled publication barriers to reject mixed team-status fields, mixed old/new restore registries, failed-restore state, and audit identities exposed during a failed team creation.

### Personal-Inbox Governance

Use normal Text ReAct or Native clients that explicitly invoke `open_agent_mail` and `submit_governance_choice`; standalone synthetic JSON responses must not stand in for Agent ballots.

Cover:

- Continuing personal instructions and history, no automatic private-file injection, read-receipt independence, voluntary unanswered mail.
- Strict choice schemas, immutable idempotent votes, complete participation, ties and new rounds.
- Shared-Agent serialization and session-lock release while answers remain pending.

Preserve all four formation attitudes and prove that `None` and `no_response` remain domain semantics rather than email states.

Cover:

- Failover timeout and caller cancellation, late-choice rejection, durable migration progress.
- Submission rollback, schema corruption, exact mailbox-to-round ownership, append-only ballots, and authoritative commits made inside an outer auto-save suppression batch.
- Reject unrecognized decision statuses and derive authoritative communication ballot projections from the accepted round rather than independently supplied summaries.
- Cover interrupted Native submissions and their next ordinary interaction, fatal parallel-tool cleanup before invocation-lock release, and admission checks after waiting for a lock during shutdown or restore.
- Verify multi-principal `PROCESSING` consistency, exact sibling-order rollback after failed migration commits, and rejection of non-finite governance timestamps without changing the live manager.

The `test/test_att/test_personal_governance/` package contains focused integration cases.

### Personal Activity Lifecycle Boundaries

The `test/test_att/test_agent_activity/` package includes real-client and SQLite regression cases for restore finalization, synchronous interaction dependencies, answer observation, and revocable foreground execution authority.

Cover post-publication cancellation and commit failure, admission attempts during reconstruction, and close while recovery still owns accepted local work.

Exercise self-dependencies, longer identity cycles, parallel nested observers, one-slot acyclic progress, and cancellation without waiting for a downstream provider.

Verify that technical model/tool budgets and scope checkpoints do not produce empty completed answers, while an explicit idle or sleep choice remains observable.

Test both asynchronous and synchronous cancellation-resistant tools, inherited child contexts, rejected new managed writes after a later admission, and successful settlement of a file operation accepted before cancellation.
