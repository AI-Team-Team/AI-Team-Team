"""Immutable per-entity values and deterministic schema-aware delta merging."""

import math
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Iterator

from sqlalchemy import Float, Integer, JSON, String

from ai_team_team.core.exceptions import StatePersistenceError
from ai_team_team.database.models import ACTIVITY_TABLES


MODEL_REQUEST_TABLES = frozenset({"model_requests", "audit_model_requests", "memory_index_requests"})
_REQUEST_OUTCOMES = {
    "unsent": frozenset({"pending"}),
    "confirmed_unsent": frozenset({"failed", "cancelled"}),
    "sent": frozenset({"pending", "completed", "failed", "cancelled", "uncertain"}),
    "unknown_sent": frozenset({"pending", "completed", "failed", "cancelled", "uncertain"}),
}


def valid_request_outcome(dispatch_state, outcome):
    """Separate admitted requests from terminal unsent or sent evidence."""
    return outcome in _REQUEST_OUTCOMES.get(dispatch_state, ())


@dataclass(frozen=True)
class FrozenObject(Mapping):
    items_tuple: tuple[tuple[str, Any], ...]

    def __post_init__(self):
        if type(self.items_tuple) is not tuple:
            raise ValueError("Frozen records require immutable object entries.")
        names = set()
        for entry in self.items_tuple:
            if type(entry) is not tuple or len(entry) != 2 or type(entry[0]) is not str or entry[0] in names:
                raise ValueError("Frozen record keys must be unique strings.")
            names.add(entry[0])
            self._validate_value(entry[1])

    @classmethod
    def _validate_value(cls, value):
        if isinstance(value, FrozenObject) or value is None or type(value) in (str, int, bool):
            return
        if type(value) is tuple:
            for item in value:
                cls._validate_value(item)
            return
        if type(value) is float and math.isfinite(value):
            return
        raise ValueError("Frozen record values cannot contain mutable or runtime objects.")

    def __iter__(self) -> Iterator[str]:
        return (key for key, _ in self.items_tuple)

    def __len__(self) -> int:
        return len(self.items_tuple)

    def __getitem__(self, key):
        for name, value in self.items_tuple:
            if name == key:
                return value
        raise KeyError(key)


def freeze(value):
    if isinstance(value, FrozenObject):
        return value
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("Durable JSON object keys must be strings.")
        # SQLAlchemy column names are immutable str subclasses; canonicalize
        # keys so directly constructed FrozenObject values can remain strict.
        return FrozenObject(tuple(sorted((str(key), freeze(item)) for key, item in value.items())))
    if isinstance(value, (list, tuple)):
        return tuple(freeze(item) for item in value)
    if value is None or type(value) in (str, int, bool):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    raise ValueError("Durable records accept only finite JSON values, not runtime bindings.")


def thaw(value):
    """Materialize only on a worker or at a deliberate runtime query boundary."""
    if isinstance(value, Mapping):
        return {key: thaw(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [thaw(item) for item in value]
    return value


@dataclass(frozen=True)
class DomainRecord:
    table_name: str
    values: FrozenObject

    @classmethod
    def capture(cls, table_name: str, values: Mapping):
        if table_name not in ACTIVITY_TABLES:
            raise ValueError("Unknown durable record domain.")
        table = ACTIVITY_TABLES[table_name]
        unknown = set(values) - set(table.columns.keys())
        if unknown:
            raise ValueError(f"Unknown fields for {table_name}: {sorted(unknown)}")
        normalized = {}
        for column in table.columns:
            value = values.get(column.name)
            if value is None:
                if not column.nullable:
                    raise ValueError(f"{table_name}.{column.name} is required.")
            elif isinstance(column.type, Integer):
                if type(value) is not int:
                    raise ValueError(f"{table_name}.{column.name} requires a strict integer.")
            elif isinstance(column.type, Float):
                if type(value) not in (int, float) or not math.isfinite(value):
                    raise ValueError(f"{table_name}.{column.name} requires a finite timestamp or duration.")
                value = float(value)
            elif isinstance(column.type, String):
                if type(value) is not str or not value.strip():
                    raise ValueError(f"{table_name}.{column.name} requires nonblank text.")
            elif not isinstance(column.type, JSON):
                raise ValueError("Unsupported durable SQL field type.")
            normalized[column.name] = freeze(value)
        version_key = "created_version" if table.info["append"] else "state_version"
        if normalized[version_key] < 1:
            raise ValueError("Durable record versions must be positive.")
        if table_name in MODEL_REQUEST_TABLES and not valid_request_outcome(normalized["dispatch_state"], normalized["outcome"]):
            raise ValueError("A model request has an impossible dispatch/outcome combination.")
        return cls(table_name, freeze(normalized))

    @property
    def identity(self):
        table = ACTIVITY_TABLES[self.table_name]
        return self.table_name, tuple(self.values[column.name] for column in table.primary_key)

    @property
    def version(self):
        return self.values["created_version" if ACTIVITY_TABLES[self.table_name].info["append"] else "state_version"]

    @property
    def receipt_key(self):
        return f"{self.table_name}:{self.identity[1]!r}@{self.version}"


def merge_records(earlier, later):
    merged = {record.identity: record for record in earlier}
    for record in later:
        previous = merged.get(record.identity)
        if previous is not None:
            if ACTIVITY_TABLES[record.table_name].info["append"] or record.version == previous.version:
                if previous != record:
                    raise StatePersistenceError("Conflicting bodies for the same durable record identity/version.")
            if record.version < previous.version:
                continue
            validate_update(previous, record)
        merged[record.identity] = record
    return tuple(merged.values())


def record_digest(records):
    """Hash accepted domain values on a worker, not on the event loop."""
    values = sorted(((record.table_name, thaw(record.values)) for record in records),
                    key=lambda item: (item[0], json.dumps(item[1], sort_keys=True)))
    return hashlib.sha256(json.dumps(values, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


IMMUTABLE_FIELDS = {
    "activity_admissions": "agent_id runtime_generation scope_kind scope_team_id accepted_at",
    "activity_invocations": "admission_id agent_id runtime_generation scope_kind scope_team_id context_version started_at",
    "model_requests": "frame_id agent_id model_alias attempt_index input_version created_at request_budget sequence_budget",
    "memory_index_requests": "segment_id beneficiary_agent_id source_version model_alias attempt_index input_digest created_at",
    "model_token_claims": "model_request_id audit_request_id index_request_id model_alias prompt_budget output_budget",
    "direct_relationships": "agent_a_id agent_b_id",
    "friendship_requests": "relationship_id sender_agent_id recipient_agent_id generation created_at",
    "chat_streams": "team_id relationship_id",
    "membership_intervals": "team_id agent_id stream_id join_event_id",
    "chat_personal_views": "agent_id message_id interval_id",
    "executions": "agent_id invocation_id scope_kind scope_team_id tool_name effects runtime_generation created_at",
    "execution_controls": "execution_id requester_agent_id operation requested_at",
    "sleep_plans": "agent_id latest_wake_seconds minimum_seconds maximum_seconds",
    "audit_runs": "subject_agent_id subject_team_id temporary_team_id template electorate runtime_generation created_at deadline token_budget",
    "audit_model_requests": "audit_id scoped_agent_id invocation_id frame_id input_version model_alias attempt_index created_at request_budget sequence_budget",
    "audit_execution_evidence": "audit_id scoped_agent_id tool_name effects runtime_generation attempt_index",
    "publication_manifests": "checkpoint_id previous_generation target_generation staged_files recovery_operation_id prepared_at",
}


def validate_update(previous, later):
    """Captured authority is immutable even when its factual progress changes."""
    if previous == later:
        return
    for field in IMMUTABLE_FIELDS.get(previous.table_name, "").split():
        if previous.values[field] != later.values[field]:
            raise StatePersistenceError(f"Captured {previous.table_name}.{field} cannot be rewritten.")
    if previous.table_name == "membership_intervals" and previous.values["leave_event_id"] is not None:
        if later.values["leave_event_id"] != previous.values["leave_event_id"]:
            raise StatePersistenceError("A closed membership interval cannot reopen or change departure.")
    monotonic = {
        "chat_streams": ("next_position",),
        "agent_activities": ("arrival_generation", "presentation_generation", "context_version"),
        "direct_relationships": ("generation",),
        "health_incidents": ("occurrence_count", "latest_at"),
    }
    if any(later.values[field] < previous.values[field] for field in monotonic.get(previous.table_name, ())):
        raise StatePersistenceError("An authoritative ordering or occurrence cursor cannot move backwards.")
    if previous.table_name == "activity_admissions" and previous.values["disposition"] != "admitted":
        if later.values["disposition"] != previous.values["disposition"]:
            raise StatePersistenceError("An ended personal admission cannot be reopened.")
    if previous.table_name == "activity_invocations" and previous.values["boundary_at"] is not None:
        if any(previous.values[field] != later.values[field] for field in ("boundary_at", "interrupted")):
            raise StatePersistenceError("A confirmed invocation boundary cannot reopen or change its outcome.")
    if previous.table_name == "chat_message_projections" and previous.values["withdrawal_id"] is not None:
        if later.values["withdrawal_id"] != previous.values["withdrawal_id"]:
            raise StatePersistenceError("A confirmed message withdrawal cannot be removed or replaced.")
    if previous.table_name == "chat_personal_views" and previous.values["view_kind"] == "frozen":
        if any(previous.values[field] != later.values[field] for field in ("view_kind", "revision_id", "withdrawal_id", "departure_cutoff")):
            raise StatePersistenceError("A frozen personal view cannot be rewritten by later shared updates.")
    if previous.table_name in {"executions", "audit_execution_evidence"}:
        if previous.values["status"] in {"completed", "failed", "cancelled"} and previous.values["status"] != later.values["status"]:
            raise StatePersistenceError("A confirmed execution outcome cannot be reversed.")
    if previous.table_name == "model_token_claims" and previous.values["settlement"] != "reserved":
        if any(previous.values[field] != later.values[field] for field in ("settlement", "actual_usage", "settled_at")):
            raise StatePersistenceError("A confirmed token settlement cannot be rewritten.")


def dependency_closure(records, retained):
    """Capture concrete prerequisites without consulting mutable worker state."""
    captured = {record.identity: record for record in records}
    pending = list(records)
    while pending:
        record = pending.pop()
        table = ACTIVITY_TABLES[record.table_name]
        for constraint in table.foreign_key_constraints:
            target = constraint.referred_table
            if target.name not in ACTIVITY_TABLES:
                continue
            values = tuple(record.values[element.parent.name] for element in constraint.elements)
            if any(value is None for value in values):
                continue
            key = target.name, values
            if key in captured:
                continue
            prerequisite = retained.get(key)
            if prerequisite is None:
                raise StatePersistenceError(f"Missing concrete durable prerequisite: {target.name}.")
            captured[key] = prerequisite
            pending.append(prerequisite)
    return tuple(captured.values())
