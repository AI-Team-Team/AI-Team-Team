# Autonomous Activity: Contract Freeze and Durability Foundations

## Status

Phase 0 implements value contracts, a dependency inventory, deterministic adversarial fixtures, and an explicitly red runtime specification suite.

Phase 1 adds the [durability foundations](Phase_1.md), activates schema 12, and makes durable versus volatile operation explicit without implementing the replacement scheduler or claiming later-phase acceptance.

The governing [blueprint](../../blueprints/Autonomous_Agent_Activity_Messaging_and_Background_Tasks/README.md) and [implementation plan](../../blueprints/Implementation_plan_Autonomous_Agent_Activity_Messaging_and_Background_Tasks/README.md), including the confirmed decisions recorded on 2026-10-07, remain authoritative.

This directory records their engineering contracts and phase-specific verification artifacts.

All D01 through D15 decisions remain confirmed, and no institution is reopened by these specifications.

The running persistence schema is now `12`; schema 11 and earlier are rejected without migration.

## Deliverables

- [Engineering contracts](Contracts.md): scope, intent, presentation, effects, admission, and cancellation boundaries.
- [Schema 12](Schema_12.md): relational groups, reference constraints, ordering, and publication protocol.
- [Replacement inventory](Replacement_Inventory.md): ownership and disposition of round-dependent code and documentation.
- [Machine-readable line inventory](round_dependencies.json): every selected source occurrence, including exports, tests, callbacks, diagrams, and examples.
- [Built-in effect declarations](tool_effects.json): the reviewed target registration contracts, not permissions already installed in `Tool`.
- [Contract models](../../../src/ai_team_team/core/activity/contracts/__init__.py): strict immutable values and a host-facing Protocol without an execution engine.
- [Fixtures and specifications](../../../test/test_att/test_autonomous_activity_phase0): real Manager identity checks and controlled model, clock, executor, commit, and publication boundaries.
- [Phase 1 implementation](Phase_1.md): immutable durable records, exact receipts, recoverable publication, mutation leases, and the scope of the initial recovery plan.

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

Five remaining red specifications target the real `ATTManager`, assert missing prerequisites explicitly, and contain the subsequent behavioral assertions that later phases must satisfy.

Runtime cleanup also rejects scripted-client requests whose exceptions were swallowed, and coalescing checks the preserved scope and complete request count.

The background specification validates a structured durable handle and its later owner-facing completion notice rather than accepting the old handle as evidence of a new notification.

The completed schema specification is now in ordinary [Phase 1 discovery](../../../test/test_att/test_autonomous_activity_phase1/test_schema_activation.py), requiring every frozen new or replacement table, rejecting retired tables and provenance columns, and checking foreign-key integrity.

The remaining red specifications cover default continuation without automatic publication, shared-person admission coalescing, idle-mail activation without inferred read state, next-frame notification during a tool wait, and one-execution Native detachment.

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

Actual publication rollback, schema corruption, worker fencing, and process-crash tests now run in the [Phase 1 package](../../../test/test_att/test_autonomous_activity_phase1), with later phases extending the same boundaries.

No fixture waits two real minutes or creates storage in the repository root.
