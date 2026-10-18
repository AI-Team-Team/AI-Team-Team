"""Full SQL reference validation for restores and differential regressions."""

from sqlalchemy import CheckConstraint, text

from ai_team_team.core.exceptions import StateRestoreError
from ai_team_team.database.models import ACTIVITY_TABLES
from .validation.graph import read_graph, validate_graph


def validate_records(session, *, current_memberships=None, partial_memberships=False):
    graph = read_graph(session)

    def require(condition, reason):
        if not condition:
            raise StateRestoreError(f"Invalid durable checkpoint: {reason}.")

    for name, table in ACTIVITY_TABLES.items():
        for check in table.constraints:
            if isinstance(check, CheckConstraint):
                invalid = session.execute(text(f'SELECT 1 FROM "{name}" WHERE NOT ({check.sqltext}) LIMIT 1')).first()
                require(invalid is None, f"{name} check violation")
        for column in table.columns:
            for check in column.constraints:
                if isinstance(check, CheckConstraint):
                    invalid = session.execute(text(f'SELECT 1 FROM "{name}" WHERE NOT ({check.sqltext}) LIMIT 1')).first()
                    require(invalid is None, f"{name}.{column.name} check violation")

    validate_graph(graph, current_memberships=current_memberships, partial_memberships=partial_memberships)
