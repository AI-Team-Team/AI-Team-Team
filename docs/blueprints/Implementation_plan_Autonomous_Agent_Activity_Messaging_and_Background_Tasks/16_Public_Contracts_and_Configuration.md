# 16. Proposed Public Contracts and Configuration

[Back to plan index](README.md).

## 16.1 API and tool families

The following names describe intended capabilities and remain subject to interface review.

| Family | Proposed surface | Authority and result contract |
| --- | --- | --- |
| Personal admission | Host `activate_agent()` and activity inspection or event waiting. | Addresses the same registered person and returns an admission reference, not a certified business result. |
| Activity control | Proposed `set_activity_intent()` with strict idle and sleep choices. | Current Agent only, with changes applied at a safe boundary and no required continuing declaration. |
| Scope control | Explicitly request a validated personal or team scope for subsequent execution. | Current Agent only, with no retroactive change to admitted executions or an unfinished Native batch. |
| Team publication | `send_team_message()` and authorized reply references. | Current captured team scope and current membership, with a committed source receipt. |
| Team retrieval | List, search, read, revision inspection, and mark-read or mark-unread operations. | Eligible live or frozen relationship view filtered before metadata, with independent personal read state. |
| Message changes | Author-only versioned edits and timed withdrawal, plus personal deletion and explicit restoration. | AT mutation requires current membership, edits create unread reminders without restoring personal deletion, withdrawal timing starts at the latest committed edit or unedited send, existing reminders and authorized captured previews survive withdrawal, read receipts are unchanged, and frozen views remain unchanged. |
| Organization and lifecycle | Independent AgentTeams, explicit parent inspection, unilateral detachment or accepted reattachment, active-team discovery, personal archives, and privileged Host-only retained Agent death. | Host-configurable default-enabled unilateral departure, required target acceptance for reattachment, no creator-lifecycle barrier or implicit Root parent, direct children surviving parent loss, and no dissolved team in live discovery. |
| Preview preference | Per-person team or direct-chat detail controls. | Changes display only, not delivery, read state, or authority. |
| Direct chat | `send_direct_message()` and owner-authorized direct-stream retrieval. | Current sender identity, relationship checks, atomic allowance, and idempotent acceptance. |
| Friendship | Request, accept, reject, withdraw, remove, block, unblock, and refusal inspection or clearance. | Each person's own control and the current relationship generation. |
| Background execution | `start_background_task()`, list, search, inspect, request cancellation, and acknowledge attention. | Current owner, registered operation, ordinary validation and scope, with factual task references. |
| Sleep preferences | Sleep intent, wake-condition inspection, and permanent or timed do-not-disturb control. | Current owner, mandatory sleep safeguard, and protected notice exclusions. |
| Governance | Existing personal mail inspection and explicit strict choice submission, updated to case IDs. | Addressed active voter only, with no vote inferred from reading. |
| Institutional matters | Addressed approval mail, request inspection, and explicit ballot submission. | Configured principal and voluntary queue handling, not arbitrary sender override or forced approval. |
| Health incidents | Subject-authorized inspection and explicit handling acknowledgement. | No automatic acknowledgement from an ordinary answer or message read. |

Host administrative methods may accept an explicit authenticated actor, but model tools resolve their actor from invocation context and cannot select another person's identity.

Background tools must not accept arbitrary Python expressions, unregistered callables, caller-supplied executors, or policy overrides.

Use Pydantic results and stable JSON with operation status, reference IDs, affected versions, and durability information.

Distinguish accepted for execution, delivered into a source stream, presented to a model, and completed execution rather than overload one success string.

Read and inspection APIs reuse existing character continuation, file-version checks, and content-only read-token budgets where they return protected long text.

On-demand task queries follow the discovery approach without automatically injecting complete task records or a global directory.

Keep the provider-neutral client contract `tools: Optional[List[Tool]]` and avoid requiring a new provider-specific model response API for activity control.

## 16.2 Proposed configuration groups

Introduce strict nested configuration for personal activity, notifications, conversations, relationships, and execution rather than many mutually dependent flat flags.

Every supplied value and runtime assignment must use the same strict validation, including mutable mapping content.

| Existing setting or behavior | Proposed treatment |
| --- | --- |
| `subagent_discussion_rounds` and `emergency_discussion_rounds` | Delete without aliases or compatibility parsing. |
| `react_max_steps` | Replace with a clearly named per-invocation model-request budget. |
| `max_tool_rounds` | Replace with a per-invocation tool-batch budget, with no cross-member synchronization meaning. |
| `max_memory_turns` | Review and name the actual complete-exchange retention unit without preserving a team-round interpretation. |
| `turn_failure_policy` | Delete whole-discussion abort semantics and retain activity after ordinary tool failure, with classified per-Agent tool availability under D15. |
| `max_migrations_per_team_discussion` | Delete and use a ten-minute cooldown for the same AT's successful own migrations, excluding inherited ancestor movement. |
| `formation_deliberation_policy` | Remove the mandatory team-scoped draft prerequisite and use autonomous proposals, invitations, and voluntary feedback. |
| `enable_emergency_wakeup` | Review as institutional incident scheduling without allowing suppression of protected personal notices. |
| `communication` | Retain all three institutions and channel direction, exempt independent endpoints on their own side while retaining non-independent counterpart requirements, use queue as voluntary personal-mail handling, and defer communication wake. |
| Parent failover timeout | Retain the explicit positive 120-second default for the bounded resource attempt. |
| Automatic background threshold | Add the confirmed positive configurable 120-second default. |
| Background permission | Require an explicit whitelist declaration for built-in and externally registered tools. |
| Resource coordination | Serialize conflicting resources across owners while allowing independent resources to proceed, without new optimistic write-version or overwrite-confirmation checks. |
| Execution retry configuration | Retain explicit typed retry policy, retry count, retry safety, and backoff independently of detachment. |
| Message presentation and withdrawal | Use the first non-code level-one Markdown heading, reject titles over the configurable 200-character limit, show 500 body characters by default, and require the author to remain a current AT member for AT edits or withdrawal; each committed edit creates unread reminders and renews the default ten-minute withdrawal window without restoring personal deletion. |
| Historical chat | Freeze shared information at departure, including version and withdrawal state, preserve each person's authorized archive after team dissolution, and exclude absence-period messages without allowing later shared updates to modify frozen views. |
| Message withdrawal evidence | Preserve existing unread reminders, captured authorized previews, and read receipts while replacing the current source with an author-attributed withdrawal marker. |
| Organizational parent | Allow no parent or an explicit Agent or AgentTeam parent independently of creator provenance, detach surviving direct children when the actual parent disappears, and waive an independent side's parent or ancestor approvals without waiving another side's requirements. |
| Unilateral detachment | Add a strict Host-controlled permission enabled by default, with candidate field name `allow_unilateral_detachment`, retaining current acting authority, own-position cooldown, and atomic integrity checks without requiring the old parent's approval. |
| Reattachment acceptance | Require the prospective Agent's explicit personal decision or AgentTeam's collective decision for the exact attaching team and target, independently of the attaching team's own-ancestor exemption. |
| Cross-tree lineage | Collect required approval principals on both actual lineages through their respective independent top-level teams, deduplicate, retain recipient consent rules, and invent no common Root. |
| Sleep | Require a finite safeguard, positive-integer day, hour, and minute inputs, and host-adjustable total countdown bounds defaulting to five minutes and two days. |
| Do-not-disturb | Support permanent or countdown suppression scoped to the person, use sleep-equivalent countdown bounds, and default to source-and-count unread summaries without previews when suppression ends, without blocking delivery, explicit inspection, protected notices, or the sleep safeguard. |
| Tool cooldown | Use ten-minute per-Agent and per-tool cooling for eligible execution faults rather than parameter, path, or operation-specific permission mistakes. |
| LLM retry | Default to three additional retries, a one-second base, a thirty-second exponential jitter cap, a configurable per-model 120-second request timeout, a ten-minute whole-sequence budget, and one-minute recovery admission after recoverable exhaustion, never before a valid provider earliest-retry boundary. |
| Cooldown downtime | Count real elapsed downtime by default for migration and tool cooldowns, with host-configurable downtime exclusion. |
| Resource admission | Configure live model and executor capacity without interpreting rejection as an AI's choice or erasing accepted events. |
| Stall classification | Configure only supported evidence under D10 without inventing a universal stall duration. |
| Persistence mode | Default to durable with a configured database, and require explicit selection of intentionally volatile operation. |

Keep `tokenizers` as a required dependency, retain Python 3.11 through 3.13 support, and preserve `typing_extensions` usage for portable runtime schemas.

No new broker, scheduler, or provider SDK dependency is required merely to represent the proposed architecture.

## 16.3 Durability mode

The current manager allows `db_path=None`, so the blueprint's durability promises require an explicit policy rather than a silent assumption that every accepted event is committed to SQLite.

The confirmed D14 contract provides a durable mode requiring a configured state database, plus an intentionally volatile mode whose receipts and documentation clearly deny restart guarantees.

Durable is the default, so absent database configuration fails clearly rather than silently selecting volatile operation.

Do not silently create an unexpected database or write project-root storage merely to satisfy an implicit persistence assumption.

Each mode must preserve the same identity and authorization rules, while tests distinguish in-memory acceptance from durable acceptance.
