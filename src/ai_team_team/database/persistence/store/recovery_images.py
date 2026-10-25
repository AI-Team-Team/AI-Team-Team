"""Bounded before-images for required recovery updates under one writer lease."""

from sqlalchemy import and_, select

from ai_team_team.core.exceptions import StateRestoreError
from ai_team_team.database.models import ACTIVITY_TABLES, Base
from ai_team_team.database.persistence.records import thaw


SECTIONS = {
    "memory_events": ("system_memory_events", "event_id"),
    "memory_segments": ("agent_memory_segments", "segment_id"),
    "governance_cases": ("governance_cases", "case_id"),
    "communication_requests": ("communication_requests", "request_id"),
    "communication_approvals": ("communication_approvals", None),
}
ALLOWED = {
    "activity_admissions", "activity_invocations", "model_requests", "model_token_claims",
    "notification_claims", "agent_notifications", "agent_activities", "executions",
    "memory_index_requests", "audit_runs", "audit_evidence", "audit_model_requests",
    "audit_execution_evidence", "health_incidents", "health_incident_events", "resource_decisions",
    "recovery_incidents", "sleep_plans", "notification_suppression", "notification_summary_items",
} | {
    table for table, _key in SECTIONS.values()
}


def validate_images(images):
    if images is None:
        return
    if type(images) is not list:
        raise StateRestoreError("Recovery before-images must be a list.")
    seen = set()
    for item in images:
        if type(item) is not dict or set(item) != {"table", "key", "before"} or item["table"] not in ALLOWED:
            raise StateRestoreError("Invalid recovery before-image table or fields.")
        table = Base.metadata.tables[item["table"]]
        if type(item["key"]) is not dict or set(item["key"]) != {column.name for column in table.primary_key}:
            raise StateRestoreError("A recovery before-image requires an exact primary key.")
        if any(type(value) is not str or not value for value in item["key"].values()):
            raise StateRestoreError("Invalid recovery before-image identity.")
        identity = item["table"], tuple(sorted(item["key"].items()))
        if identity in seen:
            raise StateRestoreError("Duplicate recovery before-image identity.")
        seen.add(identity)
        before = item["before"]
        if before is not None and (type(before) is not dict or set(before) != set(table.columns.keys())
                or any(before[key] != value for key, value in item["key"].items())):
            raise StateRestoreError("A recovery before-image contradicts its identity or schema.")


def capture_images(store, delta):
    keys = {}
    for record in delta.get("records", ()):
        table = ACTIVITY_TABLES[record.table_name]
        key = {column.name: record.values[column.name] for column in table.primary_key}
        keys[record.identity] = (record.table_name, key)
    for section, (name, column) in SECTIONS.items():
        for row in delta.get(section, ()):
            key = ({column: row[column]} if column else {
                "request_id": row["request_id"], "principal_kind": row["principal"]["kind"],
                "principal_id": row["principal"]["principal_id"],
            })
            keys[name, tuple(key.values())] = name, key
    images = []
    with store.session_factory() as session:
        for name, key in keys.values():
            table = Base.metadata.tables[name]
            predicate = and_(*(table.c[column] == value for column, value in key.items()))
            before = session.execute(select(table).where(predicate)).mappings().one_or_none()
            images.append({"table": name, "key": key, "before": dict(before) if before is not None else None})
    validate_images(images)
    return images


def restore_images(session, images):
    images = thaw(images)
    validate_images(images)
    # Deferred restrictive FKs permit exact restoration of a mutually dependent
    # candidate without manufacturing higher versions or replaying domain work.
    for item in reversed(images or ()):
        table = Base.metadata.tables[item["table"]]
        predicate = and_(*(table.c[key] == value for key, value in item["key"].items()))
        before = item["before"]
        if before is None:
            session.execute(table.delete().where(predicate))
        elif session.execute(select(table).where(predicate)).first() is None:
            session.execute(table.insert().values(**before))
        else:
            session.execute(table.update().where(predicate).values(**before))
