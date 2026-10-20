"""Dependency-complete records for independent episodic-memory deltas."""

from typing import Any, Dict

from ..agent import Agent
from ..exceptions import StatePersistenceError
from ..memory import MemoryIndexStatus
from ..team import AgentTeam
from ai_team_team.database.models import ACTIVITY_TABLES
from ai_team_team.database.persistence.records import dependency_closure


def capture_execution_dependencies(manager, agent_ids, memory_records):
    """Retain concrete observation sources even on a first partial checkpoint."""
    execution_ids = {message["source_execution_id"]
        for owner in agent_ids if owner in manager._agents_by_id
        for message in manager._agents_by_id[owner].messages if message.get("source_execution_id")}
    execution_ids.update(event["source_execution_id"] for event in memory_records["memory_events"]
                         if event.get("source_execution_id"))
    selected = []
    for execution_id in execution_ids:
        _require(manager._records.index, ("executions", (execution_id,)), "observation execution")
    for row in manager._records.snapshot():
        if row.table_name in {"executions", "execution_attempts", "execution_payloads", "execution_observations", "execution_controls"} and row.values["execution_id"] in execution_ids:
            selected.append(row)
    records = dependency_closure(selected, manager._records.index)
    agents, teams, libraries = set(), set(), set()
    for record in records:
        for constraint in ACTIVITY_TABLES[record.table_name].foreign_key_constraints:
            target = constraint.referred_table.name
            values = {record.values[item.parent.name] for item in constraint.elements}
            values.discard(None)
            if target == "agents":
                agents.update(values)
            elif target == "teams":
                teams.update(values)
        if record.table_name == "executions":
            libraries.update(source["lib_id"] for source in record.values["source_references"] or () if source["kind"] == "library")
    return records, agents, teams, libraries


def capture_memory_records(manager: Any, dirty: Dict[str, Any]) -> Dict[str, list]:
    """Capture memory records and their sources under the journal's shared lock."""
    memory = manager._memory
    with memory._lock:
        event_ids = set(memory.events) if dirty["full"] else set(dirty["memory_events"])
        segment_ids = set(memory.segments) if dirty["full"] else set(dirty["memory_segments"])
        card_ids = set(memory.cards) if dirty["full"] else set(dirty["memory_cards"])
        reference_ids = (
            set(memory.references) if dirty["full"] else set(dirty["memory_references"])
        )

        for reference_id in reference_ids:
            reference = memory.references.get(reference_id)
            if reference is not None:
                _require(memory.cards, reference.memory_id, "Memory Card")
                card_ids.add(reference.memory_id)
        for memory_id in card_ids:
            card = memory.cards.get(memory_id)
            if card is not None:
                _require(memory.segments, card.segment_id, "memory segment")
                segment_ids.add(card.segment_id)
        for segment_id in segment_ids:
            segment = memory.segments.get(segment_id)
            if segment is None:
                continue
            for event_id in segment.source_event_ids:
                _require(memory.events, event_id, "Journal event")
                event_ids.add(event_id)
            if segment.status is MemoryIndexStatus.INDEXED:
                memory_id = memory._card_id_by_turn.get(segment.turn_id)
                card = _require(memory.cards, memory_id, "indexed Memory Card")
                if card.segment_id != segment_id:
                    raise StatePersistenceError(
                        f"Memory Card {memory_id!r} references the wrong segment."
                    )
                card_ids.add(memory_id)

        # Journal events remain immutable and may safely be included in later deltas.
        events = [memory.events[event_id] for event_id in event_ids if event_id in memory.events]
        return {
            "memory_events": [
                event.model_dump(mode="json")
                for event in sorted(events, key=lambda item: item.sequence)
            ],
            "memory_segments": [
                memory.segments[segment_id].model_dump(mode="json")
                for segment_id in sorted(segment_ids)
                if segment_id in memory.segments
            ],
            "memory_cards": [
                memory.cards[memory_id].model_dump(mode="json")
                for memory_id in sorted(card_ids)
                if memory_id in memory.cards
            ],
            "memory_references": [
                memory.references[reference_id].model_dump(mode="json")
                for reference_id in sorted(reference_ids)
                if reference_id in memory.references
            ],
        }


def collect_memory_identity_dependencies(
    manager: Any, records: Dict[str, list], *, extra_agents=(), extra_teams=(), agent_lookup=None
) -> tuple[set[str], set[str]]:
    """Include insert-only identity and provenance targets, not historical event owners."""
    agent_ids = {
        record["agent_id"]
        for key in ("memory_segments", "memory_cards", "memory_references")
        for record in records[key]
    }
    team_ids = {
        record["origin_team_id"]
        for key in ("memory_segments", "memory_cards")
        for record in records[key]
        if record["origin_team_id"] is not None
    }
    agent_ids.update(extra_agents)
    team_ids.update(extra_teams)
    pending_agents = list(agent_ids)
    pending_teams = list(team_ids)
    seen_agents: set[str] = set()
    seen_teams: set[str] = set()
    while pending_agents or pending_teams:
        while pending_agents:
            agent_id = pending_agents.pop()
            if agent_id in seen_agents:
                continue
            agent = _require(manager._agents_by_id if agent_lookup is None else agent_lookup, agent_id, "memory owner Agent")
            seen_agents.add(agent_id)
            for message in agent.messages:
                team_id = message.get("team_id")
                if team_id is not None and team_id not in team_ids:
                    team_ids.add(team_id)
                    pending_teams.append(team_id)
        while pending_teams:
            team_id = pending_teams.pop()
            if team_id in seen_teams:
                continue
            team = _require(manager.teams, team_id, "memory provenance AgentTeam")
            if team.team_kind != "ordinary":
                raise StatePersistenceError(
                    f"Memory provenance cannot retain temporary team {team_id!r}."
                )
            seen_teams.add(team_id)
            related_agents = {member.agent_id for member in team.members}
            if isinstance(team.creator, Agent):
                related_agents.add(team.creator.agent_id)
            pending_agents.extend(related_agents - agent_ids)
            agent_ids.update(related_agents)
            related_teams = set()
            if team.parent_team is not None:
                related_teams.add(team.parent_team.team_id)
            if isinstance(team.creator, AgentTeam):
                related_teams.add(team.creator.team_id)
            pending_teams.extend(related_teams - team_ids)
            team_ids.update(related_teams)
    return agent_ids, team_ids


def _require(records: dict, identifier: Any, kind: str) -> Any:
    record = records.get(identifier)
    if record is None:
        raise StatePersistenceError(
            f"Cannot persist episodic memory: missing {kind} {identifier!r}."
        )
    return record
