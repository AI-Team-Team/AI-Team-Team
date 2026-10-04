"""Dependency-complete records for independent episodic-memory deltas."""

from typing import Any, Dict

from ..agent import Agent
from ..exceptions import StatePersistenceError
from ..memory import MemoryIndexStatus
from ..team import AgentTeam


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
    manager: Any, records: Dict[str, list]
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
    pending_agents = list(agent_ids)
    pending_teams = list(team_ids)
    seen_agents: set[str] = set()
    seen_teams: set[str] = set()
    while pending_agents or pending_teams:
        while pending_agents:
            agent_id = pending_agents.pop()
            if agent_id in seen_agents:
                continue
            agent = _require(manager._agents_by_id, agent_id, "memory owner Agent")
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
