# 3. System Invariants

[Back to plan index](README.md).

1. A manager has at most one admitted model-driven activity for a given Agent identity at a time, regardless of message source, membership count, or governance role.
2. Joining, leaving, migrating, or dissolving a team never reassigns an existing Agent's identity, personal instructions, model binding, memory, Private DocLib, inbox, friendships, or task ownership.
3. Membership-related notices are independently addressed system records rather than replacement of Agent-owned fields.
4. Team-sensitive operations use one explicit, validated operation scope rather than the union of all teams mentioned in a prompt.
5. Shared messages, direct messages, personal mail, notification presentation, read state, ballots, attention acknowledgement, and business judgments remain separate facts.
6. Every source record accepted for delivery survives scheduling backpressure and does not depend on a callback successfully running.
7. Unanswered information already presented does not repeatedly reactivate a person merely because it remains unread or unanswered.
8. Model answers, private artifacts, and tool observations are never automatically published into a team conversation.
9. Background execution never creates a second owner activity or independently modifies the owner's Working Context.
10. Detachment preserves the same execution identity and does not cancel, retry, restart, or duplicate an operation.
11. A recorded cancellation request is not a confirmed cancellation.
12. Recovery preserves last-confirmed facts, labels uncertainty, and makes no automatic external execution, polling, or reconnection calls.
13. No activity or observer runs against partially restored state, and stale execution references cannot mutate a newly published runtime.
14. Important system notices and a finite latest-wake condition cannot be disabled by personal sleep or do-not-disturb filters.
15. ATT downtime does not consume persisted sleep countdowns.
16. Ordinary silence, an empty queue, a completed tool, and a successful health audit do not certify business completion.
17. Optional episodic memory remains optional, and no indexing model is required for basic activity, messaging, or notification delivery.
18. Generic discovery, callbacks, logs, counts, and health evidence expose only their explicit field allowlists.
19. Leaving an AgentTeam freezes the shared chat information visible at the departure boundary, and later edits or withdrawals do not mutate that frozen view.
20. An Agent with no memberships remains an independent active identity unless a separate authorized lifecycle operation changes its state.
21. Permanent do-not-disturb suppresses selected ordinary reminders and activation, but cannot suppress protected system notices or a sleep plan's finite wake safeguard.
22. An independent AgentTeam may have no organizational parent, and a missing parent is not an implicit Root relationship or inferred creator relationship.
23. Withdrawal changes the current source projection without erasing existing recipient-owned unread reminders, previously captured authorized previews, or read receipts.
24. Dissolution removes an AgentTeam from live discovery and publication while preserving each Agent's previously authorized personal chat archives.
25. Loss of an actual Agent or AgentTeam parent makes surviving direct child teams independent without destroying them, their descendants, or members' owned state.
26. Independent endpoints are exempt from their own parent or ancestor approvals, not from another endpoint's approvals, membership consent, identity validation, DocLib ACLs, or runtime integrity constraints.
27. Reattachment requires explicit acceptance from the prospective Agent or AgentTeam parent and cannot be inferred from an independent team's permissive status.
28. An attached AT may voluntarily detach without its old parent's approval by default, subject to a configurable unilateral-detachment permission and the existing own-position cooldown and integrity checks.
