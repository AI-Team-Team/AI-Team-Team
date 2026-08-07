# 🛠️ AI-Team-Team Test Suite Development Guide

The `AI-Team-Team` project has an extensive suite of `unittest` test cases to ensure framework stability. When modifying or contributing to the framework, ensure all existing tests pass and appropriate coverage is added for new features.

## 1. Running Tests

The test suite is located in the `test/` directory. You can run all tests using standard standard module discovery from the project root:

```bash
./venv/bin/python -m unittest discover -s test
```

For individual test files:

```bash
./venv/bin/python -m unittest test/test_state_persistence.py
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

Reliability changes should cover schema preflight without mutation, competing processes, abrupt writer termination, pending-delta coalescing, cancellation, shared-agent context/tool scope, durable UNKNOWN alert states, callback ordering and isolation, and hanging-provider shutdown behavior. The suite's `test_high_hardening.py` contains reference patterns for these cases.

Private Agent DocLib tests must create agents through `register_agent` or a supported team-creation path.

Cover one-library-per-UUID ownership, shared-agent reuse, missing invocation context, team-ACL/public/link denial, archive read-only behavior, explicit publish collision/overwrite behavior, lifecycle rollback, schema 5 corruption, and the absence of private body text from transcripts, callbacks, and message history. `test_private_doclib.py` contains the baseline end-to-end cases.
