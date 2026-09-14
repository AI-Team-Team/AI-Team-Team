"""Persistent, consent-based AgentTeam formation contracts."""

from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class InvitationAttitude(str, Enum):
    """The complete public attitude vocabulary for one invited Agent."""

    ACCEPTED = "accepted"
    DECLINED = "declined"
    EXPLICITLY_IGNORED = "explicitly_ignored"
    NO_RESPONSE = "no_response"


class TeamFormationStatus(str, Enum):
    COLLECTING_RESPONSES = "collecting_responses"
    READY_FOR_CONFIRMATION = "ready_for_confirmation"
    CREATED = "created"
    ABANDONED = "abandoned"


class FormationDraftStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    READY = "ready"
    FAILED = "failed"
    CANCELLED = "cancelled"
    STALE = "stale"
    PUBLISHED = "published"


class UnanimousAcceptanceAction(str, Enum):
    AUTO_CREATE = "auto_create"
    REQUIRE_CONFIRMATION = "require_confirmation"


class LateJoinPolicy(str, Enum):
    DISABLED = "disabled"
    OPEN = "open"
    REQUIRE_INITIATOR_CONFIRMATION = "require_initiator_confirmation"


class AgentInboxMessage(BaseModel):
    """A durable notification addressed to one stable Agent identity."""

    model_config = ConfigDict(extra="forbid", strict=True, validate_assignment=True)

    message_id: str
    agent_id: str
    message_type: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    created_at: float
    read_at: Optional[float] = None


class TeamFormationInvitation(BaseModel):
    """One invited Agent's public response and late-join state."""

    model_config = ConfigDict(extra="forbid", strict=True, validate_assignment=True)

    request_id: str
    agent_id: str
    proposal_revision: int = Field(ge=1)
    attitude: InvitationAttitude = InvitationAttitude.NO_RESPONSE
    responded_at: Optional[float] = None
    joined_at: Optional[float] = None
    late_join_pending: bool = False
    late_join_requested_at: Optional[float] = None
    late_join_decision: Optional[Literal["approved", "denied"]] = None


class TeamFormationRequest(BaseModel):
    """A persistent proposal that cannot add existing Agents without consent."""

    model_config = ConfigDict(extra="forbid", strict=True, validate_assignment=True)

    request_id: str
    initiator_agent_id: str
    creator_kind: Literal["agent", "agent_team"]
    creator_id: str
    parent_team_id: Optional[str] = None
    task: Optional[str] = None
    member_count: int = Field(ge=1)
    roles_and_presets: Optional[List[List[str]]] = None
    preset_name: str
    system_instructions: str
    team_purpose: str
    roles_and_models: Optional[Dict[str, str]] = None
    member_configs: Optional[Dict[str, Dict[str, Any]]] = None
    invitee_agent_ids: List[str]
    initial_docs: Optional[Dict[str, str]] = None
    is_public_visible: bool
    initiator_joins: bool = False
    unanimous_acceptance_action: UnanimousAcceptanceAction
    late_join_policy: LateJoinPolicy
    proposal_revision: int = Field(default=1, ge=1)
    content_fingerprint: str
    revision_fingerprint: str
    status: TeamFormationStatus = TeamFormationStatus.COLLECTING_RESPONSES
    created_team_id: Optional[str] = None
    decision_reason: str = ""
    created_at: float
    updated_at: float
    resolved_at: Optional[float] = None


class TeamFormationRevisionPatch(BaseModel):
    """Material proposal fields supplied with explicit unset/null semantics."""

    model_config = ConfigDict(extra="forbid", strict=True)

    task: Optional[str] = None
    member_count: Optional[int] = Field(default=None, ge=1)
    roles_and_presets: Optional[List[List[str]]] = None
    preset_name: Optional[str] = None
    system_instructions: Optional[str] = None
    team_purpose: Optional[str] = None
    roles_and_models: Optional[Dict[str, str]] = None
    member_configs: Optional[Dict[str, Dict[str, Any]]] = None
    existing_member_ids: Optional[List[str]] = None
    initial_docs: Optional[Dict[str, str]] = None
    is_public_visible: Optional[bool] = None
    initiator_joins: Optional[bool] = None
    unanimous_acceptance_action: Optional[UnanimousAcceptanceAction] = None
    late_join_policy: Optional[LateJoinPolicy] = None


class TeamFormationDraftCandidate(BaseModel):
    """Complete structured candidate synthesized from proposal deliberation."""

    model_config = ConfigDict(extra="forbid", strict=True)

    task: Optional[str] = None
    member_count: int = Field(ge=1)
    roles_and_presets: Optional[List[List[str]]] = None
    preset_name: str
    system_instructions: str
    team_purpose: str
    roles_and_models: Optional[Dict[str, str]] = None
    member_configs: Optional[Dict[str, Dict[str, Any]]] = None
    existing_member_ids: List[str] = Field(default_factory=list)
    initial_docs: Optional[Dict[str, str]] = None
    is_public_visible: bool
    initiator_joins: bool
    unanimous_acceptance_action: UnanimousAcceptanceAction
    late_join_policy: LateJoinPolicy

    def as_patch(self) -> TeamFormationRevisionPatch:
        return TeamFormationRevisionPatch.model_validate(
            self.model_dump(mode="python"),
            strict=True,
        )


class TeamFormationRevision(BaseModel):
    """Immutable audit snapshot for one committed proposal revision."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    revision_id: str
    request_id: str
    proposal_revision: int = Field(ge=1)
    content_fingerprint: str
    revision_fingerprint: str
    proposal_snapshot: Dict[str, Any]
    revised_by_agent_id: str
    source_draft_id: Optional[str] = None
    created_at: float


class TeamFormationInvitationDecision(BaseModel):
    """Append-only public attitude expressed for an exact proposal revision."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    decision_id: str
    request_id: str
    proposal_revision: int = Field(ge=1)
    agent_id: str
    attitude: InvitationAttitude
    created_at: float


class TeamFormationDraft(BaseModel):
    """Persistent detached deliberation and structured synthesis job."""

    model_config = ConfigDict(extra="forbid", strict=True, validate_assignment=True)

    draft_id: str
    initiator_agent_id: str
    creator_kind: Literal["agent", "agent_team"]
    creator_id: str
    creator_team_id: Optional[str] = None
    request_id: Optional[str] = None
    base_revision: Optional[int] = Field(default=None, ge=1)
    base_revision_fingerprint: Optional[str] = None
    objective: str
    status: FormationDraftStatus = FormationDraftStatus.PENDING
    participant_agent_ids: List[str] = Field(default_factory=list)
    source_discussion_id: Optional[str] = None
    candidate: Optional[TeamFormationDraftCandidate] = None
    reason: str = ""
    created_at: float
    updated_at: float


class FormationStatusSummary(BaseModel):
    """Privacy-safe, initiator-facing counts and creation eligibility."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    request_id: str
    status: TeamFormationStatus
    accepted: int
    declined: int
    explicitly_ignored: int
    no_response: int
    eligible_member_count: int
    minimum_member_count: int
    can_create: bool
    eligibility_reason: str = ""
    created_team_id: Optional[str] = None
    note: str = (
        "Only accepted invited Agents join; declined, explicitly ignored, and no-response "
        "invitations all mean that the Agent does not join."
    )


class TeamFormationInspection(BaseModel):
    """An authorization-checked proposal view plus its live response summary."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    request: TeamFormationRequest
    summary: FormationStatusSummary


class FormationOperationResult(BaseModel):
    """Stable result returned by formation APIs and Agent-facing tools."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    status: Literal[
        "PENDING_RESPONSES",
        "READY_FOR_CONFIRMATION",
        "CREATED",
        "ABANDONED",
        "INVITATION_UPDATED",
        "LATE_JOIN_PENDING",
        "JOINED",
        "DENIED",
        "REVISED",
        "UNCHANGED",
        "STALE_REVISION",
        "DRAFT_PENDING",
        "DRAFT_READY",
        "DRAFT_FAILED",
        "DRAFT_PUBLISHED",
    ]
    request_id: str
    summary: FormationStatusSummary
    team_id: Optional[str] = None
    reason: str = ""
