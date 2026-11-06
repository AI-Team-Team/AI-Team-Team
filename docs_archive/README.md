# Historical Design and Development Documents

This directory preserves earlier ATT design proposals, implementation records, and acceptance evidence.

Archived documents may contain superseded mechanisms, unimplemented ideas, or status descriptions from the time they were written.

They preserve design history and do not define current APIs, permissions, or runtime behavior.

## Design Records

| Document | Purpose |
| --- | --- |
| [Asynchronous and Event-Driven Agent Collaboration](Async_Event_Driven_Collaboration.md) | The original conceptual proposal, preserved unchanged. |
| [Evolution of Asynchronous Collaboration](Async_Event_Driven_Collaboration_Evolution.md) | A brief explanation of how the proposal evolved into continuing personal activity, explicit messaging, and registered execution. |

## Autonomous Activity Development Snapshot

The 2026-11-02 snapshot preserves the original contents of these development sources:

| Original location | Archived location |
| --- | --- |
| `docs/dev/autonomous_activity/` | [Engineering contracts, schema extensions, and phase records](dev/autonomous_activity/README.md) |
| `docs/blueprints/` | [Design blueprints, implementation plan, and deferred proposals](blueprints/README.md) |
| Root `todo.md` | [Original Todo](todo.md) |

The [snapshot manifest](snapshots/2026-11-02-document-organization.json) records the source commit, original paths, file sizes, and SHA-256 hashes.

The [section disposition record](snapshots/2026-11-02-document-disposition.json) accounts for all 68 copied document/data files and 340 Markdown sections, including current destinations, historical evidence, and deferred research.

The [closeout record](snapshots/2026-11-02-document-closeout.json) records test relocation, reviewed retirements, and fresh verification against the reorganized source inputs.

The runtime topic directory was subsequently renamed from `docs/Runtime_Architecture/` to [Autonomous Agent Runtime Architecture](../docs/Autonomous_Agent_Runtime_Architecture/README.md).

Historical disposition and closeout records retain the paths and source identities used when they were recorded.

The current [archive integration guide](../docs/dev/verification/Archive_Integration.md) and [rule-level traceability](../docs/dev/verification/Contract_Traceability.md) provide specific canonical destinations and implementation references beyond the original broad disposition list.

The [2026-11-04 documentation-contract record](snapshots/2026-11-04-document-contract-completion.json) records the subsequent content corrections, exact engineering references, and fresh validation against their own source inputs.

The copied documents retain their original wording and relative links, including references that no longer resolve from the archive location.

Use this index to navigate the historical files and the [current documentation](../docs/README.md) for implemented behavior, APIs, and integration.

Current normative documentation and maintained verification artifacts are organized by function rather than implementation phase.
