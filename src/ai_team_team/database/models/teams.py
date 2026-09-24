from typing import List, Optional

from sqlalchemy import (
    CheckConstraint,
    Column,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Table,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .agents import AgentModel
from .base import Base


# Many-to-many association table for team members.
team_members = Table(
    "team_members",
    Base.metadata,
    Column(
        "team_id",
        String,
        ForeignKey("teams.team_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "agent_id",
        String,
        ForeignKey("agents.agent_id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class TeamModel(Base):
    __tablename__ = "teams"
    team_id: Mapped[str] = mapped_column(String, primary_key=True)
    team_kind: Mapped[str] = mapped_column(String, nullable=False)
    preset_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    team_purpose: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    team_progress: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    depth: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    chapter_num: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    parent_team_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("teams.team_id", ondelete="SET NULL"), nullable=True)
    migration_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    creator_agent_id: Mapped[Optional[str]] = mapped_column(
        String,
        ForeignKey("agents.agent_id", ondelete="RESTRICT"),
        nullable=True,
    )
    creator_team_id: Mapped[Optional[str]] = mapped_column(
        String,
        ForeignKey("teams.team_id", ondelete="RESTRICT"),
        nullable=True,
    )
    status_map: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    system_instructions: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Self-referential hierarchy
    parent_team: Mapped[Optional["TeamModel"]] = relationship(
        "TeamModel",
        remote_side=[team_id],
        foreign_keys=[parent_team_id],
        back_populates="child_teams",
    )
    child_teams: Mapped[List["TeamModel"]] = relationship(
        "TeamModel", foreign_keys=[parent_team_id], back_populates="parent_team"
    )

    # Many-to-many members
    members: Mapped[List["AgentModel"]] = relationship(
        secondary=team_members,
        order_by="AgentModel.name"
    )

    inbox: Mapped[List["TeamInboxModel"]] = relationship(
        back_populates="team", cascade="all, delete-orphan", order_by="TeamInboxModel.created_at"
    )
    proposals: Mapped[List["TeamProposalModel"]] = relationship(
        back_populates="team", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "team_kind = 'ordinary'",
            name="ck_persisted_team_kind",
        ),
        CheckConstraint(
            "(creator_agent_id IS NOT NULL AND creator_team_id IS NULL) OR "
            "(creator_agent_id IS NULL AND creator_team_id IS NOT NULL)",
            name="ck_team_exact_creator",
        ),
    )

class TeamInboxModel(Base):
    __tablename__ = "team_inbox"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    team_id: Mapped[str] = mapped_column(String, ForeignKey("teams.team_id", ondelete="CASCADE"))
    sender: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    msg_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    payload: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[float] = mapped_column(Float)

    team: Mapped["TeamModel"] = relationship(back_populates="inbox")

class TeamProposalModel(Base):
    __tablename__ = "team_proposals"
    proposal_id: Mapped[str] = mapped_column(String, primary_key=True)
    team_id: Mapped[str] = mapped_column(String, ForeignKey("teams.team_id", ondelete="CASCADE"))
    action: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    target: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    initiator_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    initiator_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    initiator_agent_id: Mapped[Optional[str]] = mapped_column(
        String,
        ForeignKey("agents.agent_id", ondelete="SET NULL"),
        nullable=True,
    )
    rationale: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    proposed_details: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    votes: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    team: Mapped["TeamModel"] = relationship(back_populates="proposals")


class TeamFormationRequestModel(Base):
    __tablename__ = "team_formation_requests"
    request_id: Mapped[str] = mapped_column(String, primary_key=True)
    initiator_agent_id: Mapped[str] = mapped_column(
        String, ForeignKey("agents.agent_id", ondelete="RESTRICT")
    )
    creator_kind: Mapped[str] = mapped_column(String)
    creator_agent_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("agents.agent_id", ondelete="RESTRICT"), nullable=True
    )
    creator_team_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("teams.team_id", ondelete="RESTRICT"), nullable=True
    )
    parent_team_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("teams.team_id", ondelete="RESTRICT"), nullable=True
    )
    task: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    member_count: Mapped[int] = mapped_column(Integer)
    roles_and_presets: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    preset_name: Mapped[str] = mapped_column(String)
    system_instructions: Mapped[str] = mapped_column(String)
    team_purpose: Mapped[str] = mapped_column(String)
    roles_and_models: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    member_configs: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    invitee_agent_ids: Mapped[list] = mapped_column(JSON)
    initial_docs: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    is_public_visible: Mapped[int] = mapped_column(Integer)
    initiator_joins: Mapped[int] = mapped_column(Integer)
    unanimous_acceptance_action: Mapped[str] = mapped_column(String)
    late_join_policy: Mapped[str] = mapped_column(String)
    proposal_revision: Mapped[int] = mapped_column(Integer)
    content_fingerprint: Mapped[str] = mapped_column(String)
    revision_fingerprint: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    created_team_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("teams.team_id", ondelete="RESTRICT"), nullable=True
    )
    decision_reason: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[float] = mapped_column(Float)
    updated_at: Mapped[float] = mapped_column(Float)
    resolved_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "(creator_kind = 'agent' AND creator_agent_id IS NOT NULL AND creator_team_id IS NULL) OR "
            "(creator_kind = 'agent_team' AND creator_agent_id IS NULL AND creator_team_id IS NOT NULL)",
            name="ck_team_formation_exact_creator",
        ),
        CheckConstraint(
            "status IN ('collecting_responses', 'ready_for_confirmation', 'created', 'abandoned')",
            name="ck_team_formation_status",
        ),
        CheckConstraint(
            "is_public_visible IN (0, 1)",
            name="ck_team_formation_public_visible_boolean",
        ),
        CheckConstraint(
            "initiator_joins IN (0, 1)",
            name="ck_team_formation_initiator_joins_boolean",
        ),
        CheckConstraint(
            "member_count >= 1 AND proposal_revision >= 1",
            name="ck_team_formation_positive_counts",
        ),
        UniqueConstraint(
            "created_team_id",
            name="uq_team_formation_created_team",
        ),
    )


class TeamFormationInvitationModel(Base):
    __tablename__ = "team_formation_invitations"
    request_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("team_formation_requests.request_id", ondelete="CASCADE"),
        primary_key=True,
    )
    agent_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("agents.agent_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    proposal_revision: Mapped[int] = mapped_column(Integer)
    attitude: Mapped[str] = mapped_column(String)
    responded_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    joined_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    late_join_pending: Mapped[int] = mapped_column(Integer)
    late_join_requested_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    late_join_decision: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "attitude IN ('accepted', 'declined', 'explicitly_ignored', 'no_response')",
            name="ck_team_formation_invitation_attitude",
        ),
        CheckConstraint(
            "late_join_pending IN (0, 1)",
            name="ck_team_formation_late_join_pending_boolean",
        ),
    )


class TeamFormationRevisionModel(Base):
    __tablename__ = "team_formation_revisions"
    revision_id: Mapped[str] = mapped_column(String, primary_key=True)
    request_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("team_formation_requests.request_id", ondelete="CASCADE"),
    )
    proposal_revision: Mapped[int] = mapped_column(Integer)
    content_fingerprint: Mapped[str] = mapped_column(String)
    revision_fingerprint: Mapped[str] = mapped_column(String)
    proposal_snapshot: Mapped[dict] = mapped_column(JSON)
    revised_by_agent_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("agents.agent_id", ondelete="RESTRICT"),
    )
    source_draft_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[float] = mapped_column(Float)

    __table_args__ = (
        UniqueConstraint(
            "request_id",
            "proposal_revision",
            name="uq_team_formation_revision_number",
        ),
        UniqueConstraint(
            "source_draft_id",
            name="uq_team_formation_revision_source_draft",
        ),
        CheckConstraint(
            "proposal_revision >= 1",
            name="ck_team_formation_revision_positive",
        ),
    )


class TeamFormationInvitationDecisionModel(Base):
    __tablename__ = "team_formation_invitation_decisions"
    decision_id: Mapped[str] = mapped_column(String, primary_key=True)
    request_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("team_formation_requests.request_id", ondelete="CASCADE"),
    )
    proposal_revision: Mapped[int] = mapped_column(Integer)
    agent_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("agents.agent_id", ondelete="RESTRICT"),
    )
    attitude: Mapped[str] = mapped_column(String)
    created_at: Mapped[float] = mapped_column(Float)

    __table_args__ = (
        CheckConstraint(
            "proposal_revision >= 1",
            name="ck_team_formation_decision_revision_positive",
        ),
        CheckConstraint(
            "attitude IN ('accepted', 'declined', 'explicitly_ignored', 'no_response')",
            name="ck_team_formation_decision_attitude",
        ),
    )


class TeamFormationDraftModel(Base):
    __tablename__ = "team_formation_drafts"
    draft_id: Mapped[str] = mapped_column(String, primary_key=True)
    initiator_agent_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("agents.agent_id", ondelete="RESTRICT"),
    )
    creator_kind: Mapped[str] = mapped_column(String)
    creator_agent_id: Mapped[Optional[str]] = mapped_column(
        String,
        ForeignKey("agents.agent_id", ondelete="RESTRICT"),
        nullable=True,
    )
    creator_team_id: Mapped[Optional[str]] = mapped_column(
        String,
        ForeignKey("teams.team_id", ondelete="RESTRICT"),
        nullable=True,
    )
    deliberation_team_id: Mapped[Optional[str]] = mapped_column(
        String,
        ForeignKey("teams.team_id", ondelete="RESTRICT"),
        nullable=True,
    )
    request_id: Mapped[Optional[str]] = mapped_column(
        String,
        ForeignKey("team_formation_requests.request_id", ondelete="CASCADE"),
        nullable=True,
    )
    base_revision: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    base_revision_fingerprint: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    objective: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    participant_agent_ids: Mapped[list] = mapped_column(JSON)
    source_discussion_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    candidate: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    reason: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[float] = mapped_column(Float)
    updated_at: Mapped[float] = mapped_column(Float)

    __table_args__ = (
        CheckConstraint(
            "(creator_kind = 'agent' AND creator_agent_id IS NOT NULL "
            "AND creator_team_id IS NULL AND deliberation_team_id IS NULL) OR "
            "(creator_kind = 'agent_team' AND creator_agent_id IS NULL "
            "AND creator_team_id IS NOT NULL "
            "AND deliberation_team_id = creator_team_id)",
            name="ck_team_formation_draft_creator",
        ),
        CheckConstraint(
            "(request_id IS NULL AND base_revision IS NULL "
            "AND base_revision_fingerprint IS NULL) OR "
            "(request_id IS NOT NULL AND base_revision IS NOT NULL "
            "AND base_revision_fingerprint IS NOT NULL)",
            name="ck_team_formation_draft_exact_base",
        ),
        CheckConstraint(
            "status IN ('pending', 'running', 'ready', 'failed', 'cancelled', 'stale', 'published')",
            name="ck_team_formation_draft_status",
        ),
        CheckConstraint(
            "base_revision IS NULL OR base_revision >= 1",
            name="ck_team_formation_draft_revision_positive",
        ),
    )
