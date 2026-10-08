# 17. Relationship to the Existing Asynchronous Roadmap

[Back to blueprint index](README.md).

## Confirmed Direction

The earlier event-driven proposal is a source of ideas rather than an already approved implementation contract.

As recorded in the [repository findings](../Implementation_plan_Autonomous_Agent_Activity_Messaging_and_Background_Tasks/02_Repository_Findings.md), ordinary round members already use concurrent collection through `asyncio.gather()` when identity locks and resources permit.

The motivation here is therefore independent personal activation, removal of round barriers, deliberate messaging, safe background execution, and durable recovery rather than merely adding concurrency.

An independently scheduled actor is acceptable as an implementation idea only if it represents the one continuing Agent rather than a separate copy for every team.

The earlier assumptions about automatic public model responses, whole-person suspension on one tool wait, unrestricted mid-call preemption, and removing technical locks are not adopted.

An empty event queue does not mean work has converged or been completed.

An inactivity timeout may be a scheduling fact but must not certify a business result.

Supervision must not force a leader to synthesize a final business answer.

The preliminary Company Mode and Society Mode descriptions do not settle the detailed contracts in this blueprint.
