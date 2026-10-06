"""Read-only directory selection, keyword matching, and position pagination."""

from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..discovery import (
    AgentDirectoryRecord,
    AgentTeamDirectoryRecord,
    EntityDirectoryRecord,
    EntityDiscoveryResult,
    EntitySelection,
    EntityType,
)
from ..exceptions import ATTException


class _DirectoryQuery(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    entity_type: EntitySelection = "all"
    start_index: int = Field(default=1, ge=1)
    end_index: Optional[int] = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_range(self):
        if self.end_index is not None and self.end_index < self.start_index:
            raise ValueError("end_index cannot precede start_index.")
        return self


class _DirectorySearch(_DirectoryQuery):
    keywords: List[str] = Field(min_length=1)

    @field_validator("keywords")
    @classmethod
    def validate_keywords(cls, keywords):
        if any(not keyword.strip() for keyword in keywords):
            raise ValueError("keywords must not contain empty or blank strings.")
        return list(dict.fromkeys(keyword.strip().casefold() for keyword in keywords))


class _DirectoryInspection(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    entity_type: EntityType
    entity_id: str = Field(min_length=1)


class DiscoveryService:
    """Projects only public fields without borrowing Agent invocation locks."""

    def __init__(self, manager: Any) -> None:
        self.manager = manager

    def _capture(
        self, entity_type: EntitySelection = "all", entity_id: Optional[str] = None
    ) -> List[EntityDirectoryRecord]:
        # Capture uses the same lock as Agent registration/lifecycle, team
        # metadata/topology commits, and restore publication. Synchronous host
        # callbacks can therefore query from a worker without seeing a partial
        # registry update. No Agent invocation lock or await is needed here.
        with self.manager._topology_lock:
            teams = tuple(self.manager.teams.values())
            audit_ids = {
                agent.agent_id
                for team in teams
                if team.team_kind == "supervisory"
                for agent in team.members
            }
            candidates = (
                self.manager._agents_by_id.values()
                if entity_id is None
                else (self.manager._agents_by_id.get(entity_id),)
            )
            agents = (
                [
                    (agent.agent_id, agent.name, agent.role, agent.role_description)
                    for agent in candidates
                    if agent is not None
                    and agent.lifecycle_state == "active"
                    and agent.agent_id not in audit_ids
                ]
                if entity_type != "agent_team"
                else []
            )
            team_fields = (
                {
                    team.team_id: (
                        team.team_purpose,
                        team.team_progress,
                        team.parent_team.team_id if team.parent_team is not None else None,
                    )
                    for team in teams
                    if team.team_kind == "ordinary"
                }
                if entity_type != "agent"
                else {}
            )

        # Recompute depth from the captured public map. Do not mutate live
        # derived caches or read runtime objects again after the capture.
        depths = {}
        selected_team_ids = [
            identifier for identifier in team_fields if entity_id is None or identifier == entity_id
        ]
        for team_id in selected_team_ids:
            path = []
            seen = set()
            cursor = team_id
            while cursor is not None and cursor not in depths:
                if cursor in seen or cursor not in team_fields:
                    raise ATTException("Discovery encountered an inconsistent AgentTeam topology.")
                seen.add(cursor)
                path.append(cursor)
                cursor = team_fields[cursor][2]
            depth = depths.get(cursor, 0)
            for identifier in reversed(path):
                depth += 1
                depths[identifier] = depth
        records: List[EntityDirectoryRecord] = [
            AgentDirectoryRecord(
                agent_id=agent_id, name=name, role=role, role_description=description
            )
            for agent_id, name, role, description in agents
        ]
        records.extend(
            AgentTeamDirectoryRecord(
                team_id=team_id,
                team_purpose=purpose,
                team_progress=progress,
                parent_team_id=parent_id,
                depth=depths[team_id],
            )
            for team_id in selected_team_ids
            for purpose, progress, parent_id in (team_fields[team_id],)
        )
        return records

    @staticmethod
    def sort_key(record):
        label = record.name if record.entity_type == "agent" else record.team_id
        identifier = record.agent_id if record.entity_type == "agent" else record.team_id
        case_order = tuple(0 if char.isupper() else 1 if char.islower() else 2 for char in label)
        return label.casefold(), case_order, label, record.entity_type, identifier

    def _query(self, query: _DirectoryQuery) -> EntityDiscoveryResult:
        records = self._capture(query.entity_type)
        if isinstance(query, _DirectorySearch):
            records = [
                record
                for record in records
                if any(
                    keyword in str(value).casefold()
                    for field, value in record.model_dump().items()
                    if field != "entity_type" and value is not None
                    for keyword in query.keywords
                )
            ]
        records.sort(key=self.sort_key)
        total = len(records)
        end = query.end_index if query.end_index is not None else query.start_index + 29
        items = records[query.start_index - 1 : end]
        return EntityDiscoveryResult(
            requested_start_index=query.start_index,
            requested_end_index=end,
            actual_start_index=query.start_index if items else None,
            actual_end_index=min(end, total) if items else None,
            maximum_index=total,
            total_results=total,
            returned_count=len(items),
            items=items,
        )

    def list_entities(
        self,
        entity_type: EntitySelection = "all",
        start_index: int = 1,
        end_index: Optional[int] = None,
    ) -> EntityDiscoveryResult:
        return self._query(
            _DirectoryQuery(entity_type=entity_type, start_index=start_index, end_index=end_index)
        )

    def search_entities(
        self,
        keywords: List[str],
        entity_type: EntitySelection = "all",
        start_index: int = 1,
        end_index: Optional[int] = None,
    ) -> EntityDiscoveryResult:
        return self._query(
            _DirectorySearch(
                keywords=keywords,
                entity_type=entity_type,
                start_index=start_index,
                end_index=end_index,
            )
        )

    def inspect_entity(self, entity_type: EntityType, entity_id: str) -> EntityDirectoryRecord:
        query = _DirectoryInspection(entity_type=entity_type, entity_id=entity_id)
        for record in self._capture(query.entity_type, query.entity_id):
            identifier = record.agent_id if record.entity_type == "agent" else record.team_id
            if record.entity_type == query.entity_type and identifier == query.entity_id:
                return record
        # Do not disclose whether an ID belongs to an excluded identity.
        raise KeyError("No discoverable entity matches the requested type and stable ID.")
