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

The repository CI runs the suite on Python 3.11 through 3.13 across Linux, macOS, and Windows. The quality job also runs Ruff, the public consumer mypy contract, branch coverage with a 70 percent baseline, and a wheel build/install smoke test.

Run the same quality checks locally with:

```bash
./venv/bin/ruff check src test typecheck
./venv/bin/mypy typecheck/consumer_contract.py
./venv/bin/coverage run -m unittest discover -s test
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
        self.addCleanup(os.chdir, self._test_old_cwd)
        self.addCleanup(shutil.rmtree, self._test_tmpdir, ignore_errors=True)
        
        # Initialize your manager now (workspace_root will default to CWD which is tmpdir)
        # self.manager = ATTManager(...)
```

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

## 6. Concurrency & I/O Shielding Mocks

When writing tests that evaluate `AgentTeam` mutations, respect `team.state_lock` and the task-local `manager.suppress_auto_save()` context.

To test these protected blocks without triggering actual DB hits or risking deadlocks in the test loop:

```python
        async with self.manager.suppress_auto_save():
            async with team.state_lock:
                team.proposals["VP-123"] = {"status": "active"}
            self.manager._auto_save(teams={team.team_id})
```

Persistence tests must await `save_state`, `load_state`, `flush_state`, and `close`. Use `asyncTearDown` or `async with ATTManager(...)` so writer threads and SQLite engines are released. Successful LLM mocks must accept the arguments used by their selected mode; a mock is native-capable only when `supports_native_tool_calling()` returns the literal boolean `True`.

Direct mock clients used by persisted agents must be registered with `manager.register_llm_client(alias, client)` before the first auto-save. Close the writer manager before constructing another manager for the same database; tests that intentionally verify contention should assert `DatabaseOwnershipError`.

Callbacks are background observations. Call `await manager.flush_callbacks()` before asserting their effects. Retry tests must use typed transient failures such as `ConnectionError` or an exception with `retryable=True`; arbitrary `RuntimeError` instances intentionally do not retry.

Tool execution tests should separately cover argument correction and execution replay.

Use malformed syntax, unknown tools, strict type mismatches, or JSON Schema violations for `max_tool_argument_retries`; assert that the callable was never invoked.

Use `RetryableToolError` for `max_tool_execution_retries`, select the intended `tool_execution_retry_policy`, and opt into `Tool(retry_safe=True)` when testing the `retry_safe` policy.

A custom result string beginning with `Error:` is a successful ordinary string unless the callable raises a typed exception.

Text parser tests must include nested containers, parentheses inside strings, escaped and triple quotes, multiline content, Markdown fences, Unicode, truncation, duplicate keywords, expanded arguments, and multiple actions.

Native parallel invalid-call tests must assert that the batch consumes one correction opportunity rather than one per failed call.

Discussion tests should use `execute_reasoning_step_detailed()` and `execute_team_discussion_detailed()` when asserting failure semantics.

Default isolate policies produce `AgentTurnStatus.INCOMPLETE` and `DiscussionStatus.PARTIAL`, preserve peer results, and let the failed member rejoin the next round with a reset correction budget.

Abort-policy tests should assert `AgentTurnIncompleteError`.

Strict governance tests must prove that any incomplete turn leaves requests and approvals pending.

Operational audit tests must cover framework, supervisor, and framework-then-supervisor authority; content and runtime status combinations; and none/queue/wake degraded escalation. Durable operational alerts must be tested for stable fingerprint merging, occurrence timestamps/counts, active-wake deduplication, success removal, and failure/cancellation requeue without private tool arguments or bodies.

Team creation fault-injection tests should fail before validation, during Agent/DocLib staging, and during final publication, then compare the complete Agent, team, library, parent/child, private-library, dirty-state, and filesystem snapshots. A successfully committed team must remain registered if its first later discussion fails.

Shared-membership tests must use `existing_members` or `existing_member_ids`, assert exact object identity across teams and after restore, verify that every Agent-owned field remains unchanged, and confirm that removing one membership leaves every other membership and the Private DocLib intact. `member_configs` is reserved for creating new Agent identities and must reject legacy existing-Agent forms.

Reliability changes should cover schema preflight without mutation, competing processes, abrupt writer termination, pending-delta coalescing, cancellation, shared-agent context/tool scope, durable UNKNOWN alert states, callback ordering and isolation, and hanging-provider shutdown behavior.

The suite's `test/test_att/test_high_hardening/` package contains reference patterns for these cases.

Private Agent DocLib tests must create agents through `register_agent` or a supported team-creation path.

Cover one-library-per-UUID ownership, shared-agent reuse, missing invocation context, team-ACL/public/link denial, archive read-only behavior, explicit publish collision/overwrite behavior, lifecycle rollback, schema 7 corruption, and the absence of private body text from transcripts, callbacks, and message history. The `test/test_att/test_private_doclib/` package contains the baseline end-to-end cases.

Selective episodic-memory tests must cover disabled-mode zero indexing/tool exposure, one card per completed or incomplete turn, cancelled-turn exclusion, isolated label calls, owner-only search and recall, ephemeral recall cleanup, explicit compact retention, Journal immutability, private/tool-body redaction, FTS5 gating, Agent deletion semantics, restore corruption, and membership changes that leave all Agent-owned memory untouched.

The suite's `test/test_att/test_episodic_memory/` package contains the baseline end-to-end cases for this optional mode.

Communication changes must cover strict tool context, all three institutions, explicit Root Agent principals, parent deduplication, lineage routes, full-member strict ballots, queue/wake delivery, stale successors, directionality, endpoint revocation, idempotent delivery, rollback, restart recovery, and malformed request/approval/agreement combinations. Schema 6 and earlier databases must be rejected before DDL.
