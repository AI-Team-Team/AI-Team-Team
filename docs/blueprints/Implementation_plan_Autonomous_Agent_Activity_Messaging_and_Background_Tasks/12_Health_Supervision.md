# 12. Health Supervision and Alert Handling

[Back to plan index](README.md).

## 12.1 Evidence and triggers

Replace end-of-discussion auditing with health-evidence sampling over explicitly permitted activity and execution events.

Candidate evidence includes repeated structurally similar activity, repeated invalid operations, corrupted output, and confirmed runtime availability incidents.

The confirmed scope covers health of Agents, AgentTeams, and ATT itself, including garbled or uninterpretable model output and evidence that permission enforcement is malfunctioning.

Use deterministic framework checks for permission and state invariants where possible, with the supervisory team assessing permitted evidence rather than serving as the sole authorization mechanism.

Confirmed permission or state-integrity faults are recorded and protected immediately by the framework without waiting for an audit vote.

Activity silence, lack of a published answer, ordinary long waits, and business progress are not health failures.

Task-health evidence and personal or team health evidence remain separately attributable.

Configure health triggers by evidence type rather than introduce a universal health score.

Exact per-evidence thresholds remain configuration-design choices, and no additional business-review or intervention authority follows from confirming D10.

Private documents, raw arguments, direct-chat bodies, and personal Working Context are not automatically audit input.

## 12.2 Real short-lived supervisory teams

Continue creating a fresh registered special-privilege AgentTeam with fresh audit-scoped Agents for each health assessment.

ATT supplies its predefined template, restricted tools, evidence access, and health-assessment contract rather than granting ordinary organizational autonomy.

Run those Agents through the common activity, message, and execution boundaries rather than a dedicated second reasoning engine.

Auditors deliberately share their permitted findings in a restricted audit conversation and submit strict structured health findings.

Final aggregation uses an explicitly documented audit contract instead of selecting `members[0]` as an implicit authoritative representative.

All predefined audit members must submit valid structured results before a strict majority can form the health conclusion.

Missing results, failed assessment, or a tie produce `UNKNOWN` rather than infer a result from partial participation.

A health conclusion does not itself authorize business-content repair, permission changes, or changes to the governance institution.

No business-progress leader, reviewer, or completion evaluator is appointed.

After a result, failure, cancellation, or shutdown, commit evidence and dissolve the audit team and its runtime identities without retaining personal memory for reuse.

Persist audited subject references and historical auditor identity snapshots without foreign keys requiring ephemeral teams or Agents to become ordinary persistent participants.

Full save and restore must not recreate abandoned audit teams or make auditors discoverable as ordinary recruits or friends.

The audit service may have technical budgets and deadlines, but cannot implement them as a hidden multi-member round loop.

Long-lived supervisory teams are deferred in [Future Plans](../Todo_Autonomous_Agent_Activity_Messaging_and_Background_Tasks.md#long-lived-preconfigured-supervisory-teams).

## 12.3 Incidents and escalation

Preserve content health and operational health as independent dimensions.

Keep stable incident fingerprints, occurrence counts, first and latest timestamps, and no automatic TTL or hard dropping limit for unique incidents.

`queue` and `wake` escalate through event-driven organizational handling rather than emergency discussion rounds.

Delivery or presentation does not automatically acknowledge an incident.

The proposed replacement for automatic discussion-success removal is explicit authoritative incident acknowledgement, with claim failure or cancellation returning the incident to pending.

This confirmed technical health acknowledgement is not a mandatory business-completion interface.

Repeated incidents and audit-service failures must not create recursively waking audit chains for the same evidence generation.

Root-level incidents propagate through durable system events and callbacks rather than another implicit representative.
