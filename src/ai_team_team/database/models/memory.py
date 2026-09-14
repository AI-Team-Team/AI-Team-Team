from typing import Any, Optional

from sqlalchemy import CheckConstraint, Float, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


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
