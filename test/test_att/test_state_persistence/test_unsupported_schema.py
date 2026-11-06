"""Every unsupported schema is rejected before DDL or workspace publication."""

import hashlib
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path

from ai_team_team import ATTConfig, ATTManager, Agent, StateRestoreError
from ai_team_team.database.persistence.constants import STATE_SCHEMA_VERSION
from test.test_att.test_state_integrity._support import make_manager


class UnsupportedSchemaTests(unittest.IsolatedAsyncioTestCase):
    async def test_old_future_and_malformed_versions_leave_database_and_workspace_unchanged(self):
        manager, path, client = make_manager(self)
        await manager.save_state()
        await manager.close()
        workspace = Path(manager.config.workspace_root)

        def files():
            return {item.relative_to(workspace).as_posix(): hashlib.sha256(item.read_bytes()).hexdigest()
                    for item in workspace.rglob("*") if item.is_file()}

        for version in ("0", "11", "12", "13", "14", "15", str(int(STATE_SCHEMA_VERSION) + 1), "999", "invalid", ""):
            with self.subTest(schema=version):
                with closing(sqlite3.connect(path)) as database:
                    database.execute("UPDATE manager_config SET config_value=? WHERE config_key='schema_version'", (version,))
                    database.commit()
                before = files()
                with self.assertRaises(StateRestoreError):
                    ATTManager(Agent("RejectedRoot", "Architect", client),
                        ATTConfig(workspace_root=str(workspace)), db_path=path)
                self.assertEqual(files(), before)
