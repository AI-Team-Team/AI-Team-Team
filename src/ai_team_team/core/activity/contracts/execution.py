"""Declared effects are independent of retry safety and elapsed wait time."""

from typing import Literal

from pydantic import Field, model_validator

from .base import ContractRecord, Identifier, PositiveInteger
from .scope import OperationScope


Effect = Literal[
    "read_only", "artifact_write", "domain_mutation", "self_modification", "undeclared"
]
ExecutionState = Literal["queued", "running", "completed", "failed", "cancelled"]
HealthState = Literal["healthy", "degraded", "stalled", "error", "unknown"]
AttentionState = Literal["none", "required", "acknowledged"]


class ToolExecutionContract(ContractRecord):
    """Registration metadata; authorization is still checked at execution time."""

    effects: tuple[Effect, ...] = Field(min_length=1)
    background_allowed: bool
    required_scope: Literal["personal", "agent_team", "either"]
    mutation_safety: Literal["none", "managed_lease", "isolated", "trusted_host"] = "none"
    cancellation: Literal["none", "cooperative", "provider", "isolated"] = "none"
    health_signals: tuple[Literal["heartbeat", "progress", "provider"], ...] = ()

    @model_validator(mode="after")
    def check_effects(self) -> "ToolExecutionContract":
        if len(set(self.effects)) != len(self.effects):
            raise ValueError("Tool effects must be unique.")
        if len(set(self.health_signals)) != len(self.health_signals):
            raise ValueError("Health capabilities must be unique.")
        if self.background_allowed:
            if {"self_modification", "undeclared"}.intersection(self.effects):
                raise ValueError(
                    "Self-modifying and undeclared tools cannot run in the background."
                )
            if {"artifact_write", "domain_mutation"}.intersection(self.effects):
                if self.mutation_safety == "none":
                    raise ValueError("Detachable mutations require an explicit safety contract.")
        return self


class ExecutionObservation(ContractRecord):
    execution_id: Identifier
    owner_agent_id: Identifier
    scope: OperationScope
    runtime_generation: PositiveInteger
    execution_state: ExecutionState
    health_state: HealthState
    attention_state: AttentionState
    outcome_unconfirmed: bool = False
    cancellation_requested: bool = False

    @model_validator(mode="after")
    def preserve_confirmed_terminal_outcomes(self) -> "ExecutionObservation":
        if self.outcome_unconfirmed and self.execution_state in {
            "completed",
            "failed",
            "cancelled",
        }:
            raise ValueError("A confirmed terminal outcome cannot become interruption uncertainty.")
        return self


class ActivityAdmission(ContractRecord):
    admission_id: Identifier
    agent_id: Identifier
    status: Literal["QUEUED", "COALESCED"]
    durability: Literal["durable", "volatile"]


class BackgroundTaskHandle(ContractRecord):
    status: Literal["BACKGROUND"] = "BACKGROUND"
    execution_id: Identifier
    durability: Literal["durable", "volatile"]
    state_version: PositiveInteger


class ActivityCheckpoint(ContractRecord):
    admission_id: Identifier
    agent_id: Identifier
    context_version: PositiveInteger
    intent: Literal["continuing", "idle", "sleep"]


class ActivityView(ContractRecord):
    agent_id: Identifier
    admission_id: Identifier | None
    scope: OperationScope | None
    intent: Literal["continuing", "idle", "sleep"]
    availability: Literal[
        "ready", "waiting_model", "waiting_tool", "resource_blocked", "unavailable", "closing"
    ]
