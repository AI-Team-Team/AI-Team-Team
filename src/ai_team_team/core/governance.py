"""Durable personal-mail governance rounds and explicit choices."""

import time
import uuid
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, StrictBool

from .communication import ApprovalPrincipal


class BooleanGovernanceChoice(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    approved: StrictBool
    reason: str = ""


class ModelGovernanceChoice(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    model_alias: str = Field(min_length=1)
    reason: str = ""


class GovernanceBallot(BaseModel):
    """An immutable public submission, independent of its email read receipt."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True, allow_inf_nan=False)
    ballot_id: str = Field(default_factory=lambda: f"GB-{uuid.uuid4().hex}")
    round_id: str
    voter_agent_id: str
    choice: Dict[str, Any]
    created_at: float = Field(default_factory=time.time)


class GovernanceRound(BaseModel):
    """One frozen electorate and schema for an exact governance activity."""

    model_config = ConfigDict(
        strict=True, extra="forbid", validate_assignment=True, allow_inf_nan=False
    )
    round_id: str = Field(default_factory=lambda: f"GR-{uuid.uuid4().hex}")
    business_kind: Literal["communication", "migration", "failover"]
    business_id: str
    principal: ApprovalPrincipal
    round_number: int = Field(ge=1)
    choice_kind: Literal["boolean", "model"]
    voter_agent_ids: List[str] = Field(min_length=1)
    prompt: str
    transcript: str = ""
    candidates: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    status: Literal[
        "PENDING", "APPROVED", "DENIED", "TIED", "SUPERSEDED", "EXPIRED", "CANCELLED"
    ] = "PENDING"
    ballots: List[GovernanceBallot] = Field(default_factory=list)
    reason: str = ""
    created_at: float = Field(default_factory=time.time)
    resolved_at: Optional[float] = None
    expires_at: Optional[float] = None


class GovernanceSubmissionResult(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    status: Literal["SUBMITTED", "ALREADY_SUBMITTED", "CLOSED"]
    round_id: str
    round_status: str
    reason: str = ""
    choice: Optional[Dict[str, Any]] = None


class MigrationRequest(BaseModel):
    model_config = ConfigDict(
        strict=True, extra="forbid", validate_assignment=True, allow_inf_nan=False
    )
    request_id: str = Field(default_factory=lambda: f"MIG-{uuid.uuid4().hex}")
    team_id: str
    target_parent_id: str
    original_parent_id: Optional[str]
    policy_name: Literal["permissive", "ancestor_approval", "lineage_path"]
    principals: List[ApprovalPrincipal]
    rationale: str
    status: Literal["PENDING", "EXECUTED", "DENIED", "STALE", "CANCELLED"] = "PENDING"
    reason: str = ""
    created_at: float = Field(default_factory=time.time)
    resolved_at: Optional[float] = None


class MigrationOperationResult(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    status: Literal["PENDING", "EXECUTED", "DENIED", "STALE", "CANCELLED"]
    request_id: Optional[str] = None
    reason: str = ""
