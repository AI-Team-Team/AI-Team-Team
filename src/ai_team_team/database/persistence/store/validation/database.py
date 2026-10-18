"""Transaction-local incremental SQL checks with post-commit cache promotion."""

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select, text

from ai_team_team.core.exceptions import StateRestoreError
from ai_team_team.database.models import (
    GovernanceBallotModel,
    GovernanceElectorateModel,
    GovernanceRoundModel,
    MigrationRequestModel,
    commit_receipts,
)

from .graph import ValidationGraph, read_graph, validate_graph
from .tracking import MutationTracker


_GOVERNANCE_TABLES = frozenset(model.__table__.name for model in (
    GovernanceRoundModel, GovernanceElectorateModel, GovernanceBallotModel, MigrationRequestModel,
))


@dataclass(frozen=True)
class DatabaseCandidate:
    graph: ValidationGraph
    signature: tuple


class DatabaseValidationCache:
    """No candidate becomes reusable until the real SQLite commit succeeds."""

    def __init__(self, engine, db_path):
        self.tracker = MutationTracker(engine)
        self._accepted = None
        self._epoch = None
        self._base = None
        self._changes = None
        self.has_triggers = False
        self._path = Path(db_path)
        self._file_identity = self.file_identity()

    def file_identity(self):
        stat = self._path.stat()
        return stat.st_dev, stat.st_ino

    def check_file_identity(self):
        try:
            identity = self.file_identity()
        except OSError as error:
            self.finish()
            raise StateRestoreError("The active writer's database file is unavailable.") from error
        if identity != self._file_identity:
            self.finish()
            raise StateRestoreError("The database file identity changed while its writer was active; reopen the store.")

    @staticmethod
    def signature(session):
        connection = session.connection()
        return (connection.connection.driver_connection,
                connection.exec_driver_sql("PRAGMA data_version").scalar_one(),
                connection.exec_driver_sql("PRAGMA schema_version").scalar_one())

    def begin(self, session, *, full=False):
        signature = self.signature(session)
        accepted = self._accepted
        reusable = (not full and accepted is not None and accepted.signature == signature
                    and self._epoch == self.tracker.epoch and self._changes == signature[0].total_changes)
        # Arbitrary triggers may change tables which are absent from direct
        # SQL. Retain full validation whenever their effects are not known.
        self.has_triggers = session.execute(text("SELECT 1 FROM sqlite_master WHERE type='trigger' UNION ALL "
                                                "SELECT 1 FROM sqlite_temp_master WHERE type='trigger' LIMIT 1")).first() is not None
        if self.has_triggers:
            reusable = False
        self._base = accepted if reusable else None
        self.tracker.start()

    def prepare(self, session):
        from ..records import read_receipt, validate_database
        from ..governance_reader import read_governance_state
        from ..scalar_validation import validate_scalars

        signature = self.signature(session)
        base = self._base
        if base is None or self.tracker.uncertain or signature != base.signature:
            validate_database(session)
            graph = read_graph(session)
        else:
            changed = self.tracker.affected_tables()
            if session.execute(text("PRAGMA foreign_key_check")).first() is not None:
                raise StateRestoreError("The checkpoint contains a dangling concrete foreign key.")
            validate_scalars(session, tables=changed, combine_checks=True)
            graph = read_graph(session, previous=base.graph, changed_tables=changed)
            # These cheap value-only checks remain conservative: source and
            # reverse dependencies and whole collections are never skipped.
            validate_graph(graph)
            if changed & _GOVERNANCE_TABLES:
                read_governance_state(session)
            if "commit_receipts" in changed:
                for operation_id in session.execute(select(commit_receipts.c.operation_id)).scalars():
                    read_receipt(session, operation_id)
        return DatabaseCandidate(graph, signature)

    def finish(self, candidate=None):
        self.tracker.active = False
        self._base = None
        self._accepted = candidate
        self._epoch = self.tracker.epoch if candidate is not None else None
        self._changes = candidate.signature[0].total_changes if candidate is not None else None
