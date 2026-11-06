# Model Requests, Presentation, and Token Settlement

ATT records what was admitted, what may have reached a provider, what outcome is known, and what budget remains reserved as separate facts.

These rules apply to ordinary activity, temporary audit participants, and optional memory indexing through the same model-alias ledger.

## Request Profiles and Dependencies

| Request table | Concrete provenance | Claim reference |
| --- | --- | --- |
| `model_requests` | Existing `notification_frames` row, its actual ordinary Agent, matching context/input version, and the frame's invocation. | `model_token_claims.model_request_id` |
| `audit_model_requests` | Existing `(audit_id, scoped_agent_id)` participant snapshot and audit-scoped invocation/frame evidence. | `model_token_claims.audit_request_id` |
| `memory_index_requests` | Existing source segment, its matching retained beneficiary, source version, and input digest. | `model_token_claims.index_request_id` |

An audit caller has no ordinary Agent or library dependency, and indexing does not create a personal admission for its beneficiary.

Each claim has exactly one of the three request references, and each reference column is independently unique.

The claim alias must equal its referenced request's alias.

Frames precede ordinary requests, and requests precede their claim-backed dispatch; there is no frame-to-future-request identity cycle.

## Legal Dispatch and Outcome Combinations

`dispatch_state` describes transport evidence, while `outcome` describes the last accepted outcome of that request.

| `dispatch_state` | Allowed `outcome` values | Meaning |
| --- | --- | --- |
| `unsent` | `pending` | An admitted request has no confirmed local completion or send evidence yet. |
| `confirmed_unsent` | `failed`, `cancelled` | The local request ended with confirmed absence of provider dispatch. |
| `sent` | `pending`, `completed`, `failed`, `cancelled`, `uncertain` | Dispatch is established; completion, failure, local cancellation, and current uncertainty remain distinct facts. |
| `unknown_sent` | `pending`, `completed`, `failed`, `cancelled`, `uncertain` | Available evidence does not establish whether dispatch occurred; this uncertainty must not erase an independently confirmed outcome. |

Every other pair is invalid in record capture, transactional graph validation, and detached restore.

For example, `unsent/completed` and `confirmed_unsent/pending` are corruption rather than states that restoration may repair by inventing dispatch.

A non-null `dispatched_at` requires `sent` or `unknown_sent` and cannot precede `created_at`.

Ordinary request attempts have a positive `attempt_index`, nonnegative input version, positive request budget, and a sequence budget at least as large as that request budget.

Admission waits, frame/checkpoint preparation, provider execution, provider waiting instructions, and backoff consume the live retry-sequence budget.

The [execution architecture](../Autonomous_Agent_Runtime_Architecture/Model_and_Tool_Execution.md#retry-and-availability) describes timing, earliest-retry boundaries, and Host remediation.

## Token Claim States

All reservations use nonnegative `prompt_budget` and `output_budget` values, even when the alias itself is disabled by a zero limit.

| `settlement` | `settled_at` | `actual_usage` | Required request evidence and accounting |
| --- | --- | --- | --- |
| `reserved` | Null | Null | Retain the reservation until factual settlement is known; interrupted unresolved claims are not silently refunded. |
| `confirmed_unsent` | Required | Null | Referenced request has `dispatch_state="confirmed_unsent"`; refund its reserved capacity. |
| `known_usage` | Required | Nonnegative integer | Referenced request has `dispatch_state="sent"` and a non-`pending` outcome; settle actual usage once and return unused reservation. |
| `unknown_sent` | Required | Null | Referenced request has `dispatch_state="unknown_sent"`; preserve potentially spent capacity conservatively. |

The SQL checks enforce nullability combinations and nonnegative usage, while the graph validator checks the matching request, profile, and alias.

Accepted usage may be provider-reported or estimated under ATT's accounting policy; `known_usage` does not certify provider billing accuracy.

Claim identity makes settlement idempotent, and a lost observer response does not create a second charge or another refund.

Prompt estimation includes explicit messages, system instructions, eligible notifications, and transmitted tool definitions and JSON Schema, together with the configured maximum output reservation.

Provider tokenization may differ from ATT's estimate; the detected admission boundary and atomic reservation remain mandatory.

## Presentation Claims

`notification_claims` has the composite primary key `(notification_id, model_request_id)` and concrete frame/request references.

| Claim status | Established fact |
| --- | --- |
| `reserved` | The notice was selected for a particular prepared request. |
| `dispatched` | Dispatch was recorded without proving successful model presentation. |
| `presented` | The associated request is `sent/completed`; this is presentation evidence only. |
| `uncertain` | Available request evidence cannot establish presentation. |

Neither reservation nor presentation marks mail or chat read, submits a ballot, expresses an invitation attitude, accepts friendship, or acknowledges execution/incident attention.

Before a new provider attempt, the runtime captures fresh eligible information after any unfinished Native exchange closes.

Already presented unanswered information does not repeatedly activate an owner who deliberately chose idle.

## Interruption and Recovery

Recovery settles requests and claims from their accepted evidence in detached state before runtime publication.

Confirmed-unsent claims refund, known usage settles once, and possibly spent or unresolved reservations remain charged.

Recovery does not replay a historical provider request, reconstruct an answer from an external handle, recreate audit participants, or replay an external tool.

Confirmed execution outcomes and factual provider outcomes remain distinct from a cancellation request or loss of a local wait.

See [Recovery and Publication](Recovery_and_Publication.md#domain-recovery) for domain-specific interruption handling and activation.

## Implementation and Behavioral Evidence

The [request outcome matrix](../../src/ai_team_team/database/persistence/records.py) is shared by all three profiles, and the [graph validator](../../src/ai_team_team/database/persistence/store/validation/graph.py) checks request, claim, alias, and presentation relationships.

The [request-state regressions](../../test/test_att/test_state_integrity/test_model_request_state_boundaries.py), [common quota tests](../../test/test_att/test_state_integrity/test_audit_and_quota.py), and [notification tests](../../test/test_att/test_agent_activity/test_notifications_and_tools.py) exercise these boundaries.
