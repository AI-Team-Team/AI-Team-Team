"""Explicit stopping controls; continuing activity needs no declaration."""

from collections.abc import Mapping
from typing import Annotated, Any, Literal

from pydantic import Field, GetJsonSchemaHandler, model_serializer, model_validator
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import core_schema

from .base import ContractRecord, Identifier, PositiveInteger


def _duration_json_schema(schema: dict[str, Any]) -> None:
    """Keep omitted units distinct from null in both wire schema modes."""
    units = ("days", "hours", "minutes")
    schema["type"] = "object"
    schema["properties"] = {
        unit: {"type": "integer", "exclusiveMinimum": 0, "title": unit.title()} for unit in units
    }
    schema["additionalProperties"] = False
    schema["anyOf"] = [{"required": [unit]} for unit in units]
    schema.pop("required", None)


class WakeDuration(ContractRecord):
    days: PositiveInteger | None = None
    hours: PositiveInteger | None = None
    minutes: PositiveInteger | None = None

    @classmethod
    def __get_pydantic_json_schema__(
        cls, schema: core_schema.CoreSchema, handler: GetJsonSchemaHandler, /
    ) -> JsonSchemaValue:
        wire_schema = handler.resolve_ref_schema(handler(schema))
        _duration_json_schema(wire_schema)
        return wire_schema

    @model_validator(mode="before")
    @classmethod
    def reject_explicit_null_units(cls, value: Any) -> Any:
        if isinstance(value, Mapping):
            if any(unit in value and value[unit] is None for unit in ("days", "hours", "minutes")):
                raise ValueError("Supplied countdown components must be positive integers.")
        return value

    @model_serializer
    def serialize_units(self) -> dict[str, int]:
        return {
            unit: value
            for unit in ("days", "hours", "minutes")
            if (value := getattr(self, unit)) is not None
        }

    @model_validator(mode="after")
    def require_duration(self) -> "WakeDuration":
        if self.days is None and self.hours is None and self.minutes is None:
            raise ValueError("A countdown requires at least one duration component.")
        return self

    @property
    def total_seconds(self) -> int:
        return ((self.days or 0) * 1440 + (self.hours or 0) * 60 + (self.minutes or 0)) * 60


class CountdownBounds(ContractRecord):
    minimum_minutes: PositiveInteger = 5
    maximum_minutes: PositiveInteger = 2880

    @model_validator(mode="after")
    def ordered_bounds(self) -> "CountdownBounds":
        if self.maximum_minutes < self.minimum_minutes:
            raise ValueError("The maximum countdown cannot be below its minimum.")
        return self

    def check(self, duration: WakeDuration) -> None:
        if not self.minimum_minutes * 60 <= duration.total_seconds <= self.maximum_minutes * 60:
            raise ValueError("The total countdown is outside the Host's permitted bounds.")


class MessageWakeCondition(ContractRecord):
    kind: Literal["message"] = "message"
    source_kind: Literal["agent", "agent_team"]
    source_id: Identifier


class ExecutionWakeCondition(ContractRecord):
    kind: Literal["execution"] = "execution"
    execution_id: Identifier


EarlyWakeCondition = Annotated[
    MessageWakeCondition | ExecutionWakeCondition, Field(discriminator="kind")
]


class IdleIntent(ContractRecord):
    kind: Literal["idle"] = "idle"


class SleepIntent(ContractRecord):
    kind: Literal["sleep"] = "sleep"
    countdown: WakeDuration
    early_conditions: tuple[EarlyWakeCondition, ...] = ()

    def check_bounds(self, bounds: CountdownBounds) -> None:
        """The admitting Host supplies its live bounds, not model-owned bounds."""
        bounds.check(self.countdown)


ActivityIntent = Annotated[IdleIntent | SleepIntent, Field(discriminator="kind")]


class SuppressionPreference(ContractRecord):
    """Permanent or timed ordinary suppression never blocks source delivery."""

    scope: Literal["all", "agent", "agent_team"]
    source_id: Identifier | None = None
    countdown: WakeDuration | None = None

    @model_validator(mode="after")
    def validate_source(self) -> "SuppressionPreference":
        if (self.scope == "all") != (self.source_id is None):
            raise ValueError("Source-scoped suppression requires exactly one source ID.")
        return self

    def check_bounds(self, bounds: CountdownBounds) -> None:
        if self.countdown is not None:
            bounds.check(self.countdown)
