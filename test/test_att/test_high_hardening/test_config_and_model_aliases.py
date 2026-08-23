import asyncio
import multiprocessing
import os
import shutil
import sqlite3
import tempfile
import threading
import time
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import AsyncMock, patch

from ai_team_team import (
    AmbiguousTeamContextError,
    ATTConfig,
    ATTException,
    ATTManager,
    Agent,
    AuditResult,
    AuditStatus,
    DatabaseOwnershipError,
    LLMGenerationError,
    StateRestoreError,
)
from ai_team_team.core.utils import generate_with_retry
from ai_team_team.database.persistence import (
    DatabaseStore,
    PersistenceCoordinator,
)
from ai_team_team.tool import get_default_tools


class EchoClient:
    async def generate(self, prompt, system_instruction=None, **kwargs):
        return "Final Answer: complete"


def _write_and_hold(db_path, workspace, ready, release):
    import warnings

    warnings.filterwarnings("ignore", category=ResourceWarning)

    async def run():
        client = EchoClient()
        manager = ATTManager(
            Agent("ProcessRoot", "Architect", client),
            ATTConfig(workspace_root=workspace),
            db_path=db_path,
        )
        manager.register_llm_client("process-model", client)
        team = manager.create_agent_team(manager.root_ai)
        await manager.save_state()
        ready.put(team.team_id)
        release.wait(10)

    asyncio.run(run())

class TestHighHardening(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="att_high_")
        self.client = EchoClient()

    async def asyncTearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_numeric_config_validation_applies_to_mutation(self):
        positive_fields = {
            "subagent_discussion_rounds",
            "react_max_steps",
            "max_memory_turns",
            "inbox_summarize_threshold_chars",
            "emergency_discussion_rounds",
            "max_tool_rounds",
        }
        for field in positive_fields:
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    ATTConfig(**{field: 0})

        config = ATTConfig(
            max_migrations_per_team_discussion=0,
            llm_max_retries=0,
            max_tool_argument_retries=0,
            max_tool_execution_retries=0,
            llm_retry_backoff_factor=0,
            model_token_limits={"disabled": 0},
        )
        with self.assertRaises(ValueError):
            config.react_max_steps = 0
        with self.assertRaises(ValueError):
            config.model_token_limits["bad"] = -1
        with self.assertRaises(ValueError):
            config.model_max_output_tokens.update({"bad": 0})
        self.assertFalse(hasattr(config, "strict_state_persistence"))
    async def test_runtime_execution_scales_are_validated(self):
        manager = ATTManager(
            Agent("Root", "Architect", self.client),
            ATTConfig(workspace_root=self.tmpdir),
        )
        team = manager.create_agent_team(manager.root_ai)
        with self.assertRaisesRegex(ValueError, "max_steps"):
            await team.execute_reasoning_step(
                team.members[0], "prompt", "system", max_steps=0
            )
        with self.assertRaisesRegex(ValueError, "rounds"):
            await manager.execute_team_discussion(team, "prompt", rounds=0)
        await manager.close()
    async def test_save_lists_every_agent_without_stable_alias(self):
        root_client = EchoClient()
        manager = ATTManager(
            Agent("Root", "Architect", root_client),
            ATTConfig(workspace_root=self.tmpdir),
        )
        team = manager.create_agent_team(manager.root_ai)
        team.members[0].llm_client = EchoClient()
        path = os.path.join(self.tmpdir, "aliases.db")
        with self.assertRaisesRegex(ValueError, "Root") as raised:
            await manager.save_state(path)
        self.assertIn(team.members[0].name, str(raised.exception))
        await manager.close()
    async def test_model_name_is_not_alias_without_identity_binding(self):
        client = EchoClient()
        client.model_name = "claimed-name"
        manager = ATTManager(
            Agent("Root", "Architect", client),
            ATTConfig(workspace_root=self.tmpdir),
        )
        with self.assertRaises(ValueError):
            await manager.save_state(os.path.join(self.tmpdir, "model-name.db"))
        manager.register_llm_client("claimed-name", client)
        await manager.save_state(os.path.join(self.tmpdir, "model-name.db"))
        await manager.close()
