"""Maintained schema and tool manifests agree with real runtime declarations."""

import asyncio
import json
import re
import tempfile
import unittest
from pathlib import Path

from ai_team_team import ATTConfig, ATTManager, Agent
from ai_team_team.core.activity.contracts import ToolExecutionContract
from ai_team_team.database.models import Base
from ai_team_team.database.persistence.constants import STATE_SCHEMA_VERSION
from ai_team_team.tool import get_default_tools

from ._fixtures import ScriptedModelClient
from ._fixtures.schema import physical_schema
from test.test_att.test_state_integrity.test_schema_activation import REQUIRED_TABLES


ROOT = Path(__file__).resolve().parents[3]


class TestContractManifests(unittest.IsolatedAsyncioTestCase):
    def test_current_schema_document_covers_retained_and_runtime_tables(self):
        document = (ROOT / "docs/Database/Schema.md").read_text(encoding="utf-8")
        documented = set(re.findall(r"^\| `([^`]+)` \|", document, re.MULTILINE))
        # The independently maintained runtime contract remains an additional
        # expectation, rather than deriving both sides from ORM metadata.
        self.assertTrue(REQUIRED_TABLES <= documented)
        self.assertEqual(set(Base.metadata.tables), documented)

    async def test_schema_fixture_reads_committed_physical_metadata_without_llm_calls(self):
        workspace = tempfile.TemporaryDirectory(prefix="att-runtime-contract-schema-")
        self.addCleanup(workspace.cleanup)
        path = Path(workspace.name) / "state.sqlite"
        client = ScriptedModelClient()
        manager = ATTManager(Agent("Root", "Architect", client),
            ATTConfig(workspace_root=workspace.name), db_path=str(path))
        self.addAsyncCleanup(manager.close)
        manager.register_llm_client("fixture", client)
        await manager.save_state()
        tables, version, columns, errors = await asyncio.to_thread(physical_schema, path)
        self.assertTrue({"agents", "agent_messages", "libraries"} <= tables)
        self.assertEqual(version, (STATE_SCHEMA_VERSION,))
        self.assertIn("agent_id", columns)
        self.assertEqual(errors, [])
        self.assertEqual(client.requests, [])

    async def test_effect_manifest_covers_every_builtin_including_optional_memory(self):
        workspace = tempfile.TemporaryDirectory(prefix="att-runtime-contract-effects-")
        self.addCleanup(workspace.cleanup)
        client = ScriptedModelClient()
        manager = ATTManager(Agent("Root", "Architect", client),
            ATTConfig(workspace_root=workspace.name), persistence_mode="volatile")
        self.addAsyncCleanup(manager.close)
        manager.config.episodic_memory.enabled = True
        manifest = json.loads((ROOT / "test/contracts/tool_effects.json").read_text(encoding="utf-8"))
        # The complete built-in declarations are checked without optional
        # invocation controls or an external model request.
        tools = get_default_tools(manager.tools_context, manager.root_ai)
        self.assertEqual(set(manifest), set(tools))
        contracts = {}
        for name, record in manifest.items():
            with self.subTest(tool=name):
                self.assertEqual(set(record), {"contract"})
                contracts[name] = ToolExecutionContract.model_validate_json(json.dumps(record["contract"]))
                self.assertEqual(contracts[name], tools[name].execution_contract)
        self.assertTrue(contracts["write_private_file"].background_allowed)
        self.assertFalse(contracts["keep_memory_in_context"].background_allowed)
        self.assertFalse(contracts["recall_memory"].background_allowed)
        self.assertEqual(contracts["send_peer_message"].required_scope, "agent_team")
        self.assertEqual(client.requests, [])
