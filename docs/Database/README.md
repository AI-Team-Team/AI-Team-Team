# ATT Database Architecture

ATT stores accepted identities, relationships, personal activity, execution facts, and institutional decisions in a versioned SQLite checkpoint.

This section describes the implemented database as a complete system rather than successive schema extensions.

The current schema version is `16`.

Unsupported versions and layouts are rejected before writable connections or schema changes, without migration or compatibility loading.

## Documents

| Document | Responsibility |
| --- | --- |
| [Current Schema](Schema.md) | All current table groups, identity references, ordering, and relational constraints. |
| [Relational Constraints](Relational_Constraints.md) | Exact primary/unique keys, partial indexes, cross-row authority, delete actions, and dependency order. |
| [SQL Reference](Schema.sql) | Complete schema 16 column, check, foreign-key, unique-key, and index declarations. |
| [Request and Token States](Request_and_Token_States.md) | Shared ordinary/audit/index request matrices, token settlement, presentation evidence, and interruption handling. |
| [Ownership and Evidence](Ownership_and_Evidence.md) | Ordinary identities, temporary audits, private data, historical authority, and runtime-only bindings. |
| [Transactions and Validation](Transactions_and_Validation.md) | Immutable capture, dependency closure, writer ownership, exact receipts, cancellation, and validation reuse. |
| [Recovery and Publication](Recovery_and_Publication.md) | Detached validation, file publication, rollback, interruption settlement, countdowns, and activation. |

For public save/load usage, see [State Persistence](../State_Persistence.md).

For scheduling and invocation boundaries, see [Autonomous Agent Runtime Architecture](../Autonomous_Agent_Runtime_Architecture/README.md).

For executable correctness requirements and measured evidence, see [Verification](../dev/verification/README.md).

## Implementation Map

The [model package](../../src/ai_team_team/database/models/) declares the physical tables, checks, foreign keys, and indexes.

The [persistence package](../../src/ai_team_team/database/persistence/) owns SQLite connections, immutable records, writer coordination, schema preflight, and publication reconciliation.

The [restore service](../../src/ai_team_team/core/manager/restore/) prepares a detached manager and publishes an accepted runtime generation.

Domain services retain responsibility for authorization and business-specific decisions; a successful database write cannot supply missing consent or a ballot.
