# Schema 14: Registered Execution Evidence

Schema 14 extends the conversation and durable-record foundations and rejects schema 13 and earlier before writable connections or DDL, without migration.

No new record groups are introduced; execution foundations become authoritative producers.

## Execution Additions

`executions` adds nullable `call_id`, `contract_snapshot`, `metadata`, `source_references`, `started_at`, and `finished_at` fields.

Replacement-service executions require a concrete call identity, immutable executor/effect declaration, description and labels, explicit Host or model origin, and protected source provenance.

Host-origin executions may have a null `invocation_id` only with their explicit admission evidence and committed input reference.

Model-origin executions retain the actual personal invocation and its exact scope, owner, and generation.

Coordinated foreground operations also produce captured contracts, inputs, attempts, terminal results, and observation references without gaining background permission.

Nullable extension columns still accommodate the explicitly invocation-backed foundation records used by the durability contracts, rather than grant undeclared background execution.

Captured authority, metadata, and source provenance cannot be rewritten by later deltas.

Confirmed start and finish timestamps cannot change, terminal outcomes cannot reverse, and background visibility cannot revert to foreground.

## Protected Inputs and Results

`execution_payloads` has a unique `(execution_id, content_kind)` constraint in addition to immutable payload identity.

`execution_observations` adds a positive per-execution `observation_index` with unique `(execution_id, observation_index)` ordering so identical or adjusted wall-clock timestamps cannot reorder health evidence after restore.

New execution payloads carry canonical content digests and owner-matching references.

The input commits with execution admission before dispatch, and the final result commits with outcome, attention, and addressed notification.

Transient payloads retain factual metadata without a body and never authorize automatic rereading after restore.

Source provenance supports restrictive retained-result access after restore without serializing runtime authorizers or borrowing a later team scope.

Working Context and Journal source-execution references capture their concrete execution evidence and insert-only identity and library prerequisites in first partial checkpoints.

## Validation and Recovery

Both transactional SQL and detached restore validate declaration snapshots, Host/model origin, original scope, source references, private ownership, payload digests, and execution timing.

Queued and running records survive interruption as last-confirmed facts with separate uncertainty rather than fabricated terminal outcomes or freshly verified live tasks.

Historical executors and external handles are evidence only, and no tool or executor binding is required merely to read a previously retained result.

The existing writer lease, exact receipts, coalesced pending delta, WAL, foreign keys, busy timeout, and all-or-nothing publication contracts remain unchanged.
