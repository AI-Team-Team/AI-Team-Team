from typing import List, Optional

from sqlalchemy import Float, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


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


class AgentInboxModel(Base):
    """A durable notification owned by one Agent identity rather than a team."""

    __tablename__ = "agent_inbox"
    message_id: Mapped[str] = mapped_column(String, primary_key=True)
    agent_id: Mapped[str] = mapped_column(
        String, ForeignKey("agents.agent_id", ondelete="CASCADE"), index=True
    )
    message_type: Mapped[str] = mapped_column(String)
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[float] = mapped_column(Float)
    read_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)


