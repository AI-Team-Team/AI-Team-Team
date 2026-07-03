# Todo

This document only contains In Progress, Known Issues, and Future Plans.

Any resolved issues should not be stored in this document.

## In Progress

## Known Issues

1. **Transcripts Token Overhead**: Passing full, multi-turn transcripts to the 3-AI Supervisory Team for consensus auditing increases token consumption on long debate sessions. Needs summary compression thresholds.
2. **State Corruption on Mid-Round Membership Mutation**: During `execute_team_discussion`, `asyncio.gather(*tasks)` executes reasoning steps for all members of the team. If a membership change (via administrative add/remove or resolved democratic voting) resolves within an agent's step, `team.members` is immediately modified. Upon completion of gather, `zip(team.members, results)` is called, which gets misaligned or truncated because the list length/order has mutated during execution.
3. **Stale root_ai Reference in SupervisoryTeam on state restore**: In `ATTManager.load_state`, `self.root_ai` is reassigned to the reconstructed root Agent. However, the supervisor instance (`self.supervisor`) keeps holding a reference to the old, pre-load `root_ai` instance in `self.supervisor.root_ai`. Any root-level escalation or anomaly reports are subsequently routed to the stale root AI.
4. **DocLib Prefix-Bypass Path Traversal**: The path safety check in `DocumentLibrary._resolve_path` evaluates path correctness using `resolved.startswith(self.root_dir)`. If a folder prefix matches the target directory (e.g. `/path/to/DL-AT-12` matching `/path/to/DL-AT-1`), it successfully bypasses path traversal verification. Needs `os.path.commonpath` or separator suffixing.
5. **Memory Compression Breaks Chat API Message Sequence**: The memory pruning routine in reasoning strategies slices the message history at a hardcoded offset (`len(messages) - max_memory_turns`). Under Native Tool Calling, if this slice point cuts between an assistant message containing `tool_calls` and its corresponding `tool` response messages, the Chat Completion API call (e.g. OpenAI/Gemini) fails validation due to violating sequence rules.

## Future Plans

1. **Visual Lineage Dashboard**: Build a lightweight web-based viewer to render the active dynamic Agent Team lineages tree, agent roles, real-time thinking states, and debate transcripts.
2. **Token Budget Circuit Breakers**: Implement token and financial cost tracking directly in the ReAct step executor, throwing cost limit anomalies to the Supervisory Team for graceful fallback.
3. **Human-in-the-Loop Interception Hook**: Extend the tool auditor callback system to support asynchronous human approval prompts before executing destructive or high-cost tools.
