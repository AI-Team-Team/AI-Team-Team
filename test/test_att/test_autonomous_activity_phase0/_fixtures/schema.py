"""Read actual SQLite metadata without creating or repairing schema objects."""

import sqlite3
from contextlib import closing
from pathlib import Path


def physical_schema(database_path: Path):
    with closing(sqlite3.connect(database_path.as_uri() + "?mode=ro", uri=True)) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        version = connection.execute(
            "SELECT config_value FROM manager_config WHERE config_key='schema_version'"
        ).fetchone()
        columns = {row[1] for row in connection.execute("PRAGMA table_info(agent_messages)")}
        foreign_key_errors = list(connection.execute("PRAGMA foreign_key_check"))
        return tables, version, columns, foreign_key_errors
