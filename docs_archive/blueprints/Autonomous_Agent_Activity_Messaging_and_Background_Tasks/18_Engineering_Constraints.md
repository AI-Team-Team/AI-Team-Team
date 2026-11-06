# 18. Proposed Engineering Constraints to Validate

[Back to blueprint index](README.md).

These recommendations express reliability and safety concerns to address during implementation planning rather than new autonomous-work policies.

- Coordinate one person's model activity across ordinary work, personal chat, team messages, inbox matters, and task notifications.
- Persist source records and notification progress so active-to-idle transitions and restarts cannot silently lose new information.
- Use idempotent message submission and task-result publication rather than assuming callbacks run exactly once.
- Capture operation scope explicitly and revalidate permissions where execution touches protected resources.
- Avoid unbounded automatic response chains in which silence itself repeatedly wakes the same Agent.
- Validate voluntary sleep and temporary do-not-disturb plans so personal filters cannot disable every wake or recovery path.
- Apply admission control without discarding accepted messages, falsifying execution state, or cloning a busy person.
- Release synchronous waiting safely when execution detaches without replaying the operation or corrupting native tool sequencing.
- Keep execution facts, observed health, attention, personal read state, and collective judgments independently inspectable.
- Preserve historical provenance without automatically injecting complete archives into model context.

No mandatory storage schema, resource limit, retention duration, or scheduler implementation is chosen by this list.

For current engineering contracts, refer to the [implementation plan](../Implementation_plan_Autonomous_Agent_Activity_Messaging_and_Background_Tasks/README.md).
