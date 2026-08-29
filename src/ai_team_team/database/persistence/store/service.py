"""Reusable SQLAlchemy store for one ATT state database."""

import os
import sqlite3
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from ai_team_team.core.exceptions import StateRestoreError
from ai_team_team.database.models import Base
from ai_team_team.database.persistence.constants import STATE_SCHEMA_VERSION

from .materialization import StoreMaterializationMixin
from .reader import StoreReadMixin
from .writer import StoreWriteMixin


class DatabaseStore(
    StoreWriteMixin,
    StoreMaterializationMixin,
    StoreReadMixin,
):
    """Owns one reusable SQLAlchemy engine for a state database."""

    def __init__(self, db_path: str):
        self.db_path = str(Path(db_path).resolve())
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._preflight_schema()
        self.engine = create_engine(
            f"sqlite:///{self.db_path}",
            connect_args={"check_same_thread": False, "timeout": 5.0},
        )
        event.listen(self.engine, "connect", self._configure_connection)
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
            bind=self.engine,
        )

    @staticmethod
    def _configure_connection(dbapi_connection: Any, _: Any) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys = ON")
            cursor.execute("PRAGMA busy_timeout = 5000")
            cursor.execute("PRAGMA journal_mode = WAL")
        finally:
            cursor.close()

    def _preflight_schema(self) -> None:
        """Rejects unsupported databases before SQLAlchemy can modify them."""
        if not os.path.exists(self.db_path) or os.path.getsize(self.db_path) == 0:
            return
        uri = f"file:{Path(self.db_path).as_posix()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
        try:
            tables = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            user_tables = {name for name in tables if name != "sqlite_sequence"}
            if not user_tables:
                return
            if "manager_config" not in user_tables:
                raise StateRestoreError(
                    "Existing SQLite database has no ATT schema version; it was not modified."
                )
            row = connection.execute(
                "SELECT config_value FROM manager_config WHERE config_key='schema_version'"
            ).fetchone()
            version = row[0] if row else None
            if version != STATE_SCHEMA_VERSION:
                raise StateRestoreError(
                    f"Unsupported state schema version {version!r}; expected "
                    f"{STATE_SCHEMA_VERSION!r}. The database was not modified."
                )
        finally:
            connection.close()

    def close(self) -> None:
        self.engine.dispose()
