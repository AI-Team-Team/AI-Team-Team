"""Strict numeric evidence checks without loading message or document bodies."""

import math

from sqlalchemy import CheckConstraint, Float, Integer, select, text

from ai_team_team.core.exceptions import StateRestoreError
from ai_team_team.database.models import ACTIVITY_TABLES, Base


_INTEGER_FLAGS = {
    ("libraries", "is_public_visible"),
    ("communication_agreements", "active"),
    ("system_memory_events", "redacted"),
}


def validate_scalars(session):
    """Reject SQLite coercions and corruption even when CHECK was disabled."""
    for name, table in Base.metadata.tables.items():
        columns = [column for column in table.columns if isinstance(column.type, (Integer, Float))]
        if columns:
            for row in session.execute(select(*columns)).mappings():
                for column in columns:
                    value = row[column.name]
                    if value is None and column.nullable:
                        continue
                    valid = (type(value) is int if isinstance(column.type, Integer)
                             else type(value) in (int, float) and math.isfinite(value))
                    if not valid or ((name, column.name) in _INTEGER_FLAGS and value not in (0, 1)):
                        raise StateRestoreError(f"Invalid numeric checkpoint evidence in {name}.{column.name}.")
        if name in ACTIVITY_TABLES:
            # Cross-row record validation already checks these declarations.
            continue
        checks = [check for check in table.constraints if isinstance(check, CheckConstraint)]
        checks.extend(check for column in table.columns for check in column.constraints
                      if isinstance(check, CheckConstraint))
        for check in checks:
            invalid = session.execute(text(f'SELECT 1 FROM "{name}" WHERE NOT ({check.sqltext}) LIMIT 1')).first()
            if invalid is not None:
                raise StateRestoreError(f"Invalid checkpoint constraint evidence in {name}.")
