# 15. Authority and Privacy Across Activities

[Back to blueprint index](README.md).

## Confirmed Direction

Personal identity persists while the authority for a particular operation may vary.

An AgentTeam tool operation must identify the team under which the person is acting and validate current membership and applicable permissions.

The Agent must not acquire combined authority over all its teams simply because its prompt shows several message summaries.

Personal chat is not an alternate route to team-file access or formal team authorization.

A personal background task must not inherit a new team's permissions merely because its owner later changes activity context.

Task results, message bodies, tool arguments, private files, and Working Context must not be exposed indiscriminately through generic counts, discovery, callbacks, or health logs.

Explicitly reading private material may inform the same person's later choices without automatically publishing that material to every team it belongs to.
