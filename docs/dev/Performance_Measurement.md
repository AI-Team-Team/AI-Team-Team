# Performance Measurement

This guide defines reproducible measurements for persistence validation and the asynchronous Agent runtime.

Use the [test development guide](testing.md) for correctness gates and the [persistence contract](../State_Persistence.md#validation-and-acceptance-boundaries) for authoritative acceptance boundaries.

Measurements describe a specific revision, environment, workload, and instrumentation profile; they are not cross-platform latency guarantees.

## Correctness Before Speed

The full SQL validator is the reference path for restore, untrusted checkpoints, and equivalence tests.

Routine commits may reuse accepted projections, but incremental and reference validation must enforce the same authority requirements.

These are not configurable strict and permissive persistence modes.

Performance work must preserve:

- Existing operation and commit ordering, including the relative order of dependent writes.
- Validation and exact-receipt verification before the real database commit.
- Runtime publication, candidate-cache promotion, and dependent notification dispatch only after successful acceptance.
- Rollback, cancellation settlement, error propagation, and conservative cache invalidation.
- Agent identity, personal memory ownership, and current membership and permission checks.

Run the reference-equivalence, transaction, cancellation, and cache-boundary regressions before interpreting a faster result as an improvement:

```bash
./venv/bin/python -B -m unittest discover -s test/test_att/test_incremental_validation -t test -v
```

An equal timing result does not prove equivalent validation, and a faster result does not justify skipping a constraint.

## Record the Experiment

Record the following metadata alongside every comparison:

- Commit ID and any uncommitted changes, including a retained patch and the contents of relevant untracked files.
- Operating system, CPU, available memory, Python implementation and version, SQLite version, dependency versions, and temporary-filesystem location.
- Exact test selectors, persistence mode, Agent and team counts, retained-history size, and the number of accepted operations or records.
- Whether Coverage, SQL event listeners, phase timers, asyncio debug mode, or extra logging are enabled.
- Whether the sample includes a new database and cold validation cache, a reused accepted baseline, restore, or an intentional fallback.
- Repetition count, execution order, other machine load, and raw sample results, including failures.

`git rev-parse HEAD`, `git status --short`, and `./venv/bin/python -m pip freeze` provide useful revision and dependency evidence, but a commit ID alone does not identify an uncommitted implementation.

Review metadata and patches before sharing them; do not include credentials, private document contents, prompts, model responses, tool arguments, or database payloads.

Use independent processes for repeated samples and run only one measured workload at a time.

Start with at least five samples per revision and instrumentation profile, retain every sample, and report the median and range rather than only the fastest result.

Keep the cold/warm policy and test order consistent; a fresh process resets ATT's in-process caches but does not guarantee a cold operating-system filesystem cache.

For before/after measurements, use identical fixtures and instrumentation on both revisions and alternate revision order where practical.

Do not compare full-suite durations when the selected tests, test count, instrumentation, or competing workloads differ.

## Metric Definitions

| Metric | Start and end | Interpretation |
| --- | --- | --- |
| Test-case wall time | `unittest` result `startTest()` through `stopTest()` | Includes setup, the test body, teardown, and registered cleanup; excludes earlier module import and test discovery. |
| Selected-run wall time | Immediately before `TextTestRunner.run()` through its return | Includes the selected test cases and runner overhead, but not interpreter startup, earlier imports, or Coverage report generation. |
| Observer wait time | Immediately before awaiting an identified checkpoint through completion or cancellation settlement | Measures that observer's interval, not necessarily the complete activity or persistence lifecycle. |
| Validation phase time | Entry through exit of a named validation function | Includes waits inside that function and failed attempts; nested or overlapping intervals must not be added as independent costs. |
| SQLAlchemy cursor attempts | One `before_cursor_execute` callback per observed driver execution request | Counts attempted calls through the selected SQLAlchemy engine scope, not rows or all SQLite internal statements. |
| Successful SQLAlchemy cursor calls | One `after_cursor_execute` callback per successful observed driver call | Omits calls that fail before the callback; label it separately from attempted calls. |
| Validation work and reuse | Calls, refreshed table groups, fallback counts, and retained projection identities | Explains the work performed; no universal constant-time claim follows from cache reuse. |
| Runtime progress | Accepted-operation counts, versions, queue sizes, task locations, and lock states | Helps locate a stall; a snapshot alone does not prove a deadlock. |

Use `time.perf_counter()` for elapsed intervals rather than wall-clock timestamps.

If measuring CPU time, label it separately and state whether it covers the event-loop thread, worker threads, or the whole process.

A final model answer is not an activity-stop boundary: finite personal-runtime fixtures must explicitly reach idle, and measurements must retain accepted-commit settlement and Manager cleanup.

### SQL Counting Boundaries

An `executemany` call produces one cursor event even if it handles many rows.

SQLite trigger bodies and foreign-key cascades do not each produce their own SQLAlchemy cursor event.

Raw `sqlite3` operations, including schema preflight and some checkpoint helpers, bypass an SQLAlchemy event listener.

A listener attached to one writer engine excludes other engines; a listener attached to `sqlalchemy.engine.Engine` includes all SQLAlchemy engines created during its lifetime, including the volatile validation database.

State which scope and event were used, and do not mix their counts in a comparison.

Keep statement text, bound parameters, cursor contents, and connection representations out of measurement output.

## Reproduce a Timed Sample

The following Bash example runs one selected test in a fresh process and emits metadata-only JSON on standard output, while ordinary test progress and failures remain on standard error.

Run it from the repository root after installing the project's development dependencies.

On Windows, the same Python body can be executed from a temporary script using the virtual environment's `Scripts/python.exe`; keep the working directory at the repository root.

Change `ATT_MEASURE_COVERAGE=0` to `ATT_MEASURE_COVERAGE=1` for an instrumented sample, and repeat the complete command in a new process for each sample.

Set `ATT_MEASURE_PHASES=0` alongside that variable to disable the internal phase hooks; use this same timing-and-SQL-only profile on both revisions when the baseline predates the incremental cache classes.

Revision-specific phase profiles can then be collected separately, without presenting different hooks as identical instrumentation.

Coverage data is held in memory and discarded in this example, so it does not overwrite a normal `.coverage` file or replace the CI coverage gate.

```bash
ATT_MEASURE_COVERAGE=0 ./venv/bin/python -B - <<'PY'
import json
import os
import platform
import sqlite3
import sys
import threading
import time
import unittest
from contextlib import ExitStack
from functools import wraps
from importlib.metadata import version
from pathlib import Path
from unittest.mock import patch

enabled = os.environ.get("ATT_MEASURE_COVERAGE", "0") == "1"
phase_timers = os.environ.get("ATT_MEASURE_PHASES", "1") == "1"
coverage_run = None
if enabled:
    import coverage
    coverage_run = coverage.Coverage(
        data_file=None, branch=True, source=["ai_team_team"]
    )
    coverage_run.start()

from sqlalchemy import event
from sqlalchemy.engine import Engine

hooks = []
if phase_timers:
    from ai_team_team.database.persistence.store import records
    from ai_team_team.database.persistence.store.validation.database import DatabaseValidationCache
    from ai_team_team.database.persistence.store.validation.detached import DetachedValidationCache
    hooks = [
        (DatabaseValidationCache, "prepare", "database_prepare"),
        (DetachedValidationCache, "prepare", "volatile_prepare"),
        (records, "validate_database", "full_sql_reference"),
    ]

sys.path.insert(0, str(Path("test").resolve()))
targets = [
    "test_att.test_state_persistence.test_recovery_and_registry."
    "TestStatePersistence.test_state_persistence_and_recovery",
]
suite = unittest.defaultTestLoader.loadTestsFromNames(targets)
lock = threading.Lock()
cursor_attempts = 0
phase_samples = {}
cases = []

def observe(connection, cursor, statement, parameters, context, executemany):
    global cursor_attempts
    with lock:
        cursor_attempts += 1

def timed(label, function):
    @wraps(function)
    def measure(*args, **kwargs):
        started = time.perf_counter()
        try:
            return function(*args, **kwargs)
        finally:
            elapsed = time.perf_counter() - started
            with lock:
                phase_samples.setdefault(label, []).append(elapsed)
    return measure

class Result(unittest.TextTestResult):
    def startTest(self, test):
        super().startTest(test)
        self.case_started = time.perf_counter()
        with lock:
            self.sql_started = cursor_attempts

    def stopTest(self, test):
        elapsed = time.perf_counter() - self.case_started
        with lock:
            count = cursor_attempts - self.sql_started
        cases.append({"test": test.id(), "wall_seconds": elapsed,
                      "sqlalchemy_cursor_attempts": count})
        super().stopTest(test)

event.listen(Engine, "before_cursor_execute", observe)
try:
    with ExitStack() as patches:
        for owner, name, label in hooks:
            patches.enter_context(patch.object(
                owner, name, timed(label, getattr(owner, name))
            ))
        started = time.perf_counter()
        result = unittest.TextTestRunner(
            resultclass=Result, verbosity=2
        ).run(suite)
        elapsed = time.perf_counter() - started
finally:
    event.remove(Engine, "before_cursor_execute", observe)
    if coverage_run is not None:
        coverage_run.stop()

print(json.dumps({
    "python": sys.version,
    "platform": platform.platform(),
    "sqlite": sqlite3.sqlite_version,
    "sqlalchemy": version("sqlalchemy"),
    "coverage_enabled": enabled,
    "coverage_version": version("coverage") if enabled else None,
    "phase_timers_enabled": phase_timers,
    "sql_event": "before_cursor_execute",
    "sql_scope": "all_sqlalchemy_engines_during_selected_run",
    "selected_run_wall_seconds": elapsed,
    "tests_run": result.testsRun,
    "successful": result.wasSuccessful(),
    "failures": len(result.failures),
    "errors": len(result.errors),
    "skipped": len(result.skipped),
    "cases": cases,
    "phases": {
        label: {"calls": len(values), "total_seconds": sum(values),
                "max_seconds": max(values)}
        for label, values in sorted(phase_samples.items())
    },
}, sort_keys=True, indent=2))
raise SystemExit(0 if result.wasSuccessful() and not result.skipped else 1)
PY
```

Preserve standard output as a separate JSON sample and retain the test log with its exit status; a failed, skipped, or timed-out sample is not a successful timing result.

Module imports and test loading happen before the cursor listener and selected-run timer start, while per-test setup and cleanup happen inside their measurement boundaries.

The phase wrappers count calls that raise and aggregate all selected cases; `full_sql_reference` can be nested inside `database_prepare`, so their totals are not additive.

The wrappers target the current internal implementation and must be reviewed if imports or call sites change; they are process-local measurement hooks, not production APIs or a switch for disabling validation.

The example keeps normal asyncio debug and logging behavior rather than silently changing those settings for a faster sample.

Test cases may emit ordinary logs independently of the JSON output, so inspect those logs before publishing an artifact.

### Representative Workloads

Use the same target list for both revisions and keep each case's ordering fixed.

The following existing cases exercise distinct boundaries:

- `test_att.test_agent_activity.test_runtime_boundaries.RuntimeBoundaryTests.test_working_window_is_bounded_without_erasing_history_or_cutting_a_batch`: continuing activity, bounded working context, and retained history.
- `test_att.test_personal_governance.test_review_regressions.GovernanceReviewTests.test_cancelled_native_submission_keeps_the_next_interaction_usable`: accepted Native ballot submission and cancellation settlement.
- `test_att.test_policies.TestMigrationPolicies.test_lineage_path_uses_every_explicit_principal`: multi-principal governance and subsequent commits.
- `test_att.test_state_persistence.test_recovery_and_registry.TestStatePersistence.test_state_persistence_and_recovery`: save, restore, registry reconstruction, and cleanup.
- `test_att.test_supervision_lifecycle.TestSupervisoryTeamLifecycle.test_parallel_audits_have_separate_live_owners_and_provider_context`: concurrent short-lived audit teams with distinct owners and provider scopes.
- `test_att.test_supervision_lifecycle.TestSupervisoryTeamLifecycle.test_parallel_personal_activities_and_audits_keep_separate_contexts`: concurrent activities of two distinct ordinary Agents and two audit teams with isolated provider contexts and admitted evidence, including ordinary continuation after audit teardown.

The sample command defaults to the recovery case; replace or extend `targets` with the exact selectors above to measure another workload.

Run workloads individually for attribution and as a fixed selected suite to expose interactions, but do not compare these two execution profiles as if their cache conditions were identical.

These fixtures use scripted clients and temporary workspaces rather than live providers; they measure framework work, not external model latency.

## Measure Reuse and Fallbacks

Separate first-use validation from steady-state deltas instead of averaging away initialization.

For durable writes, observe `DatabaseValidationCache.prepare`, full-reference call counts, and actual SQL work; a prepare call alone does not prove the incremental branch was used.

For volatile candidates, observe `DetachedValidationCache.prepare`, `checked_tables`, and identity reuse of unchanged table projections in controlled fixtures.

Candidate preparation is not acceptance, so record or assert successful commit and cache promotion separately.

Use fixtures with a fixed changed entity set and increasing unrelated history to check that unrelated SQL reads and physical table replay do not grow unnecessarily.

Graph traversal and conservative cross-row or collection checks can still scale with retained state; report those costs without describing the entire commit as O(1).

Exercise fresh connections, external database mutations, full snapshots, unknown SQL effects, and persistent or temporary triggers as explicit fallback workloads.

An intended full validation after invalidation is a safety behavior, not automatically a cache regression.

The incremental-validation suite already checks full-reference equivalence, reverse dependencies, native constraints, stale candidates, failed commits, and SQL work for an isolated delta.

Its SQL assertion uses successful `after_cursor_execute` events on one store engine, unlike the global attempted-call listener in the sampling example.

Do not remove fallbacks, enlarge observer deadlines, or alter batching and ordering merely to improve a measurement.

## Event-Loop Responsiveness

The `test_slow_preparation_does_not_block_heartbeat_or_publish_baseline` regression in `test/test_att/test_incremental_validation/test_volatile_lifecycle.py` holds worker validation at a real barrier and proves that an event-loop callback still runs before preparation is released.

That test checks responsiveness and non-publication, not a production latency percentile.

For a latency experiment, schedule periodic callbacks against absolute deadlines using the event loop's monotonic clock and record `max(0, actual_time - scheduled_time)` for each callback.

Keep the interval, workload, instrumentation, sample count, and missed-deadline handling fixed, then report the median, a sufficiently sampled tail percentile, and maximum delay.

Use absolute deadlines rather than repeatedly sleeping for one interval after the previous callback, which can hide accumulated drift.

Do not emit a log or capture runtime payloads on every tick; store small timing samples and report them after the workload and cleanup finish.

## Diagnose CI Timeouts

Use `test/async_waits.py` for bounded runtime observers and collect its diagnostic before cancellation changes the live state.

The shared default is 60 seconds, and explicitly larger scenario budgets remain explicit.

This is a test observer budget, not a production provider timeout, governance timeout, or limit on settling an accepted persistence commit.

Retain the test selector, environment, instrumentation profile, exit status, diagnostic timestamp, and payload-free runtime snapshot.

Inspect accepted-operation counts and state versions alongside persistence activity, pending deltas, record counts, model-request counts, queue sizes, worker locations, dependency edges, and lock states.

An idle queue with a blocked provider, an active writer with pending work, and a dependency cycle are different hypotheses; use progress and stack locations to investigate rather than assigning a cause from `TimeoutError` alone.

A single snapshot may identify a waiting boundary but cannot establish whether progress has stopped permanently.

Diagnostic timer execution can itself be delayed by event-loop starvation, and cancellation settlement may continue beyond the nominal observer deadline.

Do not relabel a domain `TimeoutError`, swallow external cancellation, or abandon an accepted commit to make an observer finish sooner.

If selected tests pass but CI times out, repeat the matching Python and Coverage profile, then run the complete suite without competing benchmark processes.

## Report Results

Store the experiment metadata and raw samples with a summary containing:

- Baseline and candidate revisions, including dirty-worktree evidence when applicable.
- Exact workload, dataset sizes, persistence and cache profile, and instrumentation.
- Passed, failed, skipped, and timed-out sample counts.
- Per-case and selected-run wall-time medians and ranges.
- SQL event type, engine scope, call counts, and relevant validation phase statistics.
- Reference-equivalence and ordering/rollback/cancellation regression results.
- Remaining uncertainty, platform coverage, and any deliberate fallback behavior.

Earlier exploratory local Python 3.13 Coverage runs observed a six-case total of about 89.6 seconds before optimization and 24.4 seconds afterward.

The recovery case's global SQLAlchemy `before_cursor_execute` count fell from 128,955 to 17,280 in those exploratory runs.

Those observations did not preserve every environment detail or enforce this complete sampling protocol, so they motivate reproducible follow-up measurements rather than define a baseline or CI service-level objective.

Do not infer a controlled full-suite speedup from historical runs with different test counts or overlapping test processes, and do not infer that repeated validation was the sole cause of every CI timeout.
