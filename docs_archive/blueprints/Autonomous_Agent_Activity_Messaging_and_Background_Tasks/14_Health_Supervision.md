# 14. Supervisory Teams Assess Health, Not Business Progress

[Back to blueprint index](README.md).

## Confirmed Direction

A Supervisory Team assesses evidence of unintended repetitive activity, garbled or uninterpretable output, or comparable operational health problems affecting an Agent or AgentTeam.

It does not decide whether a novel is good, development is sufficiently advanced, a business goal has been met, or the team should accept a result.

There is no framework-appointed business supervisor whose role is to manage work progress.

If AIs choose a coordinator, reviewer, or other business role, that arrangement is their own organizational choice.

Legitimate silence, an empty queue, and an ordinary long-running execution are not automatically evidence of unhealthy activity.

The supervisory role does not automatically authorize access to every private conversation or document.

Confirmed permission-enforcement or state-integrity faults produce an incident and necessary deterministic protection immediately, without waiting for an audit.

The default automatic assessment triggers are three consecutive model-protocol failures within 600 seconds, or five consecutive same-category argument failures by the same Agent on the same tool within 600 seconds.

Valid model responses and successful calls reset the corresponding streaks, while team changes do not reset an Agent's detection state.

These rolling observation windows do not expire incidents, and threshold crossing requests investigation rather than authorizing model replacement, permission changes, or activity termination.

Provider timeouts and disconnections are resource-availability problems rather than automatic evidence against the Agent.

Semantic repetition or suspected garbling detection is disabled by default and requires a Host-enabled detector that does not infer failure merely from repeated text, special characters, or non-English output.

An audit has a configurable total deadline of 600 seconds by default, independent of parent failover's 120-second resource-decision deadline.

The deadline starts at durable admission and includes queueing, model calls, and necessary exchange; expiry produces UNKNOWN without abandoning evidence or required durable cleanup.

For current supervisory scope, lifecycle, and aggregation rules, refer to the [implementation plan](../Implementation_plan_Autonomous_Agent_Activity_Messaging_and_Background_Tasks/12_Health_Supervision.md).
