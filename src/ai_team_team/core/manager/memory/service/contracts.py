"""Internal strict contracts for memory indexing."""

from typing import List

from pydantic import BaseModel, ConfigDict, Field


class _MemoryLabels(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    title: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1, max_length=1000)
    tags: List[str] = Field(min_length=1)
