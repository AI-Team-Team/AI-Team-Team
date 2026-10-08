"""Immutable, strict records shared by the replacement runtime."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


Identifier = Annotated[str, Field(min_length=1, pattern=r"\S")]
PositiveInteger = Annotated[int, Field(gt=0)]


class ContractRecord(BaseModel):
    """Contains values, never live tasks, mutable containers, or provider clients."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, validate_default=True)
