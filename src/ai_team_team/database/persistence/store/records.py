"""Transactional immutable record IO, exact receipts, and physical validation."""

import hashlib
import json

from sqlalchemy import and_, select, text

from ai_team_team.core.exceptions import StatePersistenceError, StateRestoreError
from ai_team_team.database.models import ACTIVITY_TABLES, commit_receipts
from ai_team_team.database.persistence.records import DomainRecord, thaw, validate_update
from ai_team_team.database.persistence.receipts import CommitReceipt


def write_records(session, records):
    """Insert prerequisites under deferred restrictive FKs; validate before commit."""
    for record in records:
        table = ACTIVITY_TABLES[record.table_name]
        values = thaw(record.values)
        predicate = and_(*(column == values[column.name] for column in table.primary_key))
        existing = session.execute(select(table).where(predicate)).mappings().one_or_none()
        if existing is None:
            session.execute(table.insert().values(**values))
            continue
        if table.info["append"]:
            if dict(existing) != values:
                raise StatePersistenceError("An append-only durable fact cannot be rewritten.")
            continue
        if existing["state_version"] > values["state_version"]:
            continue
        if existing["state_version"] == values["state_version"]:
            if dict(existing) != values:
                raise StatePersistenceError("A durable version cannot identify conflicting projections.")
            continue
        validate_update(DomainRecord.capture(record.table_name, existing), record)
        session.execute(table.update().where(predicate).values(**values))


def read_records(session):
    records = []
    for name, table in ACTIVITY_TABLES.items():
        try:
            records.extend(DomainRecord.capture(name, row) for row in session.execute(select(table)).mappings())
        except (ValueError, TypeError) as exc:
            raise StateRestoreError(f"Invalid durable records in {name}.") from exc
    return tuple(records)


def write_receipts(session, operations):
    receipts = []
    for operation in operations:
        values = {
            "operation_id": operation.operation_id, "state_version": operation.state_version,
            "dependencies": list(operation.dependencies),
            "record_digest": operation.record_digest,
        }
        digest = hashlib.sha256(json.dumps(values, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        existing = session.execute(select(commit_receipts).where(commit_receipts.c.operation_id == operation.operation_id)).mappings().one_or_none()
        if existing is None:
            session.execute(commit_receipts.insert().values(**values, digest=digest))
        elif existing["digest"] != digest:
            raise StatePersistenceError("An accepted operation identity cannot acknowledge different state.")
        receipts.append(operation)
    return tuple(receipts)


def read_receipt(session, operation_id):
    try:
        row = session.execute(select(commit_receipts).where(commit_receipts.c.operation_id == operation_id)).mappings().one_or_none()
    except (ValueError, TypeError) as exc:
        raise StateRestoreError("A commit receipt contains malformed JSON evidence.") from exc
    if row is None:
        return None
    values = {key: row[key] for key in ("operation_id", "state_version", "dependencies", "record_digest")}
    digest = hashlib.sha256(json.dumps(values, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if digest != row["digest"]:
        raise StateRestoreError("A commit receipt's accepted-operation evidence is inconsistent.")
    dependencies = row["dependencies"]
    if type(dependencies) is not list or any(type(key) is not str or not key.strip() for key in dependencies):
        raise StateRestoreError("A commit receipt requires a list of concrete dependency identifiers.")
    try:
        return CommitReceipt(row["operation_id"], row["state_version"], "durable", tuple(dependencies), row["record_digest"])
    except (ValueError, TypeError) as exc:
        raise StateRestoreError("A commit receipt contains invalid authority evidence.") from exc


def validate_database(session):
    if session.execute(text("PRAGMA foreign_key_check")).first() is not None:
        raise StateRestoreError("The checkpoint contains a dangling concrete foreign key.")
    from .scalar_validation import validate_scalars
    validate_scalars(session)
    from .record_validation import validate_records
    validate_records(session)
    from .governance_reader import read_governance_state
    read_governance_state(session)
    for operation_id in session.execute(select(commit_receipts.c.operation_id)).scalars():
        read_receipt(session, operation_id)
