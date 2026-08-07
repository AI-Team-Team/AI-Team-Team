from sqlalchemy import (
    String, Integer, Float, ForeignKey, Table, Column, JSON,
    CheckConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from typing import List, Optional

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
    communication_rules: Mapped[Optional[str]] = mapped_column(String, nullable=True)
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

class BrokerAgreementModel(Base):
    __tablename__ = "broker_agreements"
    sender_team_id: Mapped[str] = mapped_column(String, primary_key=True)
    recipient_team_id: Mapped[str] = mapped_column(String, primary_key=True)

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
