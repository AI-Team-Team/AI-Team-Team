"""The inventory and target declarations cover actual existing entry points."""

import asyncio
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_team_team import ATTConfig, ATTManager, Agent
from ai_team_team.core.activity.contracts import ToolExecutionContract
from ai_team_team.tool import get_default_tools
from ai_team_team.database.persistence.constants import STATE_SCHEMA_VERSION

from test.test_att.test_autonomous_activity_phase0._fixtures import ScriptedModelClient
from test.test_att.test_autonomous_activity_phase0 import _inventory
from test.test_att.test_autonomous_activity_phase0._inventory import AREAS, ROOT, SELECTORS, collect
from test.test_att.test_autonomous_activity_phase0._fixtures.schema import physical_schema
from test.test_att.test_autonomous_activity_phase0.spec_schema_activation import REQUIRED_TABLES


ARTIFACTS = ROOT / "docs/dev/autonomous_activity"


class TestFreezeArtifacts(unittest.IsolatedAsyncioTestCase):
    def test_physical_schema_spec_covers_every_new_or_replacement_table(self):
        document = (ARTIFACTS / "Schema_12.md").read_text(encoding="utf-8")
        new_groups = document.split("## Personal Admission and Model Evidence\n", 1)[1]
        documented = set(re.findall(r"^\| `([^`]+)` \|", new_groups, flags=re.MULTILINE))
        self.assertEqual(REQUIRED_TABLES, documented)

    async def test_schema_fixture_reads_committed_physical_metadata_without_llm_calls(self):
        workspace = tempfile.TemporaryDirectory(prefix="att-phase0-schema-fixture-")
        self.addCleanup(workspace.cleanup)
        database_path = Path(workspace.name).resolve() / "state.sqlite"
        client = ScriptedModelClient()
        manager = ATTManager(
            Agent("Root", "Architect", client),
            ATTConfig(workspace_root=workspace.name),
            db_path=str(database_path),
        )
        self.addAsyncCleanup(manager.close)
        manager.register_llm_client("fixture", client)
        await manager.save_state()
        tables, version, columns, foreign_key_errors = await asyncio.to_thread(
            physical_schema, database_path
        )
        self.assertTrue({"agents", "agent_messages", "libraries"}.issubset(tables))
        self.assertEqual(version, (STATE_SCHEMA_VERSION,))
        self.assertIn("agent_id", columns)
        self.assertEqual(foreign_key_errors, [])
        self.assertEqual(client.requests, [])

    def test_inventory_includes_both_workflow_extensions_and_other_source_formats(self):
        with tempfile.TemporaryDirectory(prefix="att-phase0-inventory-") as workspace:
            root = Path(workspace)
            workflows = root / ".github"
            workflows.mkdir()
            names = {f"fixture{suffix}" for suffix in (".py", ".md", ".yaml", ".yml", ".toml")}
            for name in names:
                (workflows / name).write_text("execute_team_discussion()\n", encoding="utf-8")
            with patch.object(_inventory, "ROOT", root):
                found = _inventory.collect(".github")
        self.assertEqual({item["path"] for item in found}, {f".github/{name}" for name in names})
        self.assertTrue(all(item["hits"][0][0] == 1 for item in found))

    def test_inventory_matches_the_complete_current_scan(self):
        recorded = json.loads((ARTIFACTS / "round_dependencies.json").read_text(encoding="utf-8"))
        self.assertEqual(
            recorded["files"],
            collect(),
            "Update the reviewed inventory after intentionally changing dependencies.",
        )
        self.assertEqual(recorded["selectors"], SELECTORS)
        self.assertEqual(recorded["areas"], list(AREAS))

    async def test_effect_manifest_covers_every_builtin_including_optional_memory(self):
        workspace = tempfile.TemporaryDirectory(prefix="att-phase0-effects-")
        self.addCleanup(workspace.cleanup)
        manager = ATTManager(
            Agent("Root", "Architect", ScriptedModelClient()),
            ATTConfig(workspace_root=workspace.name),
        )
        self.addAsyncCleanup(manager.close)
        # Build optional tool schemas without dispatching an indexer or model.
        manager.config.episodic_memory.enabled = True
        tools = get_default_tools(manager.tools_context, manager.root_ai)
        manifest = json.loads((ARTIFACTS / "tool_effects.json").read_text(encoding="utf-8"))
        self.assertEqual(set(manifest), set(tools))
        contracts = {}
        for name, record in manifest.items():
            with self.subTest(tool=name):
                contracts[name] = ToolExecutionContract.model_validate_json(
                    json.dumps(record["contract"])
                )
                self.assertIn(record["disposition"], {"retain", "replace"})
        self.assertTrue(contracts["write_private_file"].background_allowed)
        self.assertFalse(contracts["keep_memory_in_context"].background_allowed)
        self.assertFalse(contracts["recall_memory"].background_allowed)
        self.assertEqual(contracts["send_peer_message"].required_scope, "agent_team")
