# Todo

This document only contains In Progress, Known Issues, and Future Plans.

Any resolved issues should not be stored in this document.

## In Progress

## Known Issues

1. **Transcripts Token Overhead**: Passing full, multi-turn transcripts to the 3-AI Supervisory Team for consensus auditing increases token consumption on long debate sessions. Needs summary compression thresholds.
2. **Database Deserialization KeyError**: During state recovery, if `row.communication_rules` is empty or null, it falls back to `{}` instead of the default structure `{"allow_sibling_talk": False, "rules": []}`, leading to a `KeyError` when appending rules.

## Future Plans

1. **Visual Lineage Dashboard**: Build a lightweight web-based viewer to render the active dynamic Agent Team lineages tree, agent roles, real-time thinking states, and debate transcripts.
2. **Token Budget Circuit Breakers**: Implement token and financial cost tracking directly in the ReAct step executor, throwing cost limit anomalies to the Supervisory Team for graceful fallback.
3. **Human-in-the-Loop Interception Hook**: Extend the tool auditor callback system to support asynchronous human approval prompts before executing destructive or high-cost tools.
