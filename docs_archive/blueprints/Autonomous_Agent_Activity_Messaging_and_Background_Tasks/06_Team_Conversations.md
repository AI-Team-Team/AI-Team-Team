# 6. AgentTeam Conversations

[Back to blueprint index](README.md).

## Confirmed Direction

Each AgentTeam provides a shared message mechanism through which its members can deliberately speak and read other members' messages.

An Agent can participate in several team conversations while retaining one identity and one continuing personal memory.

A message is attributable to its actual author and target AgentTeam rather than to an inferred representative.

Team-sensitive operations still require the correct operation context and current authorization.

Automatically returning a model answer must not be equivalent to sending a team message.

Private documents, hidden model reasoning, raw tool observations, and unrelated personal conversation history must not be automatically broadcast to the team.

## Individual Views of Shared Messages

The conversation is shared, but each member has its own view of new messages and its own display preferences.

Team messages are conceptually different from copies of personal mail addressed to every member.

The data model should retain shared source messages with individually attributable read and notification state rather than conflating the source conversation with its notifications.

This is a data-model recommendation, not a finalized table layout.

For current message records and historical-view rules, refer to the [implementation plan](../Implementation_plan_Autonomous_Agent_Activity_Messaging_and_Background_Tasks/08_Team_Conversations.md).

## Model-Visible Summary

The Agent's prompt continues to show which of its AgentTeams have new messages.

Detailed display includes team information, the number of new messages, authors, titles, and short content previews.

```text
AT-237 (team information): 7 new messages

- Agent Mira — Database recovery: The checkpoint loaded, but one external job still needs reconciliation.
- Agent Rowan — Draft revision: The opening has been revised; comments on its tone are requested.

AT-123 (team information): 2 new messages

- Agent Sol — Build status: The test runner is still executing in the background.
```

The example illustrates presentation, not finalized names, fields, or a guarantee that every unread body fits into one prompt.

The AI may use a tool to disable or enable detailed display.

If only some new-message previews fit within the display budget, the summary should distinguish the total new-message count from the number of previews shown and indicate that more messages remain available.

With detailed display disabled, the summary still reports new-message counts.

```text
AT-237 (team information): 7 new messages
AT-123 (team information): 2 new messages
```

## Separate Controls

Disabling detailed display is not the same as marking messages read, muting notifications, declining to reply, or leaving a team.

Previews do not advance read state, while using a tool to read a message marks it read for that individual.

The AI may explicitly mark messages read or unread again, independently of whether it has replied or acknowledged a related task.

One person's read-state changes do not alter another person's read state.

Preview selection and size limits must remain distinct from message retention and the reported unread count.

Displaying several team summaries must not merge those teams' permissions into a single authority context.

## Chat History and Membership Intervals

A new member cannot retrieve AgentTeam chat messages from before its own joining boundary.

A departing member retains access to chat messages from the periods in which it belonged to the team but cannot learn about messages posted after departure through chat APIs or notifications.

If that same person rejoins, earlier eligible history remains available, messages from its absence remain unavailable, and messages from the new membership interval become available.

The person's eligible history is therefore the union of its actual membership intervals rather than all team history unlocked by current membership.

These boundaries apply to previews, unread counts, listing, search, message inspection, and linked chat references rather than only to the message-body read endpoint.

A former member can inspect its eligible historical messages without being granted current membership authority or receiving current-team unread summaries.

Chat-history entitlement does not authorize new posts, current team operations, or access to team files.

This rule applies to chat only and does not replace existing DocLib ACLs or remove knowledge, memories, or artifacts that the same person already legitimately acquired.

Membership intervals must be retained as relationship history without rewriting the person's identity or memory on each join or departure.

The engineering design must order membership changes and message publication consistently so concurrent operations have unambiguous history boundaries.

## Open Choices

For current message behavior and presentation defaults, refer to the [implementation plan](../Implementation_plan_Autonomous_Agent_Activity_Messaging_and_Background_Tasks/08_Team_Conversations.md).

- Whether conversations have topics, threads, or a single team stream with optional references.
- Whether titles are required, optional, or generated only for display.
- Message listing, search, inspection, reply, and mark-read API shapes.
- Exact preview budgets, sorting, and the default detail preference.
- Message editing, deletion, archival, and preservation of historical author identities.
- Exact read and mark-read API shapes, including which query operations return only previews and which perform a message read.
- Storage and ordering of membership intervals, including quoted-message and link filtering at historical-access boundaries.
