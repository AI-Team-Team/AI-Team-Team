# Round-Dependent Replacement Inventory

## Coverage

[round_dependencies.json](round_dependencies.json) contains a deterministic file-and-line inventory over `src`, `test`, `typecheck`, `docs`, `README.md`, `Roadmap`, `.github`, and `pyproject.toml`.

It selects discussion APIs/results, governance solicitation identities, round/turn provenance, session controls, configuration, personal execution, transcript publication, callbacks, parallel collection, and round-oriented prose.

Comments and historical tests are intentionally included rather than treated as production authority.

The inventory is overinclusive, and a selected callback, transcript word, technical memory exchange, or auto-save helper must be reviewed by responsibility rather than blindly deleted.

Parallel collection is inventoried because an all-member gather can form a barrier, while Native tool batches, writer receipt collection, and shutdown cleanup may legitimately retain gather.

The new Phase 0 package and this specification directory are excluded to avoid recursively cataloging the inventory's own quoted old names.

Ignored local design records remain governing records.

The scanner is read-only and prints JSON without changing repository files.

```bash
./venv/bin/python -m test.test_att.test_autonomous_activity_phase0._inventory --summary
./venv/bin/python -m test.test_att.test_autonomous_activity_phase0._inventory
```

Regenerate the tracked snapshot through normal file editing after an intentional dependency change and review the removals rather than suppress inventory failures.

## Ownership and Disposition

| Area | Required disposition |
| --- | --- |
| `core/manager/discussions/`, `facade/discussions_api.py` | Remove team discussion coordination, numbered rounds, inbox/session cleanup, text/detailed result APIs, and whole-team discussion lock. |
| `core/agent.py`, `core/team.py`, `facade/governance_api.py`, `manager/lifecycle.py` | Preserve one person's guards and membership relationships, replace standalone or team-owned model execution with common activity admission and technical checkpoints. |
| `core/strategies/`, `core/tool_runtime.py`, `tool/contract.py` | Keep parsing, validation, provider-neutral tools, auditors and typed results, add per-request notification refresh, declared effects, execution admission and valid one-result Native handles. |
| `tool/context.py`, invocation-scoped tool resolution | Resolve the captured personal or AgentTeam scope explicitly, reject membership-based fallback from a personal scope, and enforce the trusted ordinary or restricted audit lifecycle profile. |
| `core/response.py`, package exports | Remove discussion results/statuses/round records and rename provenance and activity failure concepts without preserving old API aliases. |
| `core/config.py` | Delete discussion-round and whole-discussion abort configuration, rename real request/batch/context units, and install strict nested groups with confirmed defaults. |
| `core/governance.py`, `core/decision.py`, `manager/governance/` | Replace solicitation rounds with cases/revisions, preserve explicit immutable ballots and voluntary addressed mail, and remove hidden voter discussions. |
| `core/broker/`, `tool/communication.py`, `communication_validation/` | Preserve AT endpoints, snapshots, channels, revocation and transactional delivery, implement queue as voluntary mail and real independent-side routing, and reject unsupported wake. |
| `manager/migration.py`, `topology.py`, `failover.py` | Replace reset-on-session counters and nested approvals with requests, accepted parents, own-position cooldown and bounded resource cases, without implicit Root or representative fallback. |
| `manager/formations/`, `team_creation/`, `tool/delegation.py`, `tool/formation.py` | Retain staging, exact-revision consent, four attitudes and creation-retention, replace mandatory drafts and synchronous business waits with optional advice and durable admission references. |
| `manager/supervision.py`, `alerts.py` | Replace two-round audit/emergency execution with temporary managed AT activity and explicit structured findings or incident acknowledgement. |
| `manager/memory/`, `core/memory/`, `tool/memory.py` | Replace turn/discussion origins with invocation/source provenance, preserve optional catalog and transient privacy, and checkpoint bounded continuing activity. |
| `manager/state.py`, `snapshots.py`, `snapshot_dependencies.py` | Replace whole-session persistence boundaries with immutable domain deltas and causal dependency receipts. |
| `manager/restore/`, `state_validation/` | Validate schema 12, explicit optional parents, new records and historical views, fence old workers and publish a recoverable complete generation. |
| `database/models/`, `database/persistence/` | Replace solicitation schema and round fields, extend writer/reader ordering and merge rules, and activate schema 12 only with supported physical layout. |
| `manager/callbacks.py`, callback signatures and event payloads | Retain ordered observational dispatch, remove round metadata and incomplete-turn synthetic publication, and keep private bodies out of generic events. |
| Existing `test/test_att/` packages | Replace obsolete behavioral assertions rather than skip them, preserving consent, quota, identity, corruption, reliability, and privacy regressions. |
| `typecheck/consumer_contract.py`, CI wheel smoke | Replace old exported result references and examples only when their new public runtime is implemented. |
| README, user/developer APIs, Tool System, Dynamic Delegation, governance and formation docs | Change directly affected runtime examples and terminology without unrelated restructuring. |
| `docs/flowcharts/` | Replace round/session/transcript/emergency loops with personal admission, explicit publication, execution receipts and incident paths. |
| `Roadmap/Async_Event_Driven_Collaboration.md` | Reconcile outdated concurrency, automatic broadcast, convergence, actors and business-leader assumptions with the governing confirmed blueprint. |

## Review Rules

An individual invocation, message position, model request, electorate revision, and execution attempt are technical facts rather than renamed all-member rounds.

All-member valid governance participation remains an authorization requirement rather than a barrier on ordinary conversation.

Source messages and historical evidence remain retained even when automatic transcript generation disappears.

No unrelated Agent fields may change while implementing join, leave, migration, detachment, parent loss, or team dissolution.

Retirement and retained death are explicit privileged lifecycle changes, not side effects of losing membership.

The final Phase 5 deletion gate must re-scan runtime call paths and exports as well as lexical occurrences, because a zero word count alone cannot prove absence of a hidden barrier.

The Phase 0 green test checks snapshot completeness, not that any round dependency has already been removed.
