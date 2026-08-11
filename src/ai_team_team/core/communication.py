"""Typed communication governance records and public operation results."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class CommunicationRequestStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    STALE = "STALE"


class CommunicationApprovalStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    CANCELLED = "CANCELLED"


class AgreementDirection(str, Enum):
    ONE_WAY = "one_way"
    BIDIRECTIONAL = "bidirectional"


class ApprovalPrincipal(BaseModel):
    """A governance authority explicitly named by ATT policy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["agent_team", "agent"]
    principal_id: str = Field(min_length=1)

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.principal_id}"


class CommunicationBallot(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    request_id: str = Field(min_length=1)
    principal: ApprovalPrincipal
    voter_agent_id: str = Field(min_length=1)
    approved: bool
    reason: str = ""
    created_at: float = Field(default_factory=time.time)


class CommunicationApproval(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    request_id: str = Field(min_length=1)
    principal: ApprovalPrincipal
    sequence: int
    status: CommunicationApprovalStatus = CommunicationApprovalStatus.PENDING
    reason: str = ""
    created_at: float = Field(default_factory=time.time)
    resolved_at: Optional[float] = None

    @property
    def key(self) -> str:
        return f"{self.request_id}:{self.principal.key}"


class CommunicationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    request_id: str = Field(
        default_factory=lambda: f"CR-{uuid.uuid4().hex}"
    )
    sender_team_id: str = Field(min_length=1)
    recipient_team_id: str = Field(min_length=1)
    initiated_by_agent_id: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    direction: AgreementDirection = AgreementDirection.BIDIRECTIONAL
    policy_snapshot: Dict[str, Any]
    approval_principals: List[ApprovalPrincipal]
    route_fingerprint: str
    status: CommunicationRequestStatus = CommunicationRequestStatus.PENDING
    decision_reason: str = ""
    created_at: float = Field(default_factory=time.time)
    resolved_at: Optional[float] = None
    superseded_by_request_id: Optional[str] = None
    supersedes_request_id: Optional[str] = None


class CommunicationAgreement(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    agreement_id: str = Field(
        default_factory=lambda: f"CA-{uuid.uuid4().hex}"
    )
    source_team_id: str = Field(min_length=1)
    target_team_id: str = Field(min_length=1)
    direction: AgreementDirection
    allowed_message_types: List[str] = Field(
        default_factory=lambda: ["peer_message"]
    )
    created_from_request_id: str = Field(min_length=1)
    policy_snapshot: Dict[str, Any]
    active: bool = True
    created_at: float = Field(default_factory=time.time)
    revoked_at: Optional[float] = None
    revoked_by_team_id: Optional[str] = None
    revoke_reason: Optional[str] = None
    superseded_by_agreement_id: Optional[str] = None

    def permits(self, sender_team_id: str, recipient_team_id: str) -> bool:
        if not self.active or "peer_message" not in self.allowed_message_types:
            return False
        if (
            sender_team_id == self.source_team_id
            and recipient_team_id == self.target_team_id
        ):
            return True
        return bool(
            self.direction is AgreementDirection.BIDIRECTIONAL
            and sender_team_id == self.target_team_id
            and recipient_team_id == self.source_team_id
        )


class PeerMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    message_id: str = Field(
        default_factory=lambda: f"PM-{uuid.uuid4().hex}"
    )
    sender_team_id: str = Field(min_length=1)
    recipient_team_id: str = Field(min_length=1)
    initiated_by_agent_id: str = Field(min_length=1)
    agreement_id: Optional[str] = None
    content: str = Field(min_length=1)
    delivery_state: Literal["pending", "consumed"] = "pending"
    created_at: float = Field(default_factory=time.time)
    consumed_at: Optional[float] = None
    invocation_id: Optional[str] = None

    def to_inbox_message(self) -> Dict[str, Any]:
        return {
            "type": "peer_message",
            "message_id": self.message_id,
            "from": self.sender_team_id,
            "sender_team_id": self.sender_team_id,
            "recipient_team_id": self.recipient_team_id,
            "initiated_by_agent_id": self.initiated_by_agent_id,
            "agreement_id": self.agreement_id,
            "objective": self.content,
            "delivery_state": self.delivery_state,
            "created_at": self.created_at,
            "consumed_at": self.consumed_at,
            "invocation_id": self.invocation_id,
        }


class CommunicationOperationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal[
        "DELIVERED",
        "NO_AGREEMENT",
        "PENDING_APPROVAL",
        "APPROVED",
        "DENIED",
        "ALREADY_ACTIVE",
        "REVOKED",
        "ALREADY_REVOKED",
        "FORBIDDEN",
    ]
    reason: str = ""
    request_id: Optional[str] = None
    agreement_id: Optional[str] = None
    message_id: Optional[str] = None
    team_id: Optional[str] = None


def route_fingerprint(principals: List[ApprovalPrincipal]) -> str:
    canonical = json.dumps(
        [principal.model_dump(mode="json") for principal in principals],
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
