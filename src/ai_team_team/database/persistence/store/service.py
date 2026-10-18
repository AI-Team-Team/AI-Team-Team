"""Reusable SQLAlchemy store for one ATT state database."""

import os
import sqlite3
import uuid
import re
import tempfile
import shutil
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import CreateIndex, CreateTable
from sqlalchemy.dialects.sqlite import dialect

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
        fresh = self._preflight_schema(self.db_path)
        self.engine = create_engine(
            f"sqlite:///{self.db_path}",
            connect_args={"check_same_thread": False, "timeout": 5.0},
            hide_parameters=True,
        )
        event.listen(self.engine, "connect", self._configure_connection)
        try:
            if fresh:
                self._initialize_schema()
        except BaseException:
            self.engine.dispose()
            raise
        self.session_factory = sessionmaker(
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
            bind=self.engine,
        )
        from .validation.database import DatabaseValidationCache
        self._validation = DatabaseValidationCache(self.engine, self.db_path)

    def _initialize_schema(self):
        with self.engine.connect() as connection:
            # Explicit BEGIN also makes SQLite DDL rollback as one layout.
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                Base.metadata.create_all(connection)
                connection.execute(text("INSERT INTO manager_config (config_key, config_value) VALUES ('schema_version', :version)"), {"version": STATE_SCHEMA_VERSION})
                connection.execute(text("INSERT INTO manager_config (config_key, config_value) VALUES ('checkpoint_id', :identity)"), {"identity": uuid.uuid4().hex})
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    @staticmethod
    def _configure_connection(dbapi_connection: Any, _: Any) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys = ON")
            cursor.execute("PRAGMA busy_timeout = 5000")
            cursor.execute("PRAGMA journal_mode = WAL")
        finally:
            cursor.close()

    @staticmethod
    def _preflight_schema(db_path: str) -> bool:
        """Rejects unsupported databases before SQLAlchemy can modify them."""
        if not os.path.exists(db_path) or os.path.getsize(db_path) == 0:
            return True
        temporary = None
        wal_path, shm_path = f"{db_path}-wal", f"{db_path}-shm"
        inspected_path = db_path
        try:
            if os.path.exists(wal_path) and not os.path.exists(shm_path):
                # Rebuild a crash-left WAL index only in a detached copy.
                temporary = tempfile.TemporaryDirectory(prefix="att-schema-preflight-")
                inspected_path = str(Path(temporary.name) / "checkpoint.sqlite")
                shutil.copyfile(db_path, inspected_path)
                shutil.copyfile(wal_path, f"{inspected_path}-wal")
            immutable = "" if os.path.exists(wal_path) else "&immutable=1"
            uri = f"{Path(inspected_path).as_uri()}?mode=ro{immutable}"
            connection = sqlite3.connect(uri, uri=True)
        except BaseException:
            if temporary is not None:
                temporary.cleanup()
            raise
        try:
            tables = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            user_tables = {name for name in tables if name != "sqlite_sequence"}
            if not user_tables:
                return True
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
            for name, table in Base.metadata.tables.items():
                if name not in user_tables:
                    raise StateRestoreError(f"The supported checkpoint is missing table {name!r}; it was not modified.")
                actual = {row[1] for row in connection.execute(f'PRAGMA table_info("{name}")')}
                if actual != set(table.columns.keys()):
                    raise StateRestoreError(f"The supported checkpoint has an invalid {name!r} layout; it was not modified.")
                # Compare physical constraints before any writable connection;
                # matching column names alone can conceal removed FKs/checks.
                normalize = lambda sql: re.sub(r"\s+", " ", sql.strip())
                declared = normalize(str(CreateTable(table).compile(dialect=dialect())))
                stored = connection.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()[0]
                if normalize(stored) != declared:
                    raise StateRestoreError(f"The supported checkpoint has invalid constraints for {name!r}; it was not modified.")
                for index in table.indexes:
                    stored_index = connection.execute("SELECT sql FROM sqlite_master WHERE type='index' AND name=?", (index.name,)).fetchone()
                    if stored_index is None or normalize(stored_index[0]) != normalize(str(CreateIndex(index).compile(dialect=dialect()))):
                        raise StateRestoreError(f"The supported checkpoint is missing or has modified index {index.name!r}; it was not modified.")
            return False
        finally:
            connection.close()
            if temporary is not None:
                temporary.cleanup()

    def close(self) -> None:
        self._validation.finish()
        self.engine.dispose()
