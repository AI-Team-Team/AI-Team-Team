# Autonomous Agent Activity, Messaging, and Background Tasks

## Purpose and Status

This blueprint describes the target design as of 2026-10-06 for replacing round-based ordinary business discussions with autonomous activity by continuing individual Agents.

It combines personal activity, AgentTeam conversations, direct person-to-person chat, background execution, and unfinished-activity recovery into one design direction.

It is a design specification rather than a claim that all described mechanisms are implemented.

Sections labeled confirmed direction identify established design requirements.

Engineering recommendations and unresolved choices are identified separately so that they do not silently become framework policy.

The behavioral decisions below are ready to guide implementation research, while exact APIs, configuration names, database tables, and a persistence schema version have not been finalized.

For current decisions and frozen contracts, refer to the [implementation plan](../Implementation_plan_Autonomous_Agent_Activity_Messaging_and_Background_Tasks/README.md).

### Design-Review Findings

The design distinguishes Agent identity, responsibility for work, and information scope when continuing individuals and organizations collaborate.

Continuing consent and AgentTeam authority remain separate from notification and recovery mechanics.

Completing a technical interaction does not establish completion of business work, and restoring stored state does not by itself recover unfinished activity.

These distinctions guide the personal activity, organizational authority, and checkpoint contracts described in this blueprint.

### Related Design Records

- [Implementation Plan: Autonomous Agent Activity, Messaging, and Background Tasks](../Implementation_plan_Autonomous_Agent_Activity_Messaging_and_Background_Tasks/README.md), which records current decisions, engineering contracts, and implementation phases.
- [Future Plans](../Todo_Autonomous_Agent_Activity_Messaging_and_Background_Tasks.md), which distinguishes deferred features from the initial replacement scope.
- [Asynchronous and Event-Driven Agent Collaboration](../../../Roadmap/Async_Event_Driven_Collaboration.md), whose preliminary assumptions are reconsidered here rather than adopted wholesale.

Confirmed contracts in the implementation plan take precedence over earlier engineering proposals or unresolved choices in this historical blueprint.

### Superseded Ideas

The earlier suggestion to make the default ordinary discussion round limit unlimited has been superseded by removing the ordinary business discussion-round concept itself.

Keeping an unlimited all-member round loop would not implement this design.

The suggestion to require a vote before an Agent may stop talking has also been rejected.

A vote may express a judgment that particular work is complete, but it is not permission for an individual to stop participating in a conversation.

Removing friendship resets the three-message stranger allowance rather than preserving an exhausted allowance.

This is a message-count reset, not a three-day messaging window.

Clearing both parties' block state also permits a fresh stranger allowance.

Automatic external-status discovery, reconnection, and replay during recovery are not part of the agreed design.

A separate framework WorkItem API or acceptance lifecycle is not required for this update.

### Navigation

Read the chapters in the numbered order below.

- [1. Foundation: An Agent Is One Continuing Person](01_Foundation.md).
- [2. Five Different Concepts](02_Core_Concepts.md).
- [3. Initial Scope and Institutional Boundaries](03_Scope_and_Institutional_Boundaries.md).
- [4. Ordinary Activity Without Discussion Rounds](04_Ordinary_Activity.md).
- [5. One Personal Activity Mechanism Across All Memberships](05_Personal_Activity_and_Wake.md).
- [6. AgentTeam Conversations](06_Team_Conversations.md).
- [7. Three Communication Surfaces, Not One Undifferentiated Inbox](07_Communication_Surfaces.md).
- [8. Direct Personal Chat and Friendship](08_Direct_Chat_and_Friendship.md).
- [9. AI-Authored Work in Existing DocLibs](09_Work_Artifacts.md).
- [10. Background Execution Has Two Entry Paths](10_Background_Execution.md).
- [11. Three Independent Background-Task State Dimensions](11_Background_Task_States.md).
- [12. Task Summaries, Queries, and Notifications](12_Task_Queries_and_Notifications.md).
- [13. Suspected Stalls and Evidence-Based Health](13_Task_Health.md).
- [14. Supervisory Teams Assess Health, Not Business Progress](14_Health_Supervision.md).
- [15. Authority and Privacy Across Activities](15_Authority_and_Privacy.md).
- [16. State Restoration and Unfinished-Activity Recovery](16_Persistence_and_Recovery.md).
- [17. Relationship to the Existing Asynchronous Roadmap](17_Asynchronous_Roadmap.md).
- [18. Proposed Engineering Constraints to Validate](18_Engineering_Constraints.md).
- [19. Implementation Research Boundaries](19_Implementation_Research.md).
- [20. Design Verification Scenarios](20_Verification_Scenarios.md).
- [21. Summary of Confirmed Defaults and Non-Defaults](21_Confirmed_Defaults.md).
