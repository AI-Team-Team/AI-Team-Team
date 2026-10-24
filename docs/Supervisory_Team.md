# Supervisory Team

Health supervision is event-driven and does not grade ordinary business output, progress, quality, or completion.

Each admitted assessment creates a real, fresh, privileged AgentTeam through Manager's staged team creation.

The temporary people use the same personal scheduler, provider-request service, invocation locks, ToolExecutor, quota ledger, and writer as ordinary people.

There is no separate audit reasoning engine, discussion round, whole-team session lock, or reused auditor memory.

## Triggering an assessment

The strict defaults in `ATTConfig.health` are:

| Evidence | Default behavior |
| --- | --- |
| Confirmed permission-execution or state-integrity fault | Apply the trusted deterministic protection immediately and retain an incident; do not wait for an audit. |
| Model protocol corruption | Three consecutive structurally classified failures for one Agent within 600 seconds request assessment; a valid response resets that streak. |
| Invalid tool arguments | Five consecutive errors of the same category for one Agent and tool within 600 seconds request assessment; a successful call to that tool resets its streak. |
| Semantic suspicion | Disabled unless the Host enables a detector and explicitly supplies its authorized evidence provider. |
| Silence, normal waiting, permission or business denial | Do not automatically trigger health assessment. |

Provider timeouts, disconnections, and availability faults belong to resource availability, not automatic Agent blame.

Reaching a threshold means that inspection is warranted, not that the Agent is unhealthy or an intervention is authorized.

The observation window ages detection samples only; it never expires a retained incident.

The Host can explicitly request an assessment:

```python
from ai_team_team import HealthSubject

admission = await manager.request_health_assessment(
    HealthSubject(kind="agent", subject_id=agent.agent_id),
    {"kind": "host", "facts": ["An explicitly authorized technical observation."]},
)
result = await manager.wait_for_health_assessment(admission.audit_id)
```

Equivalent active assessments coalesce by subject and stable evidence fingerprint.

A temporary inability to provision auditors retains the threshold evidence and incident without converting it into a personal activity failure.

This includes temporary filesystem failures while staging audit workspaces; incomplete staging leaves no registered auditors or private directories behind.

Persistence and integrity failures remain explicit failures.

## Fresh managed lifecycle

Each assessment creates new auditor identities, private working contexts, and a genuine temporary AgentTeam.

The predefined electorate is retained before auditor execution begins.

The total deadline defaults to `health.audit_timeout_seconds=600`, starts at admission, and includes scheduler queueing, provider waits, tool work, and communication.

It is independent of the 120-second parent-failover deadline.

Late provider responses or finding tools cannot acquire authority after that deadline.

Durable settlement and cleanup may finish after the model-execution deadline.

Auditors can explicitly read only admitted evidence, share permitted findings in their restricted team, inspect that conversation, submit their own structured finding, and choose idle.

Their tool view excludes ordinary private files, business tools, recruitment, topology changes, model selection, and peer communication.

Every predefined auditor must submit a valid finding before a strict majority can form a health conclusion.

Text answers and discussion summaries are not findings, and no chosen member compiles an authoritative consensus on behalf of the others.

A missing finding, failure, cancellation, tie, or deadline produces `UNKNOWN`.

Audit activity does not recursively trigger more audits.

## Evidence and privacy

Assessment admission accepts a small immutable evidence object and explicitly authorized observation references.

It does not sweep personal windows, private libraries, direct chat, background-task results, or hidden model reasoning.

Scoped model requests, sanitized execution observations, explicit shared findings, individual structured findings, identities, deadlines, and the final result remain retained in audit-specific records.

Audit prompts and transient observations do not join ordinary Agent Journal or episodic-memory ownership.

Temporary teams, auditors, and DocLibs are omitted from ordinary topology, discovery, and state snapshots.

Completion or failure removes the temporary runtime identities after accepted evidence has settled.

Restore retains the evidence and marks interrupted assessments unknown; it never restores or reuses the temporary people or automatically replays the audit.

## Result model

`AuditResult` has independent health and operational axes:

```python
AuditResult(
    status=AuditStatus.HEALTHY,
    reason="Every predefined auditor supplied a valid finding.",
    cause=None,
    operational_status=OperationalStatus.HEALTHY,
    operational_reason="Independent operational evidence was assessed.",
)
```

Health status is `HEALTHY`, `UNHEALTHY`, or `UNKNOWN`.

Operational status is `HEALTHY`, `DEGRADED`, or `UNKNOWN`.

A subject can be unhealthy and operationally degraded at the same time.

`operational_status_decision_mode="framework"` preserves the admitted framework operational evidence while auditors assess health.

`"supervisor"` requires the structured auditor findings to decide both axes.

`"framework_then_supervisor"` allows review and preserves the framework operational result when no trustworthy operational majority exists.

## Incident lifecycle

Non-healthy assessment results and configured operational degradation create or merge durable incidents.

A stable fingerprint retains occurrence count, first time, latest time, and technical references without message or private-file bodies.

There is no incident TTL and no hard limit that drops unique alerts.

`audit_unknown_escalation_mode` accepts `"queue"` or `"wake"`, while `operational_degraded_escalation_mode` additionally accepts the default `"none"`.

Attention follows the subject's actual current organizational authority rather than an implicit Root or a stale notification recipient.

Incident claims and acknowledgements revalidate that authority at their commit boundary, so waiting behind a topology change cannot preserve a former parent's authority.

Queue mode records an addressed notice without forcing activation.

Wake mode may request ordinary personal activity, but cannot switch another person's scope, override intent, or force a group discussion.

Incident handling is explicit:

```python
incident = manager.inspect_health_incident(incident_id)
async with manager.handle_health_incident(incident_id) as claim:
    # Perform authorized technical handling.
    await manager.acknowledge_health_incident(
        incident_id,
        incident["occurrence_count"],
        claim_token=claim.get("token"),
    )
```

Reading an email does not claim or acknowledge an incident.

A new occurrence invalidates acknowledgement of an older generation.

Failure, cancellation, and restart release active claims to pending, and explicit Host clearing acknowledges attention without deleting retained evidence.

Whole-ATT and root-level attention uses ordered metadata-only `on_system_event` callbacks.

Neither a health finding nor an incident implicitly grants business-repair, file, membership, permission, or model authority.
