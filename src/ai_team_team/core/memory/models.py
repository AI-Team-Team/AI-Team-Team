"""Strict models for journal, catalog, and working-memory references."""

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class MemoryIndexStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    INDEXED = "indexed"
    FAILED = "failed"


class MemoryCardStatus(str, Enum):
    ACTIVE = "active"
    FORGOTTEN = "forgotten"


class SystemMemoryEvent(BaseModel):
    """One immutable, privacy-filtered event in the system journal."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    event_id: str = Field(min_length=1)
    sequence: int = Field(ge=1)
    event_type: str = Field(min_length=1)
    agent_id: Optional[str] = None
    agent_name_snapshot: Optional[str] = None
    team_id: Optional[str] = None
    discussion_id: Optional[str] = None
    turn_id: Optional[str] = None
    role: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)
    redacted: bool = False
    created_at: float


class AgentMemorySegment(BaseModel):
    """A deterministic, sanitized Agent-turn segment awaiting catalog indexing."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        validate_assignment=True,
    )

    segment_id: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    turn_id: str = Field(min_length=1)
    origin_team_id: Optional[str] = None
    discussion_id: Optional[str] = None
    source_event_ids: List[str] = Field(min_length=1)
    recall_content: str = Field(min_length=1)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: MemoryIndexStatus = MemoryIndexStatus.PENDING
    attempts: int = Field(default=0, ge=0)
    last_error_kind: Optional[str] = None
    created_at: float
    updated_at: float


class AgentMemoryCard(BaseModel):
    """Agent-owned, AI-visible metadata for one indexed turn."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        validate_assignment=True,
    )

    memory_id: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    turn_id: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1, max_length=1000)
    tags: List[str] = Field(min_length=1)
    origin_team_id: Optional[str] = None
    discussion_id: Optional[str] = None
    segment_id: str = Field(min_length=1)
    status: MemoryCardStatus = MemoryCardStatus.ACTIVE
    version: int = Field(default=1, ge=1)
    created_at: float
    updated_at: float


class RetainedMemoryReference(BaseModel):
    """A compact memory reference deliberately retained in working context."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        validate_assignment=True,
    )

    reference_id: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    memory_id: str = Field(min_length=1)
    note: str = Field(min_length=1, max_length=1000)
    created_at: float


class MemorySearchItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    memory_id: str
    title: str
    summary: str
    tags: List[str]
    origin_team_id: Optional[str] = None
    discussion_id: Optional[str] = None
    created_at: float


class MemorySearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    items: List[MemorySearchItem]
    next_cursor: Optional[str] = None


class MemoryRecallResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    memory_id: str
    origin_team_id: Optional[str] = None
    discussion_id: Optional[str] = None
    content: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    truncated: bool = False


class MemoryOperationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    status: str
    memory_id: str
    reason: str = ""
