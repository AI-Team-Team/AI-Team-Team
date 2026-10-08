# 21. Summary of Confirmed Defaults and Non-Defaults

[Back to blueprint index](README.md).

- Ordinary business discussion rounds disappear rather than merely becoming unlimited.
- Every Agent remains one continuing person across teams and activities.
- Speaking, remaining silent, and stopping participation are personal choices without a required end-discussion vote.
- A completion vote concerns a judgment about particular work, not permission to stop talking.
- New messages normally notify an active person at a safe context boundary or activate an idle person, subject to explicit admitted temporary do-not-disturb preferences and sleep conditions.
- Not speaking restricts no other personal activity.
- The AI may voluntarily sleep, specify wake conditions, and set temporary do-not-disturb preferences, but it cannot disable every wake or recovery path.
- Voluntary sleep includes a finite latest-wake safeguard, and important system notices cannot be suppressed.
- Important notices cover the person's membership or organizational position, affected permissions, formal health incidents, and interruption recovery findings.
- AgentTeam chat, direct personal chat, and personal inbox remain conceptually separate.
- Team-message counts remain visible, and the AI can enable or disable detailed previews.
- Previews do not mark messages read, tool reads do, and the AI may explicitly change its own read and unread state.
- Team chat visibility follows the union of actual membership intervals, preserving eligible history after departure without revealing absence-period messages on rejoining.
- Stranger contact permits at most three messages before accepted friendship, unless rejection or blocking stops receipt.
- Accepted friendship removes the stranger-message cap, while removing friendship resets the allowance and permits a renewed request.
- Either person's block prevents direct sends in both directions and ends friendship, while both cleared blocks return the pair to stranger contact with a fresh allowance.
- Background execution can be explicit or automatically detached after a configurable threshold whose default is 120 seconds.
- Operations modifying the AI itself do not run as detached self-mutations, while writing its Private DocLib is eligible for background execution.
- Personal background tasks are not reset or transferred by team membership changes.
- Background-task execution, health, and attention are separate state dimensions.
- Background-task summaries remain visible, with personal list, search, and inspection across memberships and prompt notification of completion, failure, and suspected stalls.
- Supervisory Teams assess health rather than business progress or work acceptance.
- State restoration and unfinished-activity recovery require separate, operation-specific contracts.
- Recovery labels affected executions and notifies the same owner without automatically inspecting, reconnecting, or replaying external operations.
- People who were active or whose tasks were affected are activated after successful restore, while unaffected sleeping people keep their own wake rules.
- Sleep countdowns pause across ATT downtime and resume from the latest persisted remaining durations at restoration start.
- WorkItem is a conceptual distinction rather than a required new table or API, with work plans and judgments kept through existing DocLibs.

No default maximum sleep duration, conversation-retention policy, stall timeout, exact API or table layout, checkpoint interval, or persistence schema version has been selected.

For current confirmed defaults and frozen contracts, refer to the [implementation plan](../Implementation_plan_Autonomous_Agent_Activity_Messaging_and_Background_Tasks/README.md).

No framework-defined work-acceptance procedure or mandatory completion-vote threshold is introduced.
