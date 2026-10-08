# 2. Repository Findings and Replacement Map

[Back to plan index](README.md).

The following paths identify the current implementation, not a claim that the proposed architecture already exists.

| Current area | Finding | Required replacement or reuse |
| --- | --- | --- |
| `core/manager/discussions/session.py` | Members already run concurrently within a round, but progression and publication are round-based. | Remove the coordinator and use independently admitted personal activity plus explicit shared messages. |
| `core/agent.py` and `core/manager/lifecycle.py` | One Agent has an invocation lock, runtime accounting, and dependency-cycle protection. | Retain single-person coordination and extend it to activity, shutdown, and execution leases. |
| `core/manager/facade/governance_api.py` | `execute_agent_interaction()` can run an ordinary personal interaction without a team. | Refactor it into the common personal activity entry point instead of maintaining an alternative scheduler. |
| `core/manager/inbox.py` | Personal mail is durable domain data, but ordinary notification creation does not itself schedule idle owners. | Separate mail from durable notification admission and route all model activation through one service. |
| `core/strategies/` | Context preparation is partly invocation-local, and tool waits hold the personal invocation. | Introduce safe request boundaries, fresh notification frames, and execution-handle observations. |
| `core/tool_runtime.py` and `tool/contract.py` | Validation, auditing, classification, and retry are shared, but every operation is synchronously awaited by its owner. | Preserve those checks and add declared effects, tracked execution, and safe detachment. |
| `database/models/teams.py` | `team_members` records only current relationships. | Add ordered membership history and historical chat entitlement. |
| `core/broker/` | AT-to-AT requests, Agreements, and message transactions already exist. | Preserve their authority while replacing round-dependent queue and wake processing. |
| `core/decision.py` and `core/manager/governance/` | Frozen electorates and explicit mail ballots exist, but preparation and notification still invoke discussion paths. | Use event-driven governance cases and the common personal runtime. |
| `core/manager/formations/lifecycle/` | Draft preparation and initial delegated work wait for round-based results. | Use advisory message references, explicit initiator publication, and durable initial-activity admission. |
| `core/manager/alerts.py` and `supervision.py` | Health incidents use emergency discussions, and audit deliberation uses two rounds. | Use factual incident handling and real temporary teams on the new runtime. |
| `core/manager/state.py`, `snapshots.py`, and `database/persistence/` | Incremental domain commits and immutable snapshots provide a usable foundation. | Extend dependency capture, records, receipts, merging, and publication to every new domain. |
| `core/manager/restore/` | Restore stages state and files, but does not reconstruct autonomous activity or manage detached executors. | Add recovery derivation, activation admission, timer restoration, and stale-worker protection. |

Offline probes conducted during the research confirmed that generic idle-mail delivery does not schedule a model invocation and that another interaction with the same Agent waits during a foreground tool wait.

A notification arriving during a tool wait was absent from the immediately following model request but present in a later newly started interaction.

The checkpoint probe retained two Journal messages while the restored Working Context contained zero messages because its two live messages remained in an unsubmitted discussion batch.

That last observation concerns missing submission boundaries, not restoration discarding an already committed personal window.

The unchanged implementation's baseline suite passed all 411 tests with `./venv/bin/python -m unittest discover -s test` during planning.

That baseline result is not acceptance evidence for the proposed runtime, whose new tests and implementation remain future work.

The current SQLite schema is `11`, and the proposed incompatible replacement schema is `12`, subject to confirming the complete schema before implementation.
