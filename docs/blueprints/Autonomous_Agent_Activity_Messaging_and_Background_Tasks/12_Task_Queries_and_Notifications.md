# 12. Task Summaries, Queries, and Notifications

[Back to blueprint index](README.md).

## Confirmed Direction

The AI's prompt always includes a lightweight summary of its background tasks.

```text
Background tasks: 10 running, 4 completed, 1 failed, 2 stalled.
```

The stalled count belongs to the health dimension and may overlap with the running count rather than describe two additional executions.

Task completion, failure, and suspected-stall events should notify the owner promptly through the same single-person activation mechanism.

The event and pending notification are recorded promptly even when an admitted temporary do-not-disturb preference or sleep plan defers presentation until the person's wake conditions allow it.

Important system notices, including interruption findings requiring recovery activation, are not deferred by those preferences.

The criteria for a suspected-stall event and the notification deduplication rules still need to be finalized.

The task body or complete output need not be injected automatically merely to report a count or completion notice.

The AI can use list, search, and inspection tools to obtain task information deliberately.

```python
list_background_tasks(...)
search_background_tasks(...)
inspect_background_task(...)
```

These are candidate tool names rather than implemented signatures.

Query behavior should follow the on-demand list, search, and inspection approach of Agent and AgentTeam Discovery rather than automatically inserting every task record into each prompt.

The default query scope is the same person's tasks across all memberships rather than only tasks associated with its current AgentTeam.

The personal view must not become unrestricted discovery of other people's private executions or outputs.

The recommended history behavior is that acknowledging a task does not automatically delete its record or remove it from later queries.

This recommendation does not establish an unlimited retention policy or decide which acknowledged tasks remain in the always-visible summary.

## Open Choices

For current query, summary, and notification contracts, refer to the [implementation plan](../Implementation_plan_Autonomous_Agent_Activity_Messaging_and_Background_Tasks/10_Background_Tasks.md).

- Exact filters, search fields, order, pagination, and response shapes.
- Which completed and failed tasks contribute to always-visible counts.
- Whether acknowledged historical tasks remain in the summary or only in queries.
- Notification deduplication and explicit acknowledgement behavior.
- Retention, archival, and deletion policies for results, execution records, and external handles.
- Permissions for deliberately sharing a task or result with an AgentTeam or another person.
