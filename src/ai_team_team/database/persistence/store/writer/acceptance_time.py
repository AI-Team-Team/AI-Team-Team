"""Finalize position timestamps after SQL preparation, before commit receipts."""

from dataclasses import replace

from sqlalchemy import and_, select

from ai_team_team.core.exceptions import StatePersistenceError
from ai_team_team.database.models import ACTIVITY_TABLES, MigrationRequestModel
from ai_team_team.database.persistence.acceptance_time import AcceptedTimedWrite
from ai_team_team.database.persistence.records import thaw
from ..records import read_receipt


class AcceptanceTimeWriteMixin:
    @staticmethod
    def _bind_acceptance_times(session, snapshot, reader):
        bindings = snapshot.get("_acceptance_times", ())
        operations = tuple(snapshot.get("_operations", ()))
        if not bindings:
            return operations, ()
        if reader is None:
            raise StatePersistenceError("A timed domain commit has no registered clock source.")
        captured = {row.identity: row for row in snapshot.get("records", ())}
        timestamps = []
        for binding in bindings:
            if read_receipt(session, binding.operation_id) is not None:
                raise StatePersistenceError("An accepted transition cannot acquire a new acceptance time.")
            operation = next((item for item in operations if item.operation_id == binding.operation_id), None)
            if operation is None or any(captured.get(row.identity) != row for row in binding.template.records):
                raise StatePersistenceError("Acceptance-time binding lost its exact operation or record values.")
            migration = session.get(MigrationRequestModel, binding.request_id)
            if migration is None or migration.state_version < operation.state_version:
                raise StatePersistenceError("Acceptance-time binding requires this transaction's migration projection.")
            reading = reader(binding.operation_id)
            timestamp = reading.wall_time
            records, digest = binding.template.bind(timestamp)
            fields = {key: dict(names) for key, names in binding.template.fields}
            for row in records:
                table = ACTIVITY_TABLES[row.table_name]
                predicate = and_(*(column == row.values[column.name] for column in table.primary_key))
                current = session.execute(select(table).where(predicate)).mappings().one()
                original = captured[row.identity]
                if dict(current) != thaw(original.values):
                    raise StatePersistenceError("A prepared transition changed before its time could bind.")
                session.execute(table.update().where(predicate).values(
                    **{name: row.values[name] for name in fields[row.identity]}))
            migration.data = {**migration.data, "resolved_at": timestamp}
            session.flush()
            operations = tuple(replace(item, record_digest=digest) if item is operation else item for item in operations)
            timestamps.append((binding.operation_id, reading))
        return operations, tuple(timestamps)

    @staticmethod
    def _accepted_write(receipts, timestamps):
        return AcceptedTimedWrite(tuple(receipts), timestamps) if timestamps else receipts
