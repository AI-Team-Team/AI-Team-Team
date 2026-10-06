"""Public, detached directory records for Agent and AgentTeam discovery."""

from typing import Annotated, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


EntityType = Literal["agent", "agent_team"]
EntitySelection = Literal["agent", "agent_team", "all"]


class AgentDirectoryRecord(BaseModel):
    """An eligible Agent's public identity, not its private runtime state."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    entity_type: Literal["agent"] = "agent"
    agent_id: str
    name: str
    role: str
    role_description: str


class AgentTeamDirectoryRecord(BaseModel):
    """An ordinary AgentTeam's public purpose, progress, and topology position."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    entity_type: Literal["agent_team"] = "agent_team"
    team_id: str
    team_purpose: str
    team_progress: str
    parent_team_id: Optional[str]
    depth: int = Field(ge=1)


EntityDirectoryRecord = Annotated[
    Union[AgentDirectoryRecord, AgentTeamDirectoryRecord], Field(discriminator="entity_type")
]


class EntityDiscoveryResult(BaseModel):
    """One live-directory query, with one-based inclusive entity positions."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    requested_start_index: int = Field(ge=1)
    requested_end_index: int = Field(ge=1)
    actual_start_index: Optional[int]
    actual_end_index: Optional[int]
    maximum_index: int = Field(ge=0)
    total_results: int = Field(ge=0)
    returned_count: int = Field(ge=0)
    items: List[EntityDirectoryRecord]
