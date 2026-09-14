from typing import Optional

from sqlalchemy import CheckConstraint, Float, ForeignKey, ForeignKeyConstraint, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class CommunicationRequestModel(Base):
    __tablename__ = "communication_requests"
    request_id: Mapped[str] = mapped_column(String, primary_key=True)
    sender_team_id: Mapped[str] = mapped_column(
        String, ForeignKey("teams.team_id", ondelete="RESTRICT")
    )
    recipient_team_id: Mapped[str] = mapped_column(
        String, ForeignKey("teams.team_id", ondelete="RESTRICT")
    )
    initiated_by_agent_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("agents.agent_id", ondelete="SET NULL"), nullable=True
    )
    rationale: Mapped[str] = mapped_column(String)
    direction: Mapped[str] = mapped_column(String)
    policy_snapshot: Mapped[dict] = mapped_column(JSON)
    approval_principals: Mapped[list] = mapped_column(JSON)
    route_fingerprint: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    decision_reason: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[float] = mapped_column(Float)
    resolved_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    superseded_by_request_id: Mapped[Optional[str]] = mapped_column(
        String, nullable=True
    )
    supersedes_request_id: Mapped[Optional[str]] = mapped_column(
        String, nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "sender_team_id <> recipient_team_id",
            name="ck_communication_request_distinct_teams",
        ),
        CheckConstraint(
            "direction IN ('one_way', 'bidirectional')",
            name="ck_communication_request_direction",
        ),
    )


class CommunicationApprovalModel(Base):
    __tablename__ = "communication_approvals"
    request_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("communication_requests.request_id", ondelete="CASCADE"),
        primary_key=True,
    )
    principal_kind: Mapped[str] = mapped_column(String, primary_key=True)
    principal_id: Mapped[str] = mapped_column(String, primary_key=True)
    sequence: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[float] = mapped_column(Float)
    resolved_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "principal_kind IN ('agent_team', 'agent')",
            name="ck_communication_approval_principal_kind",
        ),
    )


class CommunicationBallotModel(Base):
    __tablename__ = "communication_ballots"
    request_id: Mapped[str] = mapped_column(String, primary_key=True)
    principal_kind: Mapped[str] = mapped_column(String, primary_key=True)
    principal_id: Mapped[str] = mapped_column(String, primary_key=True)
    voter_agent_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("agents.agent_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    approved: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[float] = mapped_column(Float)

    __table_args__ = (
        ForeignKeyConstraint(
            ["request_id", "principal_kind", "principal_id"],
            [
                "communication_approvals.request_id",
                "communication_approvals.principal_kind",
                "communication_approvals.principal_id",
            ],
            ondelete="CASCADE",
        ),
    )


class CommunicationAgreementModel(Base):
    __tablename__ = "communication_agreements"
    agreement_id: Mapped[str] = mapped_column(String, primary_key=True)
    source_team_id: Mapped[str] = mapped_column(
        String, ForeignKey("teams.team_id", ondelete="RESTRICT")
    )
    target_team_id: Mapped[str] = mapped_column(
        String, ForeignKey("teams.team_id", ondelete="RESTRICT")
    )
    direction: Mapped[str] = mapped_column(String)
    allowed_message_types: Mapped[list] = mapped_column(JSON)
    created_from_request_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("communication_requests.request_id", ondelete="RESTRICT"),
    )
    policy_snapshot: Mapped[dict] = mapped_column(JSON)
    active: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[float] = mapped_column(Float)
    revoked_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    revoked_by_team_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("teams.team_id", ondelete="RESTRICT"), nullable=True
    )
    revoke_reason: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    superseded_by_agreement_id: Mapped[Optional[str]] = mapped_column(
        String, nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "source_team_id <> target_team_id",
            name="ck_communication_agreement_distinct_teams",
        ),
        CheckConstraint(
            "direction IN ('one_way', 'bidirectional')",
            name="ck_communication_agreement_direction",
        ),
    )


class PeerMessageModel(Base):
    __tablename__ = "peer_messages"
    message_id: Mapped[str] = mapped_column(String, primary_key=True)
    sender_team_id: Mapped[str] = mapped_column(
        String, ForeignKey("teams.team_id", ondelete="RESTRICT")
    )
    recipient_team_id: Mapped[str] = mapped_column(
        String, ForeignKey("teams.team_id", ondelete="RESTRICT")
    )
    initiated_by_agent_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("agents.agent_id", ondelete="SET NULL"), nullable=True
    )
    agreement_id: Mapped[Optional[str]] = mapped_column(
        String,
        ForeignKey("communication_agreements.agreement_id", ondelete="SET NULL"),
        nullable=True,
    )
    content: Mapped[str] = mapped_column(String)
    delivery_state: Mapped[str] = mapped_column(String)
    created_at: Mapped[float] = mapped_column(Float)
    consumed_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    invocation_id: Mapped[Optional[str]] = mapped_column(
        String, nullable=True, unique=True
    )

