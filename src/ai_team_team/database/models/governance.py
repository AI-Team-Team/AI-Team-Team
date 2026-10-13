"""Durable cases, immutable electorate ballots, and explicit parent evidence."""

from typing import Optional

from sqlalchemy import CheckConstraint, Float, ForeignKey, ForeignKeyConstraint, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class GovernanceRoundModel(Base):
    __tablename__ = "governance_cases"
    round_id: Mapped[str] = mapped_column("case_id", String, primary_key=True)
    principal_team_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("teams.team_id", ondelete="RESTRICT"), nullable=True
    )
    principal_agent_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("agents.agent_id", ondelete="RESTRICT"), nullable=True
    )
    data: Mapped[dict] = mapped_column(JSON)
    electorate_revision: Mapped[int] = mapped_column(Integer, default=1)
    choice_schema: Mapped[dict] = mapped_column(JSON, default=dict)
    state_version: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (
        CheckConstraint(
            "(principal_team_id IS NULL) <> (principal_agent_id IS NULL)",
            name="ck_governance_principal_owner",
        ),
        CheckConstraint("electorate_revision > 0 AND state_version > 0"),
        CheckConstraint("length(trim(case_id)) > 0"),
    )


class GovernanceElectorateModel(Base):
    __tablename__ = "governance_electorates"
    case_id: Mapped[str] = mapped_column(String, ForeignKey("governance_cases.case_id", ondelete="RESTRICT"), primary_key=True)
    voter_agent_id: Mapped[str] = mapped_column(String, ForeignKey("agents.agent_id", ondelete="RESTRICT"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer)
    eligibility: Mapped[dict] = mapped_column(JSON)
    created_version: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (CheckConstraint("position >= 0 AND created_version > 0"), UniqueConstraint("case_id", "position"))


class GovernanceBallotModel(Base):
    __tablename__ = "governance_ballots"
    ballot_id: Mapped[str] = mapped_column(String, primary_key=True)
    round_id: Mapped[str] = mapped_column(
        "case_id", String
    )
    voter_agent_id: Mapped[str] = mapped_column(
        String, ForeignKey("agents.agent_id", ondelete="RESTRICT")
    )
    choice: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[float] = mapped_column(Float)
    created_version: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (
        UniqueConstraint("case_id", "voter_agent_id", name="uq_governance_voter_case"),
        ForeignKeyConstraint(["case_id", "voter_agent_id"], ["governance_electorates.case_id", "governance_electorates.voter_agent_id"], ondelete="RESTRICT"),
        CheckConstraint("created_version > 0"),
        CheckConstraint("length(trim(ballot_id)) > 0 AND created_at >= -1e308 AND created_at <= 1e308"),
    )


class MigrationRequestModel(Base):
    __tablename__ = "migration_requests"
    request_id: Mapped[str] = mapped_column(String, primary_key=True)
    team_id: Mapped[str] = mapped_column(String, ForeignKey("teams.team_id", ondelete="RESTRICT"))
    target_parent_id: Mapped[Optional[str]] = mapped_column(
        "target_parent_team_id", String, ForeignKey("teams.team_id", ondelete="RESTRICT"), nullable=True
    )
    target_parent_agent_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("agents.agent_id", ondelete="RESTRICT"), nullable=True)
    original_parent_id: Mapped[Optional[str]] = mapped_column(
        "original_parent_team_id", String, ForeignKey("teams.team_id", ondelete="RESTRICT"), nullable=True
    )
    original_parent_agent_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("agents.agent_id", ondelete="RESTRICT"), nullable=True)
    acceptance_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("parent_acceptances.acceptance_id", ondelete="RESTRICT"), nullable=True)
    detachment_kind: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    path_evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    state_version: Mapped[int] = mapped_column(Integer, default=1)
    data: Mapped[dict] = mapped_column(JSON)
    __table_args__ = (
        CheckConstraint("target_parent_team_id IS NULL OR target_parent_agent_id IS NULL"),
        CheckConstraint("original_parent_team_id IS NULL OR original_parent_agent_id IS NULL"),
        CheckConstraint("detachment_kind IS NULL OR detachment_kind IN ('voluntary_departure', 'parent_loss')"),
        CheckConstraint("detachment_kind IS NULL OR (target_parent_team_id IS NULL AND target_parent_agent_id IS NULL)"),
        CheckConstraint("state_version > 0"),
    )
