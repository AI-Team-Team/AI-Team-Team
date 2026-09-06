from sqlalchemy import (
    String, Integer, Float, ForeignKey, Table, Column, JSON,
    CheckConstraint, ForeignKeyConstraint, UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from typing import Any, List, Optional

class Base(DeclarativeBase):
    pass

# Many-to-many association table for team members
team_members = Table(
    "team_members",
    Base.metadata,
    Column("team_id", String, ForeignKey("teams.team_id", ondelete="CASCADE"), primary_key=True),
    Column("agent_id", String, ForeignKey("agents.agent_id", ondelete="CASCADE"), primary_key=True),
)

class ManagerConfigModel(Base):
    __tablename__ = "manager_config"
    config_key: Mapped[str] = mapped_column(String, primary_key=True)
    config_value: Mapped[Optional[str]] = mapped_column(String, nullable=True)

class AgentModel(Base):
    __tablename__ = "agents"
    agent_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    role: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    role_description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    system_instructions: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    model_alias: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    last_context: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    lifecycle_state: Mapped[str] = mapped_column(String, default="active")

    messages: Mapped[List["AgentMessageModel"]] = relationship(
        back_populates="agent", cascade="all, delete-orphan", order_by="AgentMessageModel.created_at"
    )

class AgentMessageModel(Base):
    __tablename__ = "agent_messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[str] = mapped_column(String, ForeignKey("agents.agent_id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String)
    content: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[float] = mapped_column(Float)
    tool_calls: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    tool_call_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    team_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    discussion_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    agent: Mapped["AgentModel"] = relationship(back_populates="messages")


class SystemMemoryEventModel(Base):
    """Append-only journal row retaining an Agent identity snapshot."""

    __tablename__ = "system_memory_events"
    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    sequence: Mapped[int] = mapped_column(Integer, unique=True)
    event_type: Mapped[str] = mapped_column(String)
    agent_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    agent_name_snapshot: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    team_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    discussion_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    turn_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    role: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    redacted: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[float] = mapped_column(Float)


class AgentMemorySegmentModel(Base):
    __tablename__ = "agent_memory_segments"
    segment_id: Mapped[str] = mapped_column(String, primary_key=True)
    agent_id: Mapped[str] = mapped_column(
        String, ForeignKey("agents.agent_id", ondelete="CASCADE")
    )
    turn_id: Mapped[str] = mapped_column(String, unique=True)
    origin_team_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    discussion_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    recall_content: Mapped[str] = mapped_column(String)
    content_sha256: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error_kind: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[float] = mapped_column(Float)
    updated_at: Mapped[float] = mapped_column(Float)

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'processing', 'indexed', 'failed')",
            name="ck_memory_segment_status",
        ),
    )


class AgentMemoryCardModel(Base):
    __tablename__ = "agent_memory_cards"
    memory_id: Mapped[str] = mapped_column(String, primary_key=True)
    agent_id: Mapped[str] = mapped_column(
        String, ForeignKey("agents.agent_id", ondelete="CASCADE")
    )
    turn_id: Mapped[str] = mapped_column(String, unique=True)
    title: Mapped[str] = mapped_column(String)
    summary: Mapped[str] = mapped_column(String)
    origin_team_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    discussion_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    segment_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("agent_memory_segments.segment_id", ondelete="CASCADE"),
        unique=True,
    )
    status: Mapped[str] = mapped_column(String)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[float] = mapped_column(Float)
    updated_at: Mapped[float] = mapped_column(Float)

    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'forgotten')",
            name="ck_memory_card_status",
        ),
    )


class MemoryCardTagModel(Base):
    __tablename__ = "memory_card_tags"
    memory_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("agent_memory_cards.memory_id", ondelete="CASCADE"),
        primary_key=True,
    )
    tag: Mapped[str] = mapped_column(String, primary_key=True)
    sequence: Mapped[int] = mapped_column(Integer)

    __table_args__ = (
        UniqueConstraint(
            "memory_id",
            "sequence",
            name="uq_memory_card_tag_sequence",
        ),
    )


class MemoryCardSourceEventModel(Base):
    __tablename__ = "memory_card_source_events"
    segment_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("agent_memory_segments.segment_id", ondelete="CASCADE"),
        primary_key=True,
    )
    event_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("system_memory_events.event_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    sequence: Mapped[int] = mapped_column(Integer)

    __table_args__ = (
        UniqueConstraint(
            "segment_id",
            "sequence",
            name="uq_memory_card_source_sequence",
        ),
    )


class RetainedMemoryReferenceModel(Base):
    __tablename__ = "retained_memory_references"
    reference_id: Mapped[str] = mapped_column(String, primary_key=True)
    agent_id: Mapped[str] = mapped_column(
        String, ForeignKey("agents.agent_id", ondelete="CASCADE")
    )
    memory_id: Mapped[str] = mapped_column(
        String, ForeignKey("agent_memory_cards.memory_id", ondelete="CASCADE")
    )
    note: Mapped[str] = mapped_column(String)
    created_at: Mapped[float] = mapped_column(Float)

class TeamModel(Base):
    __tablename__ = "teams"
    team_id: Mapped[str] = mapped_column(String, primary_key=True)
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

class LibraryModel(Base):
    __tablename__ = "libraries"
    lib_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    library_kind: Mapped[str] = mapped_column(String)
    owner_team_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("teams.team_id", ondelete="CASCADE"), nullable=True
    )
    owner_agent_id: Mapped[Optional[str]] = mapped_column(
        String,
        ForeignKey("agents.agent_id", ondelete="CASCADE"),
        nullable=True,
        unique=True,
    )
    lifecycle_state: Mapped[str] = mapped_column(String, default="active")
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    is_public_visible: Mapped[int] = mapped_column(Integer, default=0)

    files: Mapped[List["DocLibFileModel"]] = relationship(
        back_populates="library", cascade="all, delete-orphan"
    )
    __table_args__ = (
        CheckConstraint(
            "(library_kind = 'team' AND owner_team_id IS NOT NULL "
            "AND owner_agent_id IS NULL) OR "
            "(library_kind = 'agent_private' AND owner_team_id IS NULL "
            "AND owner_agent_id IS NOT NULL)",
            name="ck_library_exact_owner",
        ),
    )

class LibraryPermissionModel(Base):
    __tablename__ = "library_permissions"
    lib_id: Mapped[str] = mapped_column(String, primary_key=True)
    path: Mapped[str] = mapped_column(String, primary_key=True)
    team_id: Mapped[str] = mapped_column(String, primary_key=True)
    permission: Mapped[Optional[str]] = mapped_column(String, nullable=True)

class DocLibFileModel(Base):
    __tablename__ = "doc_lib_files"
    lib_id: Mapped[str] = mapped_column(String, ForeignKey("libraries.lib_id", ondelete="CASCADE"), primary_key=True)
    path: Mapped[str] = mapped_column(String, primary_key=True)
    content: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    library: Mapped["LibraryModel"] = relationship(back_populates="files")


class DocLibLinkModel(Base):
    """A managed cross-library file link; no filesystem symlink is created."""

    __tablename__ = "doc_lib_links"
    source_lib_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("libraries.lib_id", ondelete="CASCADE"),
        primary_key=True,
    )
    source_path: Mapped[str] = mapped_column(String, primary_key=True)
    target_lib_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("libraries.lib_id", ondelete="CASCADE"),
    )
    target_path: Mapped[str] = mapped_column(String)
