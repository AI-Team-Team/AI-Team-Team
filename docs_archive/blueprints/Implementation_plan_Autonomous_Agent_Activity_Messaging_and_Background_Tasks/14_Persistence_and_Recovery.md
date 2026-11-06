# 14. Persistence Schema, Checkpoints, and Recovery

[Back to plan index](README.md).

## 14.1 Proposed schema groups

| Record group | Required information and constraints |
| --- | --- |
| Activity and request evidence | One personal marker per continuing Agent, invocation and request IDs, scope, context version, factual dispatch, and token-accounting references. |
| Notifications and frames | Addressed owner, typed source reference, trusted classification, stable deduplication identity, distinct claim and presentation evidence, and bounded authorized reminder previews preserved independently of later source withdrawal. |
| Team conversation | Stable message identity, append-only Markdown revisions, author provenance, ordered publication, view-relative withdrawal evidence, and operation idempotency. |
| Membership history | Agent and team identities, ordered non-overlapping intervals, at most one open relation, and immutable authorized departure-view references. |
| Team lifecycle and organization | Active or dissolved lifecycle, retained creator provenance, an explicit optional Agent or AgentTeam parent, historical topology evidence, reattachment acceptance references, voluntary or parent-loss detachment provenance, and no implicit Root substitution for a missing parent. |
| Direct conversation | Canonical pair, versioned source messages, per-person read state and personal deletion, and sender provenance. |
| Personal relationships | Bilateral friendship, separately owned blocks and refusal, requests, generations, and atomic directional allowances. |
| Presentation preferences | Per-person detail controls, personal message deletion, and explicit read or unread state without replacing source records. |
| Sleep and do-not-disturb | Sleep's mandatory finite safeguard, remaining countdowns, permanent or timed notification suppression, per-person scope, and applicable expiration evidence. |
| Executions and attempts | Owner, original scope, operation identity, declared effects, protected inputs or results, five execution states, and attempt facts. |
| Tool availability | Per-Agent and per-tool cooldown evidence, remaining duration or deadline, downtime-accounting mode, and reasons, with shared-service protection separately configured. |
| Model availability and retry evidence | Dispatched attempts, per-model timeout, whole-sequence budget, recovery-admission boundary, provider earliest-retry instructions, and uncertainty without changing personal activity intent. |
| Health and attention | Supported observations, independent health and attention dimensions, cancellation requests and acknowledgements, and uncertainty annotations. |
| Governance cases | Frozen electorate, exact schema, explicit immutable ballots, revision, authoritative state, endpoint-specific independence exemptions, required-principal derivation evidence, and business references without discussion rounds. |
| Health incidents and audit evidence | Stable fingerprints, counts and timestamps, permitted evidence references, explicit acknowledgement, and ephemeral identity snapshots. |
| Recovery and publication evidence | Source checkpoint identity, interruption incident identities, prepared publication state, protected notices, and runtime generations. |

Maintain the existing identity, library ownership, configuration, communication Agreement, formation-revision, migration, Journal, and optional catalog data with updated provenance.

The exact physical table split is an implementation design, not a requirement to create one table for every conceptual field group.

Use database checks, uniqueness, foreign keys, and restore validation together rather than relying only on Pydantic objects.

## 14.2 Writer and snapshot integration

Extend dirty records, immutable capture, dependency closure, writer order, full snapshots, readers, and restore validators for each new domain.

Do not serialize live executors or read mutable runtime objects from the persistence worker.

Keep one executing write and one mergeable pending delta rather than accumulate unbounded Futures.

Append-only source records, ballots, attempts, and observations merge by stable identity, while mutable projections merge by state version.

Deletion and retained-history rules must prevent later stale deltas from resurrecting an object or erasing required evidence.

Foreign-key dependency capture must include all newly referenced Agents, teams, libraries, source messages, requests, and historical identities.

Insert-only dependencies must not rewrite another person's window or unrelated existing entities.

Authoritative receipts acknowledge the required domain state, not an unrelated full flush.

Check the supported schema before any DDL, keep exclusive writer leases, and retain foreign keys, WAL, busy timeout, and strict error propagation.

## 14.3 Restore transaction

1. Acquire the target writer lease and restore admission gate, flush accepted current commits, and reject unsafe surviving mutators.
2. Record restoration start for countdown anchoring, then read and validate a supported checkpoint without external execution.
3. Build detached staging state, staged DocLib contents, frozen departure views, and all required historical access projections without scheduling activity.
4. Derive interruption annotations and protected notification records from committed evidence rather than inspect external services.
5. Prepare a recoverable publication manifest linking the source checkpoint, staged files, annotation transaction, and intended runtime generation.
6. Prepare or publish the staged DocLib generation behind the managed-resource publication gate while public registry projections still reference the old published runtime.
7. Complete the required recovery-record and publication-manifest transaction, then switch the validated runtime in one synchronous publication step without an intervening `await` or observer dispatch.
8. If a pre-completion step fails in the live process, roll back the runtime, directories, staged authoritative additions, and timer admission without changing the original manager.
9. After publication succeeds, admit affected identities once, arm unaffected sleep rules, and resume only permitted internal domain bookkeeping.

SQLite and multiple filesystem renames do not form one atomic operating-system instruction, so crash behavior requires a publication journal or equivalent recoverable generation protocol rather than an unsupported atomicity claim.

Provisional recovery records must not be deliverable before their publication is complete.

Managed resource reads remain gated while file materialization is provisional, and synchronous directory projections continue to see the last completely published registry snapshot.

No new runtime registry becomes publicly visible while a required persistence receipt is still awaited.

If final runtime publication itself fails after durable preparation, the manifest and staged additions need explicit rollback or fail-closed reconciliation before gates are released.

A subsequent start reconciles an incomplete publication before allowing model activity, using authoritative checkpoint and manifest evidence rather than uncertain loose files.

The detailed manifest algorithm must pass the fault-injection gate in Phase 1 before it is used by later features.

## 14.4 Recovery activation matrix

| Latest committed evidence | Required post-publication behavior |
| --- | --- |
| The person was continuing or active. | Admit the same person's activity with a protected interruption summary. |
| An owned execution was affected while its owner was active, idle, or asleep. | Admit the same owner with evidence references and last-confirmed execution facts. |
| The person slept without affected execution or another protected notice. | Preserve sleep and resume its remaining countdowns. |
| Only confirmed historical terminal executions remain. | Preserve history without inventing an interruption or restart-only activation. |
| The Agent is inactive, dead, or physically deleted. | Preserve applicable evidence without silently reactivating or reconstructing the person. |

Use stable source-checkpoint and affected-attempt incident identities rather than a new notice identity on every repeated load.

Recovery activates the person, not the old external operation.

It may prepare a new personal model request to explain the incident after publication, but does not replay the earlier tool, poll an external handle, or reconnect an executor.

## 14.5 Last-confirmed facts

- Preserve confirmed completed, failed, and meaningfully acknowledged cancelled outcomes.
- Preserve queued evidence without automatically launching the previously admitted external operation.
- Preserve historical running evidence with an explicit current-outcome-unconfirmed annotation.
- Preserve cancellation requests without manufacturing cancellation acknowledgements.
- Preserve external operation IDs for deliberate owner investigation only.
- Keep uncertain records out of freshly verified running counts and include them in an explicit uncertainty summary.
- Keep rereading a notice separate from replaying publication, voting, relationship decisions, or execution.

An owner deliberately requesting another execution creates a distinct admitted execution and retains the old uncertain attempt.

The ordinary retry policy of an execution currently running in the live runtime is not replaced by the prohibition on automatic recovery replay.

## 14.6 Corruption validation

Validate ownership, lifecycle, alias availability, Root identity, explicit optional organizational parents, retained creator provenance, scopes, membership interval ordering, frozen-view cutoffs and revision references, source references, message authorship, read markers, retained reminder previews, relationship generations, stranger accounting, sleep plans, permanent or timed suppression, cooldown accounting, model-recovery boundaries, task transitions, ballots, retained identities, and publication manifests.

Reject missing or contradictory references rather than interpreting them as ordinary interruption uncertainty.

Inactive and retained dead identities do not require live model bindings, while active identities retain strict binding validation and the current Root must remain active under the confirmed lifecycle protection.

A surviving team's historical Agent creator may reference an inactive or retained dead identity rather than requiring that creator to remain active forever.

Validate a current parent as current organizational authority separately from historical creation provenance, and do not interpret a null parent as missing mandatory Root data.

Validate explicit parent-loss detachment and retained archive references, and reject a supposedly current parent reference to a dead Agent or dissolved AgentTeam rather than silently repairing it during restore.

Validate that independent-side exemption evidence does not replace a non-independent side's required ballots or manufacture an approved decision for an exempt side.

Validate reattachment acceptance against its exact target and attaching team, and distinguish a permitted voluntary detachment from a parent-loss transition rather than interpreting either as arbitrary missing-parent data.

Do not auto-create missing private libraries or historical identities in staging to hide a corrupt database.
