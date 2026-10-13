"""Deterministic interruption evidence, without external replay or admission."""

import time
import uuid
from dataclasses import dataclass

from ai_team_team.database.persistence.records import DomainRecord, merge_records


@dataclass(frozen=True)
class RecoveryPlan:
    """Post-publication candidates, not proof that any work has been activated."""

    affected_agents: tuple[str, ...] = ()
    notification_ids: tuple[str, ...] = ()
    unaffected_sleep_ids: tuple[str, ...] = ()


def derive_recovery(staged, checkpoint_id, publication_id):
    records = staged._records.snapshot()
    existing = {row.values["affected_identity"] for row in records
                if row.table_name == "recovery_incidents" and row.values["checkpoint_id"] == checkpoint_id}
    affected, captured, events, notifications = set(), [], [], []
    arrivals = {}
    for row in records:
        if row.table_name == "agent_notifications":
            owner = row.values["agent_id"]
            arrivals[owner] = max(arrivals.get(owner, 0), row.values["arrival_generation"])
    for row in records:
        if row.table_name == "activity_invocations":
            if row.values["boundary_at"] is not None:
                continue
            key = f"invocation:{row.values['invocation_id']}"
            invocation_id, execution_id = row.values["invocation_id"], None
            last_confirmed = {"invocation_id": invocation_id, "boundary_at": None}
        elif row.table_name == "executions":
            if row.values["status"] not in {"queued", "running"}:
                continue
            key = f"execution:{row.values['execution_id']}"
            invocation_id, execution_id = row.values["invocation_id"], row.values["execution_id"]
            last_confirmed = {"execution_id": execution_id, "status": row.values["status"],
                              "state_version": row.version}
        else:
            continue
        owner = row.values["agent_id"]
        agent = staged._agents_by_id[owner]
        if agent.lifecycle_state != "active":
            continue
        affected.add(owner)
        if key in existing:
            continue
        suffix = uuid.uuid5(uuid.NAMESPACE_URL, f"att:{checkpoint_id}:{owner}:{key}").hex
        incident_id, notification_id = f"RI-{suffix}", f"RN-{suffix}"
        now = time.time()
        captured.append(DomainRecord.capture("recovery_incidents", {
            "incident_id": incident_id, "agent_id": owner, "checkpoint_id": checkpoint_id,
            "publication_id": publication_id, "invocation_id": invocation_id, "execution_id": execution_id,
            "affected_identity": key, "last_confirmed": last_confirmed, "uncertain": 1,
            "created_at": now, "created_version": 1,
        }))
        event = staged._memory.record_event("recovery_interruption", agent=agent,
            payload={"incident_id": incident_id, "affected_identity": key,
                     "checkpoint_id": checkpoint_id, "outcome_unconfirmed": True},
            persist=False, inherit_context=False)
        events.append(event.model_dump(mode="json"))
        arrivals[owner] = arrivals.get(owner, 0) + 1
        captured.append(DomainRecord.capture("agent_notifications", {
            "notification_id": notification_id, "agent_id": owner, "source_kind": "system_event",
            "chat_message_id": None, "mail_id": None, "execution_id": None,
            "system_event_id": event.event_id, "publication_id": publication_id,
            "classification": "recovery", "deduplication_key": f"recovery:{checkpoint_id}:{key}",
            "arrival_generation": arrivals[owner], "created_at": now, "created_version": 1,
        }))
        notifications.append(notification_id)
    # A previously committed incident is not reissued on repeated load.
    # The later activity runtime interprets the plan; Phase 1 never dispatches it.
    sleep_ids = tuple(row.values["sleep_id"] for row in records if row.table_name == "sleep_plans"
                      and row.values["status"] == "active" and row.values["agent_id"] not in affected)
    staged._records.restore(merge_records(records, captured))
    return tuple(captured), tuple(events), RecoveryPlan(tuple(sorted(affected)), tuple(notifications), sleep_ids)
