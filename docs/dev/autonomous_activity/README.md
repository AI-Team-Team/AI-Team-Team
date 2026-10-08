# Autonomous Activity: Phase 0 Contract Freeze

## Status

Phase 0 implements value contracts, a dependency inventory, deterministic adversarial fixtures, and an explicitly red runtime specification suite.

It does not implement the replacement scheduler, change existing runtime behavior, activate schema 12, or claim that later-phase acceptance tests pass.

The governing local blueprint and implementation plan, including the confirmations recorded on 2026-10-07, remain authoritative.

This tracked directory preserves their engineering interpretation so the contract freeze is available outside the ignored `local/` directory.

All D01 through D15 decisions remain confirmed, and no institution is reopened by these specifications.

The target schema is frozen as `12`, while the running implementation continues using schema `11` until Phase 1 implements its incompatible replacement.

## Deliverables

- [Engineering contracts](Contracts.md): scope, intent, presentation, effects, admission, and cancellation boundaries.
- [Schema 12](Schema_12.md): relational groups, reference constraints, ordering, and publication protocol.
- [Replacement inventory](Replacement_Inventory.md): ownership and disposition of round-dependent code and documentation.
- [Machine-readable line inventory](round_dependencies.json): every selected source occurrence, including exports, tests, callbacks, diagrams, and examples.
- [Built-in effect declarations](tool_effects.json): the reviewed target registration contracts, not permissions already installed in `Tool`.
- [Contract models](../../../src/ai_team_team/core/activity/contracts/__init__.py): strict immutable values and a host-facing Protocol without an execution engine.
- [Fixtures and specifications](../../../test/test_att/test_autonomous_activity_phase0): real Manager identity checks and controlled model, clock, executor, commit, and publication boundaries.

## Green and Red Checks

Run the implemented Phase 0 checks with:

```bash
./venv/bin/python -m unittest discover -s test/test_att/test_autonomous_activity_phase0 -t .
./venv/bin/mypy typecheck/consumer_contract.py typecheck/activity_contract.py
./venv/bin/ruff check src test typecheck
```

Run the intentionally failing replacement specifications separately:

```bash
./venv/bin/python -m unittest discover -s test/test_att/test_autonomous_activity_phase0 -t . -p 'spec_*.py'
```

The six red specifications target the real `ATTManager`, assert missing prerequisites explicitly, and contain the subsequent behavioral assertions that later phases must satisfy.

Runtime cleanup also rejects scripted-client requests whose exceptions were swallowed, and coalescing checks the preserved scope and complete request count.

The background specification validates a structured durable handle and its later owner-facing completion notice rather than accepting the old handle as evidence of a new notification.

The schema specification reads a real committed database, requires every frozen new or replacement table, rejects retired tables and provenance columns, and checks foreign-key integrity after the target version is implemented.

They cover default continuation without automatic publication, shared-person admission coalescing, idle-mail activation without inferred read state, next-frame notification during a tool wait, one-execution Native detachment, and activation of the physical schema target.

They do not call old discussion APIs, use a fake replacement runtime, skip missing features, or convert missing implementation into `expectedFailure` success.

Their `spec_*.py` filenames deliberately keep an unfinished architecture's red gate separate from the current `test_*.py` regression suite.

Phase 0 completion requires that the green checks pass and that each red failure identifies an unimplemented contract rather than an import error, broken fixture, leaked task, or accidental external request.

Later phases must run this red gate explicitly and move each completed specification into ordinary discovery when its required runtime and dependencies are implemented.

A passing baseline is not evidence that the red specifications or the new architecture pass.

## Fixture Boundaries

`ScriptedModelClient` accepts the actual provider-neutral `List[Tool]` contract, captures isolated request frames, exposes in-flight overlap, and rejects unscripted requests.

Its exact generation signature rejects unknown keywords, and unscripted attempts remain observable even if a caller catches their exceptions.

`LogicalClock` advances only on explicit test instructions, supports independent restart clocks, and removes cancelled timer waits.

`ControlledExecutor` records one side-effect dispatch and distinguishes a request to cancel from acknowledgement or a completed result.

It cannot fabricate completion before an executor dispatch.

`ControlledCommitter` captures the accepted delta and exposes exact receipt success or failure without pretending to write SQLite.

`PublicationFaults` names preflight, staging, manifest, file, durable recovery, synchronous runtime, and pre-dispatch boundaries without introducing test-only branches into production code.

`AgentIdentitySnapshot` reads every present Agent attribute without creating lazy locks, detects replacement of equal containers, and includes private artifact hashes rather than body text.

Its string and byte evidence is hashed so an assertion's failure representation does not print personal content, and symbolic links are recorded without reading their targets.

These fixtures prove control and observation behavior, not the safety of a production executor or the atomicity of a future restore algorithm.

Actual publication rollback, schema corruption, worker fencing, and process-crash tests remain required in Phase 1 and subsequent gates.

No fixture waits two real minutes or creates storage in the repository root.
