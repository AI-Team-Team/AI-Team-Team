"""Shared fixtures for state persistence tests."""

import json
import os
import shutil
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, MagicMock

from ai_team_team import (
    ATTConfig,
    ATTManager,
    Agent,
    AgentTeam,
    ApprovalPrincipal,
    CommunicationAgreement,
    CommunicationApproval,
    CommunicationRequest,
    DocumentLibrary,
)
from ai_team_team.core.communication import (
    AgreementDirection,
    CommunicationApprovalStatus,
    CommunicationRequestStatus,
    route_fingerprint,
)


class StatePersistenceTestCase(unittest.IsolatedAsyncioTestCase):
    """Creates one isolated persisted manager for recovery tests."""

    def setUp(self) -> None:
        self.old_cwd = os.getcwd()
        self.tmpdir = tempfile.mkdtemp(prefix="att_persistence_test_")
        os.chdir(self.tmpdir)
        self.db_path = os.path.join(self.tmpdir, "att_state.db")
        self.mock_react_client = MagicMock()

        async def mock_generate(
            prompt,
            system_instruction=None,
            temperature=0.3,
            require_json=False,
            **kwargs,
        ):
            if require_json:
                return (
                    '{"is_healthy": true, '
                    '"reason": "Dialogue approved."}'
                )
            return (
                "Thought: We are doing the task.\n"
                "Final Answer: Task complete!"
            )

        self.mock_react_client.generate = mock_generate
        self.root_ai = Agent(
            name="Root_AI",
            role="Architect",
            llm_client=self.mock_react_client,
        )
        self.manager = ATTManager(
            root_ai=self.root_ai,
            db_path=self.db_path,
        )
        self.manager.register_llm_client("critic", self.mock_react_client)
        self.manager.register_tools_context({"att_manager": self.manager})

    async def asyncTearDown(self) -> None:
        await self.manager.close()
        os.chdir(self.old_cwd)
        shutil.rmtree(self.tmpdir, ignore_errors=True)

