"""Validate a value-only staging graph without registering or repairing identities."""

import atexit
from contextlib import contextmanager
from functools import lru_cache
from threading import RLock

from sqlalchemy import Float, Integer, JSON, create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from ai_team_team.core.exceptions import StateRestoreError
from ai_team_team.database.models import ACTIVITY_TABLES, Base
from ai_team_team.database.persistence.records import DomainRecord, thaw

from .record_validation import validate_records
from .records import write_records


_validation_lock = RLock()


@lru_cache(maxsize=1)
def _validation_engine():
    engine = create_engine(
        "sqlite://",
        hide_parameters=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    atexit.register(engine.dispose)
    return engine


@contextmanager
def _validation_session():
    """Reuse only schema, never data, in a process-owned in-memory database."""
    # Session.close always rolls back, including invalid graph exceptions.
    # The short worker-side lock excludes every peer graph and never holds the
    # event loop. No file, writer connection, or runtime object is cached here.
    with _validation_lock:
        with Session(_validation_engine()) as session:
            yield session


def validate_detached_records(state, *, partial=False):
    records = state.get("records", ())
    if not records:
        if not partial and any(row.get("members") for row in state.get("teams", ())):
            raise StateRestoreError("A complete checkpoint requires current membership intervals.")
        return ()
    try:
        index = {}
        for record in records:
            if (
                not isinstance(record, DomainRecord)
                or DomainRecord.capture(record.table_name, record.values) != record
            ):
                raise ValueError("Invalid immutable durable record.")
            if record.identity in index:
                raise ValueError("Duplicate durable record identity.")
            index[record.identity] = record
        sources = {
            "agents": {row["agent_id"]: row for row in state["agents"]},
            "libraries": {row["lib_id"]: row for row in state.get("libraries", ())},
            "teams": {row["team_id"]: row for row in state["teams"]},
            "agent_memory_segments": {
                row["segment_id"]: row for row in state.get("memory_segments", ())
            },
            "system_memory_events": {
                row["event_id"]: row for row in state.get("memory_events", ())
            },
            "agent_inbox": {
                mail["message_id"]: mail
                for inbox in state.get("agent_inboxes", {}).values()
                for mail in inbox
            },
            "governance_cases": {
                row["round_id"]: row for row in state.get("governance_rounds", ())
            },
        }
        for record in records:
            for constraint in ACTIVITY_TABLES[record.table_name].foreign_key_constraints:
                table = constraint.referred_table
                values = tuple(
                    record.values[element.parent.name] for element in constraint.elements
                )
                if any(value is None for value in values):
                    continue
                exists = (
                    (table.name, values) in index
                    if table.name in ACTIVITY_TABLES
                    else len(values) == 1 and values[0] in sources.get(table.name, {})
                )
                if not exists:
                    raise ValueError(f"Missing concrete staging reference to {table.name}.")
        with _validation_session() as session:
            # Only validated retained reference projections are materialized.
            # No Agent, manager, DocLib, binding, or missing row is created.
            for name, rows in sources.items():
                table = Base.metadata.tables[name]
                for identity, source in rows.items():
                    values = {}
                    for column in table.columns:
                        if column.nullable:
                            values[column.name] = source.get(column.name)
                        elif isinstance(column.type, JSON):
                            values[column.name] = source.get(column.name, {})
                        elif isinstance(column.type, Integer):
                            values[column.name] = source.get(column.name, 1)
                        elif isinstance(column.type, Float):
                            values[column.name] = source.get(column.name, 0.0)
                        else:
                            values[column.name] = source.get(column.name, identity)
                    if name == "governance_cases":
                        principal = source["principal"]
                        values.update(
                            case_id=identity,
                            data=source,
                            principal_agent_id=principal["principal_id"]
                            if principal["kind"] == "agent"
                            else None,
                            principal_team_id=principal["principal_id"]
                            if principal["kind"] == "agent_team"
                            else None,
                        )
                    if name == "teams":
                        values.update(
                            creator_agent_id=source["creator_id"]
                            if source["creator_type"] == "agent"
                            else None,
                            creator_team_id=source["creator_id"]
                            if source["creator_type"] == "team"
                            else None,
                        )
                    session.execute(table.insert().values(**values))
            write_records(session, records)
            # Use captured current relationships, not fabricated SQL rows.
            # A volatile domain delta may precede checkpoint capture of
            # unrelated intervals; a full restore must contain them all.
            memberships = {
                (row["team_id"], agent_id)
                for row in state["teams"]
                for agent_id in row.get("members", ())
            }
            validate_records(session, current_memberships=memberships, partial_memberships=partial)
    except StateRestoreError:
        raise
    except Exception as exc:
        raise StateRestoreError("Invalid durable staging graph.") from exc
    return tuple(records)
