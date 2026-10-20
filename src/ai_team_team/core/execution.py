"""Owner-only execution projections contain facts, never executable bindings."""

from typing import Literal

from pydantic import Field

from .activity.contracts.base import ContractRecord, Identifier
from .activity.contracts.execution import AttentionState, ExecutionState, HealthState
from .activity.contracts.scope import OperationScope


class ResourceClaim(ContractRecord):
    namespace: Identifier
    resource_id: Identifier
    path: str = ""
    access: Literal["read", "write"] = "write"
    subtree: bool = False


class TaskView(ContractRecord):
    execution_id: Identifier
    owner_agent_id: Identifier
    scope: OperationScope
    tool_name: Identifier
    description: str = ""
    labels: tuple[str, ...] = ()
    execution_state: ExecutionState
    health_state: HealthState
    attention_state: AttentionState
    visibility: Literal["foreground", "explicit_background", "detached"]
    outcome_unconfirmed: bool
    created_at: float
    started_at: float | None = None
    finished_at: float | None = None
    cancellation_requested: bool = False
    result_available: bool = False


class TaskPage(ContractRecord):
    items: tuple[TaskView, ...]
    total_count: int = Field(ge=0)
    next_cursor: str | None = None


class TaskControlResult(ContractRecord):
    execution_id: Identifier
    status: Literal["CANCELLED", "REQUESTED", "UNCONFIRMED", "ALREADY_TERMINAL", "ACKNOWLEDGED"]
    durability: Literal["durable", "volatile"]
    state_version: int = Field(gt=0)
