"""Durable round identities, immutable explicit ballots, and migration requests."""

from typing import Optional

from sqlalchemy import CheckConstraint, Float, ForeignKey, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class GovernanceRoundModel(Base):
    __tablename__ = "governance_rounds"
    round_id: Mapped[str] = mapped_column(String, primary_key=True)
    principal_team_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("teams.team_id", ondelete="RESTRICT"), nullable=True
    )
    principal_agent_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("agents.agent_id", ondelete="RESTRICT"), nullable=True
    )
    data: Mapped[dict] = mapped_column(JSON)
    __table_args__ = (
        CheckConstraint(
            "(principal_team_id IS NULL) <> (principal_agent_id IS NULL)",
            name="ck_governance_principal_owner",
        ),
    )


class GovernanceBallotModel(Base):
    __tablename__ = "governance_ballots"
    ballot_id: Mapped[str] = mapped_column(String, primary_key=True)
    round_id: Mapped[str] = mapped_column(
        String, ForeignKey("governance_rounds.round_id", ondelete="CASCADE")
    )
    voter_agent_id: Mapped[str] = mapped_column(
        String, ForeignKey("agents.agent_id", ondelete="RESTRICT")
    )
    choice: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[float] = mapped_column(Float)
    __table_args__ = (
        UniqueConstraint("round_id", "voter_agent_id", name="uq_governance_voter_round"),
    )


class MigrationRequestModel(Base):
    __tablename__ = "migration_requests"
    request_id: Mapped[str] = mapped_column(String, primary_key=True)
    team_id: Mapped[str] = mapped_column(String, ForeignKey("teams.team_id", ondelete="RESTRICT"))
    target_parent_id: Mapped[str] = mapped_column(
        String, ForeignKey("teams.team_id", ondelete="RESTRICT")
    )
    original_parent_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("teams.team_id", ondelete="RESTRICT"), nullable=True
    )
    data: Mapped[dict] = mapped_column(JSON)
