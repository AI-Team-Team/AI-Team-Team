"""Shared fixtures for ATT hardening tests."""

import asyncio
from contextlib import closing
import os
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import BaseModel

from ai_team_team import (
    ATTConfig,
    ATTManager,
    Agent,
    AuditResult,
    AuditStatus,
    StateRestoreError,
)
from ai_team_team.database.persistence import DatabaseStore
from ai_team_team.tool import get_default_tools


class ATTHardeningTestCase(unittest.IsolatedAsyncioTestCase):
    """Creates one isolated manager for hardening regression tests."""

    async def asyncSetUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="att_hardening_")
        self.client = MagicMock()
        self.client.generate = AsyncMock(return_value="Final Answer: Done")
        self.root = Agent("Root", "Architect", llm_client=self.client)
        self.manager = ATTManager(
            self.root,
            ATTConfig(
                max_delegation_depth=6,
                migration_policy="permissive",
                enable_membership_voting=True,
                workspace_root=self.tmpdir,
            ),
        )

    async def asyncTearDown(self) -> None:
        await self.manager.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)
