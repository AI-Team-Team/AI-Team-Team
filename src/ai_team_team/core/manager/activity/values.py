"""Live activity coordination values; none are serialized as Python objects."""

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from ai_team_team.core.activity.contracts import PersonalScope
from ai_team_team.core.exceptions import LLMGenerationError
from ai_team_team.database.models import ACTIVITY_TABLES
from ai_team_team.database.persistence.records import DomainRecord, thaw


def identifier(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


class SystemClock:
    monotonic = staticmethod(time.monotonic)
    wall_time = staticmethod(time.time)
    sleep = staticmethod(asyncio.sleep)


class ModelUnavailable(LLMGenerationError):
    """Resource evidence, never a voluntary idle choice or a personal answer."""

    def __init__(self, reason: str, *, recoverable: bool = False, earliest: float | None = None):
        super().__init__(reason)
        self.recoverable = recoverable
        self.earliest = earliest


@dataclass
class Session:
    agent_id: str
    admission_id: str
    generation: int
    scope: Any = field(default_factory=PersonalScope)
    context_version: int = 0
    active: bool = True
    queued: bool = False
    running: bool = False
    intent: str = "continuing"
    availability: str = "ready"
    invocation_id: str | None = None
    frame_id: str | None = None
    frame_notices: tuple = ()
    pending_intent: Any = None
    pending_scope: Any = None
    answer: str = ""
    failure: BaseException | None = None
    sleep_id: str | None = None
    sleep_deadline: float | None = None
    recovery_deadline: float | None = None
    pending_event_ids: set = field(default_factory=set)
    interaction_waiters: list = field(default_factory=list)
    prepared_chat_reads: dict = field(default_factory=dict)
    pending_chat_read_acknowledgements: list = field(default_factory=list)


def capture(manager, table: str, **values) -> DomainRecord:
    schema = ACTIVITY_TABLES[table]
    key = tuple(values[column.name] for column in schema.primary_key)
    previous = manager._records.index.get((table, key))
    data = thaw(previous.values) if previous else {}
    data.update(values)
    for column in schema.columns:
        if column.nullable:
            data.setdefault(column.name, None)
    data["created_version" if schema.info["append"] else "state_version"] = (
        previous.version
        if previous and schema.info["append"]
        else previous.version + 1
        if previous
        else 1
    )
    return DomainRecord.capture(table, data)


def scope_fields(scope) -> dict:
    return {"scope_kind": scope.kind, "scope_team_id": getattr(scope, "team_id", None)}
