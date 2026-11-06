# Future Plans: Autonomous Agent Activity, Messaging, and Background Tasks

## Status and Scope

This document records deferred features as of 2026-10-07.

The current implementation plan is [Implementation Plan: Autonomous Agent Activity, Messaging, and Background Tasks](Implementation_plan_Autonomous_Agent_Activity_Messaging_and_Background_Tasks/README.md).

These features are outside the initial replacement scope, and unresolved policy details must not be treated as approved defaults.

## Topics, Channels, and Threads

Extend the initial simple team and direct message streams with optional topics, channels, and threads.

Preserve explicit publication, personal read state, author-only version and withdrawal rules, and frozen departure-time views that later edits or withdrawals cannot rewrite.

Select hierarchy, membership, reference visibility, notification, and navigation contracts before implementation rather than infer them from the presence of a thread ID.

## Immediate Communication-Approval Wake

Add a future communication request-delivery mode named `wake` for immediate approval handling, while the initial implementation uses voluntary personal approval mail through `queue`.

The proposed wake mode requires immediate approval handling rather than leaving timing entirely to the recipient.

Define the relationship to sleep, permanent or countdown do-not-disturb, an already active personal invocation, unavailable models, and an unanswered ballot before implementing that requirement.

Immediate handling cannot fabricate an approval, change the configured approval principal, replace a voter, or create another simultaneous model-driven copy of a person.

No current implementation may silently advertise wake support by treating it as queue.

This item concerns communication approval only and does not defer protected system notices or ordinary sleep-timer wake.

## Long-Lived Preconfigured Supervisory Teams

Explore long-lived ATT-managed supervisory AgentTeams as an alternative to the confirmed initial approach of creating and dissolving a fresh restricted audit AT for each assessment.

Keep supervision limited to health of Agents, AgentTeams, and ATT, including abnormal output and permission-system evidence, without evaluating business correctness, quality, progress, or completion.

Preserve immediate deterministic integrity protection, evidence-specific triggers, and explicit structured aggregation rather than allow persistent auditors to gain repair or governance authority implicitly.

Define audit-to-audit memory isolation, retained evidence, restricted tools, reset or replacement behavior, concurrent audit context, shutdown, and recovery before using persistent audit identities.

Continue using the common Manager and AgentTeam mechanisms rather than introduce a separate reasoning engine.

## Git-Backed Team DocLib Collaboration

Make an AgentTeam's DocLib a Git repository, with authorized Agents collaborating through clone, branches, and push rather than only direct shared-file overwrites.

Define clone locations, private and shared working copies, branch authority, ordinary push behavior, merge handling, and the mapping between repository operations and live DocLib ACLs.

Force operations such as force push must not execute directly and require the configured AgentTeam vote to authorize the exact operation.

The electorate, threshold, affected references, and scope of other force flags require a separate governance design rather than an implicit voting rule.

Preserve source ownership, privacy, real-time access checks, explicit publication, persistence, and recovery without making friendship or membership consent an implicit repository permission.

The initial implementation retains resource-based serialization and accepts later writes overwriting older-read content without introducing optimistic version checks or overwrite confirmation.
