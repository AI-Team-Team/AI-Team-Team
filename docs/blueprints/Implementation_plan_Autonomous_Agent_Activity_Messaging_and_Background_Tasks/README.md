# Implementation Plan: Autonomous Agent Activity, Messaging, and Background Tasks

## Status and Authority

This implementation plan defines the target runtime replacement and its engineering delivery phases based on repository analysis performed on 2026-10-06.

The decision record was updated on 2026-10-07.

Phase 0 was completed on 2026-10-08.

The [Phase 0 contract freeze](../../../docs/dev/autonomous_activity/README.md) contains strict value contracts, the replacement inventory, target schema 12, built-in effect declarations, deterministic fixtures, and a separately runnable red specification gate.

The replacement runtime and schema activation remain unimplemented, with subsequent phases recorded as planned work.

Reattachment requires the prospective parent's acceptance, unilateral voluntary detachment is enabled by default through a configurable Host setting, and cross-tree lineage approval follows both actual lineages to their independent top-level teams without adding a common Root absent from the topology.

Confirmed requirements include restorable personal deletion, permanent do-not-disturb, explicit LLM retry defaults, configurable cooldown downtime accounting, and membership-free active Agents.

Source-and-count summaries after do-not-disturb and sleep-equivalent suppression countdown bounds also remain confirmed.

Confirmed requirements also include absence-period exclusion after rejoining, unchanged read receipts and retained reminder previews, ordinary-Agent death, independent reattachment, and bounded LLM retries.

Personally retained chat archives, parent-loss independence, and per-endpoint parent or ancestor approval exemptions remain confirmed.

All D01 through D15 institutional choices and their subsequent topology clarifications are confirmed for the initial replacement scope.

Remaining work concerns engineering specification, implementation, and verification rather than unresolved institutional requirements in the initial scope.

The governing design remains [Autonomous Agent Activity, Messaging, and Background Tasks](../Autonomous_Agent_Activity_Messaging_and_Background_Tasks/README.md).

The replacement removes discussion-round execution throughout the runtime, including governance, formation, emergency handling, and supervision.

The blueprint's institutional boundaries preserve authorization and decision semantics, not an exemption allowing those institutions to retain round-based execution.

This document distinguishes planned delivery phases from implemented and verified runtime behavior.

Confirmed requirements, proposed engineering contracts, and deferred features are distinguished below.

Names, signatures, table layouts, and numeric values labeled proposed are implementation candidates rather than silently selected defaults.

No compatibility layer, legacy execution mode, staged public interface labeled as a separate generation, or migration of old SQLite databases is proposed.

The source blueprint retains its historical descriptions of unresolved choices, with links to this plan for current decisions.

Confirmed contracts in this plan take precedence over conflicting earlier engineering recommendations or historical blueprint wording.

Deferred features are recorded separately in [Future Plans](../Todo_Autonomous_Agent_Activity_Messaging_and_Background_Tasks.md), and implementation-review items remain explicitly identified in Section 19.

### Navigation

Read the chapters in the numbered order below.

- [1. Scope of the Replacement](01_Scope.md).
- [2. Repository Findings and Replacement Map](02_Repository_Findings.md).
- [3. System Invariants](03_System_Invariants.md).
- [4. Proposed Architecture and Ownership](04_Architecture.md).
- [5. Personal Activity and Safe Continuation](05_Personal_Activity.md).
- [6. Context, Memory, and Model Requests](06_Context_and_Memory.md).
- [7. Notifications, Sleep, and Do-Not-Disturb](07_Notifications_and_Sleep.md).
- [8. Team Conversation Streams and Historical Membership](08_Team_Conversations.md).
- [9. Direct Personal Chat and Friendship](09_Direct_Chat_and_Friendship.md).
- [10. Tracked Execution and Background Tasks](10_Background_Tasks.md).
- [11. Round-Free Governance, Formation, Migration, and Failover](11_Governance_and_Topology.md).
- [12. Health Supervision and Alert Handling](12_Health_Supervision.md).
- [13. Authoritative Transactions and Concurrency](13_Transactions_and_Concurrency.md).
- [14. Persistence Schema, Checkpoints, and Recovery](14_Persistence_and_Recovery.md).
- [15. Shutdown, Retirement, and Historical Evidence](15_Lifecycle_and_Shutdown.md).
- [16. Proposed Public Contracts and Configuration](16_Public_Contracts_and_Configuration.md).
- [17. Implementation Sequence and Gates](17_Implementation_Sequence.md).
- [18. Verification Matrix](18_Verification_Matrix.md).
- [19. Decision Status and Implementation Review](19_Decision_Status.md).
- [20. Traceability and Completion Definition](20_Traceability.md).
