# Evolution of Asynchronous Collaboration

This document explains how ATT's early event-driven collaboration proposal evolved into continuing personal activity, explicit messaging, and registered background execution.

The [original proposal](Async_Event_Driven_Collaboration.md) is preserved unchanged as a historical design record.

## From the Early Proposal to the Current Design

The goal of independent Agent activity and flexible communication remains, while the execution, authority, and recovery contracts have become more explicit.

| Earlier proposal | Current mechanism |
| --- | --- |
| Agent actors organized around a per-team event broker. | One continuing personal runtime follows each Agent across all memberships, with serial model invocations for that identity. |
| Broad publish-subscribe events and free-flowing dialogue. | Agents deliberately publish team or direct messages; addressed notifications, presentation, reading, replies, and governance choices remain distinct. |
| Critical events immediately preempt ongoing reasoning. | Eligible protected notices use the personal runtime's wake and presentation rules while scope and control changes respect safe invocation and batch boundaries. |
| A suspension instruction pauses the Agent while a tool runs. | A declared operation can detach into the background with the same owner and execution identity while the Agent continues other activity. |
| Queue inactivity or Supervisor-selected synthesis determines discussion convergence. | Agents explicitly choose idle or finite sleep; queue state and technical checkpoints do not certify business completion. |
| Supervisor signals pause, resume, or organizational restructuring. | Restricted health audits record findings and support incident handling; organizational changes require their own institutional authority. |

Joining or leaving an AgentTeam changes membership relationships while the Agent retains its identity, memory, model binding, inbox, and Private DocLib.

Governance, Team Formation, communication, migration, resource decisions, and supervision retain their own authorization rules and durable protocols while using the common runtime to execute personal activity.

Recovery preserves accepted facts and interruption evidence without automatically replaying, polling, or reconnecting old external work.

## A Clarification About Concurrency

The original proposal's latency description conflates a round barrier with sequential member execution.

Members can execute concurrently within one round even though further progress still waits for the round's collective boundary.

The design change removes compulsory all-member discussion rounds and enables continuing personal activity; it should not be described as introducing member concurrency for the first time.

## Current References

The current contracts are documented in [Personal Activity](../docs/Personal_Activity.md), [Personal Conversations](../docs/Personal_Conversations.md), and [Background Tasks](../docs/Background_Tasks.md).

Institutional rules remain in [Team Governance](../docs/Team_Governance.md), [Consensual Team Formation](../docs/Consensual_Team_Formation.md), and [Supervisory Team](../docs/Supervisory_Team.md).

The [implementation plan](../docs/blueprints/Implementation_plan_Autonomous_Agent_Activity_Messaging_and_Background_Tasks/README.md) records confirmed decisions, implementation boundaries, and deferred work.
