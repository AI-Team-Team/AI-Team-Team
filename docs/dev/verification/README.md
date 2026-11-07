# Framework Verification

ATT verifies current behavior through ordinary functional tests, independently runnable reliability workloads, and measured acceptance evidence.

These are framework correctness requirements rather than acceptance criteria for the AIs' business work.

## Requirements and Behavioral Evidence

- [Verification Matrix](Verification_Matrix.md) lists the required adversarial boundaries by domain.
- [Verification Coverage](Verification_Coverage.md) maps independently reviewable requirements to exact behavioral tests.
- [Current Contract Traceability](Contract_Traceability.md) connects each behavioral requirement to specific explanatory headings and implementation entry points.
- [Archive Integration](Archive_Integration.md) explains where frozen engineering rules and confirmed blueprint decisions are maintained, and which descriptions remain historical or deferred.
- [Machine-readable ledger](verification_cases.json) supplies stable check identities, maintained selectors, and current source locations.
- [Machine-readable documentation routes](documentation_cases.json) retain the current heading and implementation references for each behavioral requirement.
- [Test Development Guide](../testing.md) defines fixtures, mocking, cancellation observers, isolation, and maintenance commands.
- [Performance Measurement](../Performance_Measurement.md) separates controlled timings and SQL work from correctness claims.

A declared selector is not execution evidence, and passing one test does not prove every schedule or platform.

Review the actual assertions, applicable protocol/durability modes, valid input, and positive controls at authority boundaries.

One matrix row or ledger entry may contain several clauses, so a passing selector does not establish coverage for every clause in that row.

Demonstrated implementation differences are tracked in the [known-issues list](../../../todo.md#known-issues).

## Default Discovery

`test/test_att/test_runtime_contracts/` contains strict value contracts, identity invariants, controlled fixtures, and all five continuing-runtime specification scenarios.

`test/test_att/test_state_integrity/` contains immutable records, receipts, current physical schema, authoritative references, publication, leases, and recovery boundaries.

All five scenarios run exactly once in ordinary `unittest discover`, with individual package/module/method selection still available.

There is no separate phase-only discovery requirement or legacy acceptance profile.

The maintained [tool-effect manifest](../../../test/contracts/tool_effects.json) checks every built-in declaration, including optional-memory tools, without granting execution authority by itself.

## Acceptance Profiles

The `full` profile discovers the complete ordinary suite, and the `extended` profile runs the seeded schedules, many-owner admission, and controlled slow-writer pressure.

Use fresh directories outside the checkout:

```bash
./venv/bin/python -m scripts.acceptance --coverage --output /tmp/att-acceptance/full
./venv/bin/python -m scripts.acceptance --suite extended --seeds 8 --operations 96 --output /tmp/att-acceptance/extended
./venv/bin/python -m scripts.acceptance.summary --output /tmp/att-acceptance/summary.json /tmp/att-acceptance/full/result.json /tmp/att-acceptance/extended/result.json
```

Windows users select equivalent external paths and their virtual environment's `Scripts/python.exe`.

Aggregation requires passing full and extended evidence for the same current source digest and environment, with measured branch-enabled full-suite coverage against repository policy.

Reports retain complete per-test identities, outcomes, durations, environment, typed resource-diagnostic counters, and safe workload traces.

Coverage totals must reconcile with `coverage.json` and its recorded hash; a success flag alone is insufficient.

Skipped, incomplete, mixed-environment, stale-source, missing-ledger, and contradictory results fail acceptance.

The ordinary suite and CI retain schema corruption, real process exits, cancellation, ACL revocation, privacy, and generation-fencing coverage.

## Platform and Packaging Gates

CI runs full-suite evidence on Python 3.11, 3.12, and 3.13 across Linux, macOS, and Windows.

Extended reliability runs on Python 3.13 across all three systems, and the Ubuntu Python 3.13 full suite measures coverage.

Ruff, both consumer mypy contracts, distribution builds, and installed-wheel Native/Text/background examples remain separate quality gates.

Installed examples run outside the checkout with verified package origin and explicit stable model bindings.

Each measured workload records its own source, environment, parameters, and instrumentation, with no inference of a cross-platform timing guarantee.

## Historical Records

The [historical archive](../../../docs_archive/README.md) retains original designs, implementation reports, and past acceptance records unchanged.

Those records describe their original source inputs and test selectors rather than substitute for a run of the current tree.

The [organization snapshot](../../../docs_archive/snapshots/2026-11-02-document-organization.json) records the unchanged source-to-archive transfer.

The [documentation closeout record](../../../docs_archive/snapshots/2026-11-02-document-closeout.json) records functional test relocation, retired migration-only checks, and verification of the reorganized sources.

Historical migration inventories are retained there while continuing functional regressions remain active.

The earlier section-disposition snapshot and closeout run retain their original broad mappings and source identity; current rule-level review uses the maintained contract routes above.
