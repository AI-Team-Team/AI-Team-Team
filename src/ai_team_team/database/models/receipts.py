"""Queryable accepted-operation evidence, independent of callback delivery."""

from sqlalchemy import CheckConstraint, Column, Integer, JSON, String, Table

from .base import Base


commit_receipts = Table("commit_receipts", Base.metadata,
    Column("operation_id", String, primary_key=True), Column("state_version", Integer, nullable=False),
    Column("dependencies", JSON, nullable=False), Column("digest", String, nullable=False),
    Column("record_digest", String, nullable=True),
    CheckConstraint("length(trim(operation_id)) > 0 AND state_version > 0"))
