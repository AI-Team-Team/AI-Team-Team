# Phase 8: Reliability and Quality Acceptance

ATT's reliability acceptance checks the implemented personal runtime and its interaction with independent institutional mechanisms.

Agent identity, personal state, exact-revision formation consent, explicit governance ballots, live authorization, and factual execution evidence remain the governing contracts.

Local acceptance completed on 2026-10-30; supported-platform acceptance remains subject to CI, including the Windows native-output correction described below.

## Baseline and Evidence

Implementation started on 2026-10-29 from clean commit `c42c78b5d6f7276b2a43a9f8757908e2dab375cd`.

The baseline uses an independent Git source archive so current edits cannot change its test inputs or imported package.

The local environment is Python 3.13.17, macOS 27.0.1 on arm64, and SQLite 3.54.1.

Runtime dependency versions are Pydantic 2.13.5, typing-extensions 4.16.0, jsonschema 4.26.0, SQLAlchemy 2.1.2, and tokenizers 0.23.2.

Coverage 7.16.2, mypy 2.4.0, Ruff 0.16.10, and build 1.6.1 provide the local quality tools.

Source identity includes the base commit, dirty-checkout evidence where applicable, and a content digest of production, test fixtures, typecheck, examples, documentation, maintenance scripts, configuration, and CI inputs.

The digest includes the verification ledger and frozen manifests, while excluding caches, generated package metadata, this results page, and the retained acceptance records.

Generated evidence stays outside the source tree, and metadata records test selectors, outcomes, durations, environment, and workload parameters without assertion bodies or tool inputs.

## Work Sequence

1. Align current acceptance commands and map independently verifiable requirements to reviewed test assertions.
2. Record ordinary and instrumented baseline results separately.
3. Repair weak test inputs and add positive controls at high-risk authority boundaries.
4. Extend deterministic cross-mechanism tests using real domain transactions, barriers, and logical clocks.
5. Add bounded seeded schedules and independently runnable longer workloads, retaining reproducible operation traces.
6. Terminate real subprocesses at dispatch, result, file-publication, and recovery boundaries and verify subsequent evidence.
7. Repeat local acceptance for the final inputs and retain the supported operating-system and Python CI matrix as a separate evidenced gate.

## Acceptance Boundaries

Coverage mapping and execution status are separate facts.

A passing test name alone does not prove its claimed behavior; valid inputs, applicable profiles, meaningful assertions, and appropriate positive controls establish the mapped evidence.

Random seeds identify generated schedules, while barriers and operation traces identify the actual order exercised.

An interrupted external execution retains uncertainty and is not automatically replayed, polled, or reconnected.

Bounded queue and scheduling metadata are measured independently of deliberately retained business records.

Accepted local commits settle without an arbitrary persistence timeout, and observer watchdogs remain test diagnostics rather than production policy.

Passing local checks does not establish results for another Python version, operating system, or unexecuted extended workload.

## Results

### Baseline

The ordinary baseline run stalled during asynchronous test-loop cleanup with a memory-index worker still awaiting its queue and was interrupted for diagnosis.

It is an interrupted run, not a successful baseline, and the nonverbose log does not identify the exact triggering test.

The independent baseline's instrumented full suite passed 1,122 tests without skips in 1,103.771 seconds, with 84.71 percent combined statement and branch coverage, 88.11 percent statement coverage, and 75.72 percent branch coverage.

Baseline Ruff, source-distribution and wheel builds, isolated installed-wheel imports, both consumer mypy contracts, and all three offline examples passed.

An initial mypy invocation using `MYPYPATH` checked the framework as strict application source rather than an installed consumer dependency and failed; it is excluded from the consumer gate, which was rerun successfully against the installed baseline wheel.

The baseline commit's eleven GitHub checks were independently read and all succeeded, including its nine Python and operating-system combinations, quality checks, and wheel smoke test.

These historical CI results establish the baseline only.

### Corrections and Adversarial Coverage

A deterministic pre-fix regression reproduced a cooperative cancellation losing its race with a returned index result, allowing the memory worker to enter another queue wait after shutdown or restore suspension.

The indexing lifecycle now fences that next wait, releases undispatched queue bookkeeping while retaining pending segments, and makes concurrent flush observers report closure or suspension explicitly.

Regression tests cover shutdown, restore suspension, and a flush racing closure.

A second deterministic regression exposed a queued backlog being stranded when the optional mode was disabled during indexing.

Worker lifetime and model-work admission now have separate checks, so disabled indexing can release queue bookkeeping without creating cards and re-enabling resumes the retained segments.

The scope-dissolution test previously used obsolete publication arguments that could be rejected before reaching the authority check.

It now uses valid input, asserts the specific `scope_ended` denial, and has a matching successful live-scope control.

New shared-person tests exercise Native and Text ReAct under durable and volatile modes using the actual scheduler, with chat and governance mail arriving during an in-flight model request.

They verify one personal invocation owner, unchanged identity and memory, separate unread state, no implicit ballot from ordinary response text, and approval only after the explicit governance tool.

Additional tests check silent-member independence, retired round APIs, Full Jitter and model deadlines, recovery admission, configurable withdrawal validation, mixed send/edit quotas, old relationship generations, and unsupported schemas remaining byte-for-byte unchanged before DDL.

Real subprocess exits cover before dispatch, after dispatch, after observing an outcome, before committing a result, after committing a result, between library-directory swaps, and after a recovery notice is persisted but before activation.

Restoration retains uncertainty when required, rolls back interrupted directory publication, preserves committed results, issues one recovery notice, and does not replay external execution.

### Initial Local Acceptance

The initial acceptance input digest was `4c7ab5ff48203b797893e3dc4071e7e7476bcfa6e136bab0676a2a2abf83879a`.

| Gate | Result | Elapsed seconds |
| --- | --- | --- |
| Ordinary full suite | 1,155 passed; no skips or resource-leak warnings. | 588.217 |
| Frozen runtime specifications | 5 passed. | 5.590 |
| Extended reliability workloads | 3 passed with eight seeds and 96 operations per seed. | 43.089 |
| Instrumented full suite | 1,155 passed; 84.80 percent combined coverage. | 1,169.520 |

The ordinary, frozen, and extended runs share that digest and environment, and all 186 declared checks across 44 formal areas have passing test evidence from their 263 concrete selectors.

The aggregate passed with all four reports, matching inputs and environment, no skips, no detected resource-leak warnings, and no project-root DocLib.

The instrumented run measured 88.18 percent statement coverage and 75.86 percent branch coverage, retaining the existing 70 percent combined coverage threshold.

The extended workload exercised sixteen independently admitted people, forty-eight admission requests, one identity shared by eight teams, eight seeded histories totaling 768 generated schedule steps, and 1,536 distinct slow-writer updates.

The writer made eight commits with two completion handles, retained every accepted key, progressed through 192 event-loop heartbeat callbacks while held, and released its ownership lease after close.

The built wheel matched all 284 production modules, imported from an isolated installation outside the checkout, and passed Native activity, Text ReAct activity, background result inspection, both consumer mypy contracts, and the four memory-index lifecycle regressions.

The isolated wheel environment reused the development environment's dependency distributions through a read-only search path while verifying that ATT itself came from the installed wheel.

Ruff and consumer mypy passed locally, and the CI workflow parsed successfully with its existing nine-entry full-suite matrix plus three extended reliability jobs.

A review found that the first source fingerprint omitted documentation and JSON fixtures, so its coverage run was explicitly interrupted.

Profiles predating the completed fingerprint, backlog, and warning-filter corrections are excluded from the final aggregate.

The fingerprint now includes documentation, fixtures, and frozen manifests, with regression assertions for their changes, while generated acceptance results remain excluded.

The acceptance runner also explicitly enables the ordinary unittest warning filter, with a subprocess regression proving that a successful test emitting `ResourceWarning` cannot produce a passing acceptance report.

The [machine-readable acceptance record](acceptance/2026-10-30.json) retains the environment, source identity, profile outcomes, baseline checks, coverage totals, distribution hashes, and all 186 check outcomes.

It records report hashes and numeric metrics while raw logs, coverage data, per-test run reports, and generated HTML remain in the external evidence directory.

Elapsed times describe these specific executions; the instrumented and ordinary runs are not controlled performance comparisons.

### Output Capture and Evidence Validation

The subsequent executor changes capture operating-system descriptors 1 and 2, preserve an independent console destination, and flush native stdio before restoring the original streams.

Native writes, inherited subprocess output, and binary log bytes remain in the raw log while JSON stdout stays parseable.

Resource counters now record actual Python warnings, unraisable warning exceptions, and standard asyncio exception events rather than interpreting diagnostic words in ordinary output.

Context-inheriting Python children use per-process event files, with existing startup customization and explicit warning filters retained.

The observer keeps its active context independently of a test changing its environment, and nested diagnostic scopes retain separate ownership.

Aggregation checks complete test statistics, individual outcomes, durations, environment identity, and diagnostic counters, then reconciles full-run coverage percentages, branch counts, repository policy, and the retained measurement hash.

CI runs complete tests with unfiltered output and retains raw logs, typed events, and coverage measurements as artifacts.

The updated acceptance input digest is `f716dde65d7391866961a4d70133eadefe637fd7acafbccc863e4bb57e870c36`.

| Gate | Result | Elapsed seconds |
| --- | --- | --- |
| Ordinary full suite | 1,189 passed. | 619.774 |
| Instrumented full suite | 1,189 passed; 84.83 percent combined coverage. | 1,123.968 |
| Frozen runtime specifications | 5 passed. | 5.776 |
| Extended reliability workloads | 3 passed with eight seeds and 96 operations per seed. | 43.535 |

All four reports share the updated source digest and environment, with no skips, detected resource-leak diagnostics, or project-root DocLib.

Aggregation passed all 186 declared checks after validating the individual outcomes and reconciling the coverage measurement with its artifact hash and the repository's 70 percent threshold.

The updated instrumented run measured 88.21 percent statement coverage and 75.90 percent branch coverage.

The focused executor and frozen-artifact checks passed 51 tests, documentation contracts passed 21 tests, and Ruff, both consumer mypy contracts, distribution building, and installed-wheel verification passed.

The [updated machine-readable acceptance record](acceptance/2026-10-30-output-validation.json) retains these fresh results and references the unchanged initial record.

Raw logs, typed diagnostic events, complete run reports, and coverage measurements remain in the external evidence directory.

### Platform Gate

The supported CI matrix remains Python 3.11, 3.12, and 3.13 on Linux, macOS, and Windows.

The new workflow runs full-suite evidence on all nine combinations and extended reliability on Python 3.13 for all three systems.

The committed Phase 8 changes reached CI, where the Windows full-suite jobs failed in the buffered native-output fixture.

That fixture assumed that `ucrtbase.dll` directly exports `printf`, which Windows does not guarantee.

The corrected probe uses declared CRT functions with a separately owned, fully buffered stream, verifies pending data before capture exits, and checks that it was flushed before `fclose` can flush it implicitly.

Unexpected positive-fixture exits now include their retained child report, stdout, stderr, and raw log in the assertion diagnostics.

The focused correction checks include native-buffer retention, unexpected child-failure diagnostics, and CRLF text normalization while preserving original log bytes.

A negative control confirmed that disabling native flushing makes the buffering regression fail before stream closure.

A fresh Windows CI run is still required to verify the correction on Python 3.11, 3.12, and 3.13.

Schema remains `16`, optional episodic memory remains disabled by default, and the runtime does not acquire the authority of formation, governance, communication, migration, failover, or supervision mechanisms.
