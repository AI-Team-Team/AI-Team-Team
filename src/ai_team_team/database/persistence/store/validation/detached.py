"""Incremental physical validation over accepted, value-only volatile records."""

import threading
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from sqlalchemy import Float, Integer, JSON

from ai_team_team.core.exceptions import StateRestoreError
from ai_team_team.database.models import ACTIVITY_TABLES, Base
from ai_team_team.database.persistence.records import DomainRecord, thaw

from .graph import SOURCE_COLUMNS, ValidationGraph, immutable_rows, validate_graph


def source_rows(state):
    """Match the full reference validator's retained SQL source projections."""
    sources = {
        "agents": {row["agent_id"]: row for row in state["agents"]},
        "libraries": {row["lib_id"]: row for row in state.get("libraries", ())},
        "teams": {row["team_id"]: row for row in state["teams"]},
        "agent_memory_segments": {row["segment_id"]: row for row in state.get("memory_segments", ())},
        "system_memory_events": {row["event_id"]: row for row in state.get("memory_events", ())},
        "agent_inbox": {mail["message_id"]: mail for inbox in state.get("agent_inboxes", {}).values() for mail in inbox},
        "governance_cases": {row["round_id"]: row for row in state.get("governance_rounds", ())},
    }
    result = {}
    for name, rows in sources.items():
        table = Base.metadata.tables[name]
        result[name] = []
        for identity, source in rows.items():
            values = {}
            for column in table.columns:
                if column.nullable:
                    values[column.name] = thaw(source.get(column.name))
                elif isinstance(column.type, JSON):
                    values[column.name] = thaw(source.get(column.name, {}))
                elif isinstance(column.type, Integer):
                    values[column.name] = source.get(column.name, 1)
                elif isinstance(column.type, Float):
                    values[column.name] = source.get(column.name, 0.0)
                else:
                    values[column.name] = source.get(column.name, identity)
            if name == "governance_cases":
                principal = source["principal"]
                values.update(case_id=identity, data=thaw(source),
                    principal_agent_id=principal["principal_id"] if principal["kind"] == "agent" else None,
                    principal_team_id=principal["principal_id"] if principal["kind"] == "agent_team" else None)
            if name == "teams":
                values.update(creator_agent_id=source["creator_id"] if source["creator_type"] == "agent" else None,
                    creator_team_id=source["creator_id"] if source["creator_type"] == "team" else None)
            result[name].append(values)
        result[name] = immutable_rows(result[name])
    return result


@dataclass(frozen=True)
class DetachedCandidate:
    generation: int
    records: Mapping[tuple[str, tuple], DomainRecord]
    physical_sources: Mapping[str, tuple[Mapping[str, Any], ...]]
    graph: ValidationGraph
    checked_tables: frozenset[str]


class DetachedValidationCache:
    """Prepare privately; accept only after the authoritative commit receipt."""

    def __init__(self):
        self._lock = threading.RLock()
        self._generation = 0
        self._accepted = None

    def invalidate(self):
        with self._lock:
            self._generation += 1
            self._accepted = None

    def accept(self, candidate):
        with self._lock:
            if candidate.generation == self._generation:
                self._accepted = candidate
                self._generation += 1

    def prepare(self, state):
        with self._lock:
            baseline, generation = self._accepted, self._generation
        try:
            return self._prepare(state, baseline, generation)
        except StateRestoreError:
            raise
        except Exception as exc:
            raise StateRestoreError("Invalid durable staging graph.") from exc

    @staticmethod
    def _prepare(state, baseline, generation):
        index, changed = {}, set()
        previous = baseline.records if baseline is not None else {}
        grouped = dict(baseline.graph.records) if baseline is not None else {name: () for name in ACTIVITY_TABLES}
        for record in state.get("records", ()):
            if not isinstance(record, DomainRecord):
                raise ValueError("Invalid immutable durable record.")
            if record.identity in index:
                raise ValueError("Duplicate durable record identity.")
            index[record.identity] = record
            # Equality alone is not a trust boundary: bool and int may compare
            # equal, and a caller may have constructed an unvalidated record.
            if previous.get(record.identity) is not record:
                if DomainRecord.capture(record.table_name, record.values) != record:
                    raise ValueError("Invalid immutable durable record.")
                changed.add(record.table_name)
        changed.update(identity[0] for identity in previous.keys() - index.keys())
        for name in changed:
            grouped[name] = immutable_rows(thaw(record.values) for record in index.values() if record.table_name == name)
        physical = source_rows(state) if index else {}
        old_sources = baseline.physical_sources if baseline is not None else {}
        changed_sources = {name for name in physical if physical[name] != old_sources.get(name)}
        sources = {name: () for name in SOURCE_COLUMNS}
        for name, columns in SOURCE_COLUMNS.items():
            if name in physical:
                sources[name] = immutable_rows({column: row[column] for column in columns} for row in physical[name])
        graph = ValidationGraph(MappingProxyType(grouped), MappingProxyType(sources))
        if index:
            # Every reference is checked, including reverse effects of deletion.
            for record in index.values():
                for constraint in ACTIVITY_TABLES[record.table_name].foreign_key_constraints:
                    target = constraint.referred_table
                    values = tuple(record.values[element.parent.name] for element in constraint.elements)
                    if any(value is None for value in values):
                        continue
                    exists = ((target.name, values) in index if target.name in ACTIVITY_TABLES
                        else any(tuple(row[column.name] for column in target.primary_key) == values for row in physical.get(target.name, ())))
                    if not exists:
                        raise ValueError(f"Missing concrete staging reference to {target.name}.")
            from ..detached_validation import _validation_session
            with _validation_session() as session:
                # Native CHECK/unique/partial-index rules are retained. Only
                # changed table groups are replayed, using bulk inserts rather
                # than a SELECT and INSERT for every historical record.
                for name in sorted(changed | changed_sources):
                    rows = grouped[name] if name in ACTIVITY_TABLES else physical[name]
                    if rows:
                        session.execute(Base.metadata.tables[name].insert(), [dict(row) for row in rows])
            memberships = {(row["team_id"], person) for row in state["teams"] for person in row.get("members", ())}
            validate_graph(graph, current_memberships=memberships, partial_memberships=True)
        return DetachedCandidate(generation, MappingProxyType(index), MappingProxyType(physical), graph,
                                 frozenset(changed | changed_sources))
