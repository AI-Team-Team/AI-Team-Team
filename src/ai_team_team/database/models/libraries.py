from typing import List, Optional

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


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

