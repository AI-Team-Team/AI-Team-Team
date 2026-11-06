# Design Blueprints

This directory contains target designs and implementation plans rather than descriptions of the current runtime.

## Autonomous Agent Activity, Messaging, and Background Tasks

- [Design blueprint](Autonomous_Agent_Activity_Messaging_and_Background_Tasks/README.md): The governing behavioral design for continuing individual Agents, AgentTeam conversations, direct personal communication, background execution, and recovery.
- [Implementation plan](Implementation_plan_Autonomous_Agent_Activity_Messaging_and_Background_Tasks/README.md): Confirmed decisions, engineering contracts, implementation phases, and verification gates.
- [Future plans](Todo_Autonomous_Agent_Activity_Messaging_and_Background_Tasks.md): Deferred features outside the initial replacement scope, not a progress checklist for the implementation phases.

The blueprint retains historical proposals and unresolved choices, with references to the implementation plan for current decisions.

Confirmed contracts in the implementation plan take precedence over conflicting earlier proposals or historical blueprint wording.

Phase 0 was completed on 2026-10-08 and is documented in the [contract freeze](../dev/autonomous_activity/README.md).

It supplies value contracts, verification fixtures, and specifications without implementing the replacement scheduler or activating schema 12.

The replacement runtime and schema activation remain planned work.

For current-runtime documentation, return to the [documentation index](../README.md).
