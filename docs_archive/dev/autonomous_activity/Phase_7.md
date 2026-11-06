# Phase 7: Documentation and Public Contracts

Phase 7 documents the runtime implemented in Phases 1 through 6 and replaces obsolete consumer examples.

It changes no institutional authority, Agent identity semantics, runtime policy, or database schema.

Governance, Team Formation, communication, migration, resource decisions, and supervision retain their own cases, consent, ballots, authorization, and domain transactions.

## User-Facing Contracts

| Guide | Contract |
| --- | --- |
| [Quickstart](../../user/Quickstart.md) | Complete offline Native and Text examples, explicit idle, stable model bindings, durable save, and reacquisition of restored Python objects. |
| [Public API Reference](../../user/API_Reference.md) | Current configuration defaults, nested activity and provider policies, result-model fields, and separate Host and model-tool signatures. |
| [Personal Activity](../../Personal_Activity.md) | Personal admission, captured scope, explicit controls, fair checkpoints, resource availability, sleep, suppression, lifecycle, and optional memory. |
| [Personal Conversations](../../Personal_Conversations.md) | Deliberate publication, Markdown titles, bounded previews, explicit reads, revisions, withdrawal, contact controls, relationship generations, and frozen departure archives. |
| [Background Tasks](../../Background_Tasks.md) | Affirmative registration, one-execution detachment, canonical resources, serialized overwrites, independent task dimensions, live authorization, results, cooldowns, and factual external controls. |

README retains its philosophy and main architecture diagram while linking the current usage guides.

Related governance, formation, delegation, persistence, tool, supervision, discovery, and object-model documents receive localized contract corrections and navigation updates.

The preliminary asynchronous proposal is preserved in the [design archive](../../../docs_archive/README.md), with a brief evolution note linking to current contracts and explaining the separation between execution and institutional authority.

## Source and Consumer Boundaries

`core.activity.contracts.ActivityRuntimeAPI` describes the implemented Host surface without exposing executor state or private runtime objects.

`typecheck/activity_contract.py` checks admission and delivery result types, task dimensions, and current Host call signatures alongside `typecheck/consumer_contract.py`.

The [documentation-contract tests](../../../test/test_att/test_documentation_contracts/) compare API tables with configuration and result models, inspect actual model-tool signatures, validate current navigation, and execute declared complete Markdown examples.

Complete runnable fences carry an `<!-- runnable: examples/name.py -->` marker and match the checked-in example file exactly.

Other examples explicitly describe their prerequisites and remain integration fragments rather than pretending to be complete applications.

The examples use scripted local clients, temporary workspaces, explicit stable aliases, and no credentials or external provider requests.

The background example uses an asynchronous observer to signal an asyncio Event; synchronous callbacks execute in background threads and must use thread-safe handoff when notifying an event loop.

CI executes the three example variants against the installed wheel from outside the checkout and verifies the imported package's installation origin.

## Verification Scope

Current public schema claims remain 16, and historical schema profiles keep their original numbers.

The machine-readable replacement inventory continues to exclude blueprint text and its own engineering directory.

Local documentation acceptance completed on 2026-10-26 with Python 3.13.17 on macOS.

- `./venv/bin/python -m unittest discover -s test`: 1122 tests passed in 557.856 seconds without skips.
- The 21 documentation-contract tests passed, including exact runnable Markdown, Native and Text examples, background attention handling, configuration defaults, result fields, current tool signatures, navigation, and performance-test references.
- All 35 ordinary contract-freeze checks and the five separately invoked frozen runtime specifications passed.
- The asynchronous test example in the development guide was executed with its actual repository fixture and passed.
- Ruff over `src test typecheck examples` and both public consumer mypy contracts passed.
- Source-distribution and wheel builds passed with installed build dependencies and `--no-isolation`.
- The two checked-in example sources are included in the source distribution.
- Installed-wheel examples passed outside the checkout for Native, Text ReAct, and background execution, with package-origin checks and no external provider calls.
- All 284 Python source modules matched the wheel, and the README main Mermaid diagram remained byte-identical to its pre-phase version.
- Tests left no project-root `.att_doc_libs`, and the full-suite log contained no unhandled-task, unawaited-coroutine, or resource-leak warnings.

Phase 8 retains randomized interleavings, longer stress workloads, branch-coverage acceptance, and the supported Python and operating-system matrix.
