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
        self.captured_instructions = []
        calls_by_instruction = {}

        async def mock_generate(
            prompt,
            system_instruction=None,
            temperature=0.3,
            require_json=False,
            **kwargs,
        ):
            self.captured_instructions.append(system_instruction)
            if require_json:
                return (
                    '{"is_healthy": true, '
                    '"reason": "Dialogue approved."}'
                )
            key = system_instruction or ""
            calls_by_instruction[key] = calls_by_instruction.get(key, 0) + 1
            return "Final Answer: Task complete!" if calls_by_instruction[key] % 2 else "Action: set_activity_intent(intent={'kind': 'idle'})"

        self.mock_react_client.generate = mock_generate
        self.mock_react_client.supports_native_tool_calling = lambda: False
        self.root_ai = Agent(
            name="Root_AI",
            role="Architect",
            llm_client=self.mock_react_client,
        )
        self.manager = ATTManager(
            root_ai=self.root_ai,
            db_path=self.db_path,
            persistence_mode=("durable" if (self.db_path) else "volatile"),
        )
        self.manager.register_llm_client("critic", self.mock_react_client)
        self.manager.register_tools_context({"att_manager": self.manager})

    async def asyncTearDown(self) -> None:
        await self.manager.close()
        os.chdir(self.old_cwd)
        shutil.rmtree(self.tmpdir, ignore_errors=True)

