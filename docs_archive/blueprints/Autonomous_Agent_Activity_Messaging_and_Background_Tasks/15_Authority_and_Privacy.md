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

## Retained Task Results

A task result lawfully acquired and committed before a later source-permission revocation remains the owner's protected personal execution record.

By default, the owner may continue reading that retained result after the source permission is revoked.

The Host can disable this continued-read behavior, requiring current source authorization before protected retained-result content is returned.

Neither setting grants access to another person's results or bypasses current authorization for new source reads, result refreshes, or source writes.

Changing this access policy does not erase the Agent's existing memory, rewrite identity, delete execution history, or transfer task ownership when team relationships change.

Existing transient private-read and memory-recall rules remain in force; this policy is not permission to persist content that those rules exclude from durable task results.
