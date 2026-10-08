# 5. One Personal Activity Mechanism Across All Memberships

[Back to blueprint index](README.md).

## Confirmed Direction

An Agent's activation is coordinated at the person level rather than separately inside every AgentTeam.

An event for one team must not create a second simultaneous invocation of a person already active elsewhere.

If the Agent is active, new information is presented at a suitable next context-update boundary around the return of something it is waiting for.

By default, if the Agent is idle, a new message activates that same individual so that it can decide how to handle the information.

An explicit temporary do-not-disturb preference or voluntary sleep plan may defer that activation according to admitted wake conditions without making the person permanently unreachable.

Activation does not compel a reply or public expression of a position.

## Safe Notification Boundaries

An already submitted model request cannot be retroactively edited by appending a local notification.

The next safe model context must include pending information instead of attempting to create a parallel personal invocation.

Native tool-call/result sequences must remain valid when notifications arrive during tool execution.

An ordinary notification must not be inserted as a fabricated tool result or a message that breaks an unfinished tool batch.

Several arrivals may be summarized together without losing the underlying messages or their individual provenance.

The active-to-idle transition must not lose an event that arrived while the current invocation was finishing.

A notification already presented to an Agent must not repeatedly force new activations merely because the Agent deliberately chose not to respond.

## Runtime Availability and Personal Lifecycle

Idle or asleep means that a person is not currently continuing its model-driven activity, not merely that a particular model or tool request is waiting for a response.

A person with no activity it currently chooses to continue may sleep while waiting for new information to wake it.

It does not mean that the Agent has been retired, archived, or deleted.

Automatic activation must not silently reactivate an inactive identity or reconstruct a deleted person.

## Voluntary Sleep and Temporary Do-Not-Disturb

The AI may deliberately put its own model activity to sleep and specify conditions for waking the same continuing person.

The AI may also set temporary do-not-disturb preferences to defer selected reminders or activations while it continues other work or sleeps.

Do-not-disturb is not refusal of message delivery, blocking a sender, marking information read, hiding detailed previews, or withdrawing from an AgentTeam.

Otherwise admissible messages and task outcomes remain recorded while their notifications are deferred.

Sleeping does not cancel background executions, erase personal memory, change lifecycle status, or transfer ownership of tasks and artifacts.

Waiting for one tool or background result does not require putting the entire person to sleep if it chooses to handle other matters.

Candidate wake conditions include a selected countdown duration, a message from a selected source, or an outcome of a specified background task, with exact condition types and combination rules still to be finalized.

For current wake conditions and combination rules, refer to the [implementation plan](../Implementation_plan_Autonomous_Agent_Activity_Messaging_and_Background_Tasks/07_Notifications_and_Sleep.md).

Entering sleep must respect the existing safe invocation and commit boundaries rather than abruptly breaking tool-call/result ordering or an in-progress state transaction.

## Wakeability Safety Requirement

The AI must not be allowed to configure every possible wake path away and become permanently impossible to wake.

A sleep or do-not-disturb plan must preserve a usable wake or recovery path that the person's own notification filters cannot disable completely.

A syntactically valid condition referring to an event that may never occur is not by itself a dependable safeguard against permanent sleep.

The scheduler must retain and honor the admitted wake conditions independently of the sleeping person's suspended model activity.

Waking restores activity for the same person and does not imply that it must reply, resume particular work, or declare any result complete.

Voluntary sleep includes a finite latest-wake condition alongside any AI-selected early-wake conditions rather than relying only on another person eventually sending a message.

Temporary do-not-disturb cannot suppress that safeguard or important system notifications.

No default maximum sleep duration, complete ordinary-notification priority hierarchy, or unrestricted authority for one Agent to wake another has been agreed.

For current countdown bounds and protected-notification rules, refer to the [implementation plan](../Implementation_plan_Autonomous_Agent_Activity_Messaging_and_Background_Tasks/07_Notifications_and_Sleep.md).

## Important System Notifications

The following system notifications affecting the individual cannot be suppressed by its own do-not-disturb preferences or sleep filters.

- Its membership or organizational position changes, including joining, leaving, or movement or dissolution of an AgentTeam to which it belongs.
- Changes to permissions that affect its own actions or access.
- Formal health incidents concerning the individual or an AgentTeam that affect it.
- Recovery findings that its personal activity or tasks were affected by interruption.

ATT's trusted system mechanisms determine this classification rather than letting an ordinary chat sender bypass filters by labeling a message important.

An active person receives the notice at a safe context-update boundary, and a sleeping or idle person is scheduled to receive it without waiting for its ordinary message filters to match.

Non-suppressible delivery does not compel the person to reply, agree, accept a task, or take a particular business action.

Important system notices remain distinct from person-to-person messages and cannot be impersonated through chat tools.

## Sleep Countdown Across Interruption

Time-based wake conditions preserve the remaining countdown rather than consuming ATT's offline time.

If two hours remain when ATT stops, recovery starts a two-hour countdown instead of treating the wake condition as expired because wall-clock time passed during the outage.

The restoration start time provides the countdown anchor, while activation is not dispatched until the restored state has been successfully published.

The same rule applies to the finite latest-wake safeguard so that a stop does not silently replace the person's sleep plan with an absolute overdue deadline.

Recovery uses the latest successfully persisted remaining duration, with bounded checkpoint error rather than a promise to save the exact final millisecond of an unexpected interruption.

An important system notification can still wake the person earlier than its ordinary timer.

## Open Choices

For current decisions and remaining engineering dependencies, refer to the [implementation plan](../Implementation_plan_Autonomous_Agent_Activity_Messaging_and_Background_Tasks/19_Decision_Status.md).

- Exact tools and result contracts for continuing activity, voluntary sleep, temporary do-not-disturb, and personal wake conditions.
- Supported wake-condition types, combinations, and handling of conditions that become invalid.
- API representation of the finite latest-wake safeguard and supported event conditions without weakening the confirmed protected-notification rules.
- Expiration, scope, and allowed changes to temporary do-not-disturb preferences.
- Presentation of accumulated information when the same person wakes.
- Notification prioritization and fairness when a person has many active conversations.
- Cancellation and preemption while an external model request is still outstanding.
- The exact durable distinction between pending, presented, read, and answered information.
