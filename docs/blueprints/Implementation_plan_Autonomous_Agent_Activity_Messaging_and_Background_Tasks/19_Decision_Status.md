# 19. Decision Status and Implementation Review

[Back to plan index](README.md).

This section records confirmed design contracts as of 2026-10-07.

Exact API names, executor contracts, and numerical settings not explicitly confirmed remain subject to design review.

## 19.1 Decision record

| ID | Status | Recorded contract | Remaining dependency |
| --- | --- | --- | --- |
| D01 | Confirmed. | Activity continues by default, with a tool only for deliberate idle or sleep and no required continuing declaration. | Final control-tool shape and fair technical scheduling. |
| D02 | Confirmed. | One validated scope per invocation, explicit switching at a safe boundary, and unchanged scope for already admitted executions. | Final scope-control API. |
| D03 | Queue, independent-side exemption, and lineage routing confirmed; wake deferred. | Deliver non-exempt required approval requests as voluntary personal mail, waive only an independent endpoint's own parent or ancestor requirements, preserve non-independent counterpart approval, allow independent pairs to communicate permissively, and use both real lineages to their independent tops for cross-tree attached endpoints. | Route derivation and persistence implementation, with wake safeguards deferred to future work. |
| D04 | Confirmed sleep and suppression behavior. | Mandatory sleep countdown, any-condition wake, positive day/hour/minute inputs, host-adjustable five-minute through two-day countdown bounds shared with timed suppression, permanent suppression, protected-notice bypass, and source-and-count unread summaries without previews after suppression ends. | Timer checkpoint precision and summary presentation integration. |
| D05 | Rejoin, message behavior, and personal archives confirmed. | Complete Markdown messages outside DocLib, first non-code level-one title, configurable 200-character title limit, 500 body-character preview, current-member author-only mutation, unread edit reminders, persistent personal deletion, latest-committed-edit withdrawal deadlines, prior snapshots retained after rejoining without absence-period synchronization, existing reminder previews and receipts surviving withdrawal, and authorized personal archives surviving AT dissolution. | Storage and projection implementation rather than an unresolved archive-access policy. |
| D06 | Confirmed. | Three messages per sender per relationship period, recipient-owned refusal clearance, metadata-only friendship requests, and explicit acceptance for crossed requests. | API naming and storage details. |
| D07 | Confirmed. | Measure the configurable 120-second threshold from actual executor start, exclude queue and preflight, and detach the same execution without cancellation or restart. | Executor timing integration and cumulative retry/backoff accounting. |
| D08 | Coordination and whitelist confirmed. | Explicit background permission, cross-owner conflicting-resource serialization, independent-resource concurrency, and no new version-check or overwrite-confirmation requirement. | External declaration validation and supported safety or isolation contracts. |
| D09 | Confirmed. | Show live and unresolved attention or uncertainty counts, retain acknowledged queryable history, and add no automatic result deletion or sharing grant. | Query and summary implementation. |
| D10 | Confirmed scope, lifecycle, and aggregation. | Temporary restricted real ATs assess health only, with all predefined structured findings required for a strict majority, missing or failed assessment and ties as UNKNOWN, evidence-specific triggers, and no business or governance repair authority. | Exact configurable evidence thresholds and audit deadlines, with long-lived teams deferred. |
| D11 | Lifecycle, independent organizations, detachment, and reattachment confirmed. | No death on last departure, retained inactive history and private artifacts, Host-only ordinary-Agent death without membership, creator, or active-call barriers, Root protection, factual task stopping or fencing, surviving children becoming independent after parent loss, configurable default-enabled unilateral departure, required target acceptance for reattachment, and personal archives surviving team dissolution. | Exact configuration and API shapes, transactional coordination, and acceptance provenance implementation. |
| D12 | Confirmed. | Autonomous proposal design, addressed invitations, four independent attitudes, voluntary feedback, and exact-revision consent without mandatory advisory workflow. | Replace old draft gates and preserve validated creation. |
| D13 | Confirmed cooldown and downtime policy. | At most one successful own migration per AT every ten minutes, ancestor-carried movement excluded, and real downtime counted by default with configurable exclusion. | Persistent clock evidence and commit-time validation. |
| D14 | Confirmed. | Durable by default with a configured database, explicit volatile operation, and no silent mode fallback or database creation. | Mode-aware receipts and admission. |
| D15 | Cooldown and LLM retry boundaries confirmed. | Ordinary tool errors retain activity, cooling affects only new same-Agent/tool calls without extending or replaying, and separate LLM policies use three extra retries, one-second base, thirty-second Full Jitter cap, per-model 120-second timeout, ten-minute sequence budget, one-minute recoverable re-admission, and provider earliest-retry precedence. | Precise typed tool-fault and provider-adapter contracts, not the confirmed default timeout or recovery values. |

## 19.2 Confirmation closure and engineering review

No institutional confirmation remains outstanding for D01 through D15 and the subsequent topology choices in the initial implementation scope.

The prospective parent must accept reattachment, unilateral voluntary detachment is enabled by default but Host-configurable, and cross-tree lineage uses the actual required principals up to each independent top-level AT without inventing a common Root.

The confirmed default intentionally allows an AT to gain its own permissive communication status through authorized voluntary independence, while preserving another endpoint's requirements.

Remaining engineering review covers exact public signatures and configuration placement, strict executor capability declarations, typed fault classification, transaction and lock ordering, physical schema design, configurable audit deadlines and per-evidence thresholds, and measured timer-checkpoint precision.

Those items implement the confirmed institutions and are not unapproved alternatives to them or permission to change their defaults.

If implementation research exposes a material institutional tradeoff or a contradiction that cannot be resolved within these contracts, submit the issue for explicit design review before changing a confirmed rule.

Deferred topics, immediate communication-approval wake, long-lived supervisory teams, and Git-backed Team DocLibs belong to [Future Plans](../Todo_Autonomous_Agent_Activity_Messaging_and_Background_Tasks.md), not the initial implementation scope.
