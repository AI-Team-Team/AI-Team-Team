# Autonomous Agent Runtime Architecture

ATT provides an autonomous Agent runtime for scheduling and executing each Agent's continuing personal activity.

An Agent remains one continuing individual with its own identity and memory across team memberships.

The runtime admits personal activity, prepares valid model contexts, coordinates tools and executors, and publishes accepted state transitions.

Formation consent, governance cases, communication policy, topology decisions, and health assessment retain their separate rules and authority while using these execution services.

## Documents

| Document | Responsibility |
| --- | --- |
| [Personal Scheduling](Personal_Scheduling.md) | One admitted owner, bounded invocations, fair continuation, explicit controls, and answer observers. |
| [Context and Notifications](Context_and_Notifications.md) | Captured scope, source references, presentation claims, unread state, checkpoints, and privacy. |
| [Model and Tool Execution](Model_and_Tool_Execution.md) | Provider-neutral requests, quota reservations, retries, executor admission, detachment, and resources. |
| [Executor Integration](Executor_Integration.md) | Strict effect/scope declarations, binding hooks, resource resolvers, health evidence, and a custom executor example. |
| [Institutional Services](Institutional_Services.md) | Explicit ballots, formation, communication, topology, resource decisions, and restricted audits. |
| [Lifecycle and Recovery](Lifecycle_and_Recovery.md) | Intent, availability, sleep, suppression, retained death, shutdown, and restoration handoff. |
| [Concurrency and Observers](Concurrency_and_Observers.md) | Lock responsibilities, accepted transactions, isolated execution context, and ordered callbacks. |

For public usage, start with [Personal Activity](../Personal_Activity.md), [Personal Conversations](../Personal_Conversations.md), and [Background Tasks](../Background_Tasks.md).

For physical state and publication mechanics, see [Database Architecture](../Database/README.md).

## Service Ownership

| Component | Owned responsibility |
| --- | --- |
| [Personal activity](../../src/ai_team_team/core/manager/activity/) | Admission, scheduling, captured invocation context, notifications, controls, model waits, and checkpoints. |
| [Messaging](../../src/ai_team_team/core/manager/messaging/) | Explicit team/direct sources, relationship authorization, personal views, read state, and reminders. |
| [Execution](../../src/ai_team_team/core/manager/executions/) | Registered operation admission, attempts, resources, detachment, results, controls, and factual health. |
| [Governance](../../src/ai_team_team/core/manager/governance/) | Exact cases, frozen eligibility, strict ballots, and institution-specific outcome publication. |
| [Manager facade](../../src/ai_team_team/core/manager/facade/) | Public Host entry points over the cooperating services. |
| [Restore](../../src/ai_team_team/core/manager/restore/) | Detached reconstruction, interruption settlement, recoverable publication, and post-publication handoff. |

Accepted source records are authoritative; process-local ready queues and Tasks are scheduling mechanisms over those records.

An ordinary answer, an empty queue, a successful tool, or a health finding does not certify completion of the AIs' work.

Work plans and business judgments remain deliberate artifacts in existing personal and team DocLibs, without a compulsory WorkItem model or framework-appointed business evaluator.

The [work and completion boundary](../Personal_Activity.md#work-conversation-and-completion) distinguishes these artifacts and participant judgments from conversation, registered execution, and institutional authority.
