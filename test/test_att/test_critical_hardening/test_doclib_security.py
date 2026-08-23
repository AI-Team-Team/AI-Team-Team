import asyncio
from contextlib import closing
import os
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from ai_team_team import ATTConfig, ATTManager, Agent, StateRestoreError
from ai_team_team.core.exceptions import TokenLimitExceededError
from ai_team_team.core.adapters import HandlerClientAdapter
from ai_team_team.core.policies import parse_governance_decision
from ai_team_team.core.response import LLMResponse
from ai_team_team.core.utils import generate_with_retry
from ai_team_team.tool import get_default_tools


class SimpleClient:
    async def generate(
        self,
        prompt,
        system_instruction=None,
        temperature=0.3,
        require_json=False,
        **kwargs,
    ):
        return "Final Answer: complete"


class TestCriticalHardening(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="att_critical_")
        self.client = SimpleClient()
        self.root = Agent("Root", "Architect", self.client)
        self.manager = ATTManager(
            self.root,
            ATTConfig(
                workspace_root=self.tmpdir,
                migration_policy="permissive",
            ),
        )
        self.manager.register_llm_client("test", self.client)

    async def asyncTearDown(self):
        await self.manager.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    async def test_managed_doclib_link_enforces_live_target_acl(self):
        team_a = self.manager.create_agent_team(self.root)
        team_b = self.manager.create_agent_team(self.root)
        tools_a = get_default_tools({"att_manager": self.manager}, team_a)
        tools_b = get_default_tools({"att_manager": self.manager}, team_b)
        source_lib = team_a.doc_library.lib_id
        target_lib = team_b.doc_library.lib_id

        await tools_b["write_library_file"](
            target_lib, "shared.txt", "source content"
        )
        await tools_b["grant_library_permission"](
            target_lib, "shared.txt", team_a.team_id, "READ"
        )
        created = await tools_a["create_library_link"](
            source_lib,
            "links/shared.txt",
            target_lib,
            "shared.txt",
        )
        self.assertIn("Successfully linked", created)
        self.assertIn(
            "source content",
            await tools_a["read_library_file"](
                source_lib, "links/shared.txt"
            ),
        )
        denied_write = await tools_a["write_library_file"](
            source_lib, "links/shared.txt", "changed"
        )
        self.assertIn("Permission denied", denied_write)

        await tools_b["grant_library_permission"](
            target_lib, "shared.txt", team_a.team_id, "WRITE"
        )
        self.assertIn(
            "Successfully written",
            await tools_a["write_library_file"](
                source_lib, "links/shared.txt", "changed"
            ),
        )
        self.assertIn(
            "changed", team_b.doc_library.read_file("shared.txt")
        )

        await tools_b["revoke_library_permission"](
            target_lib, "shared.txt", team_a.team_id
        )
        revoked = await tools_a["read_library_file"](
            source_lib, "links/shared.txt"
        )
        self.assertIn("Permission denied", revoked)
        deleted = await tools_a["delete_library_file"](
            source_lib, "links/shared.txt"
        )
        self.assertIn("deleted managed link", deleted)
        self.assertIn(
            "changed", team_b.doc_library.read_file("shared.txt")
        )

    async def test_managed_doclib_links_persist_and_restore(self):
        workspace = os.path.join(self.tmpdir, "link-state")
        db_path = os.path.join(self.tmpdir, "links.db")
        manager = ATTManager(
            Agent("LinkRoot", "Architect", self.client),
            ATTConfig(workspace_root=workspace),
            db_path=db_path,
        )
        manager.register_llm_client("test", self.client)
        team_a = manager.create_agent_team(manager.root_ai)
        team_b = manager.create_agent_team(manager.root_ai)
        tools_a = get_default_tools({"att_manager": manager}, team_a)
        tools_b = get_default_tools({"att_manager": manager}, team_b)
        await tools_b["write_library_file"](
            team_b.doc_library.lib_id, "target.txt", "persisted target"
        )
        await tools_b["grant_library_permission"](
            team_b.doc_library.lib_id,
            "target.txt",
            team_a.team_id,
            "READ",
        )
        await tools_a["create_library_link"](
            team_a.doc_library.lib_id,
            "reference.txt",
            team_b.doc_library.lib_id,
            "target.txt",
        )
        await manager.save_state()
        await manager.close()

        restored = ATTManager(
            Agent("LinkRoot", "Architect", self.client),
            ATTConfig(workspace_root=os.path.join(self.tmpdir, "unused-links")),
        )
        restored.register_llm_client("test", self.client)
        await restored.load_state(db_path)
        restored_a = restored.teams[team_a.team_id]
        restored_tools = get_default_tools(
            {"att_manager": restored}, restored_a
        )
        self.assertIn(
            "persisted target",
            await restored_tools["read_library_file"](
                restored_a.doc_library.lib_id, "reference.txt"
            ),
        )
        await restored.close()

    async def test_managed_doclib_link_cycle_is_rejected(self):
        team_a = self.manager.create_agent_team(self.root)
        team_b = self.manager.create_agent_team(self.root)
        lib_a = team_a.doc_library.lib_id
        lib_b = team_b.doc_library.lib_id
        self.manager.library_permissions.setdefault(lib_b, {}).setdefault(
            "/b.txt", {}
        )[team_a.team_id] = "READ"
        self.manager.library_links = {
            lib_a: {
                "a.txt": {
                    "target_lib_id": lib_b,
                    "target_path": "b.txt",
                }
            },
            lib_b: {
                "b.txt": {
                    "target_lib_id": lib_a,
                    "target_path": "a.txt",
                }
            },
        }
        with self.assertRaisesRegex(ValueError, "cycle"):
            await self.manager.read_library_file(
                team_a.team_id, lib_a, "a.txt"
            )

    async def test_late_restore_publication_failure_rolls_back_files(self):
        source_root = os.path.join(self.tmpdir, "publish-source")
        db_path = os.path.join(self.tmpdir, "publish.db")
        source = ATTManager(
            Agent("PublishRoot", "Architect", self.client),
            ATTConfig(workspace_root=source_root),
            db_path=db_path,
        )
        source.register_llm_client("test", self.client)
        first = source.create_agent_team(source.root_ai)
        second = source.create_agent_team(source.root_ai)
        first.doc_library.write_file("first.txt", "first original")
        second.doc_library.write_file("second.txt", "second original")
        await source.save_state()
        await source.close()

        live_team = self.manager.create_agent_team(self.root)
        live_team.doc_library.write_file("live.txt", "still live")
        old_teams = self.manager.teams
        real_replace = os.replace
        publication_count = 0
        def fail_second_publication(src, dst):
            nonlocal publication_count
            if os.path.basename(dst).startswith("DL-"):
                publication_count += 1
                if publication_count == 4:
                    raise OSError("simulated publication failure")
            return real_replace(src, dst)

        with patch("ai_team_team.core.manager.os.replace", fail_second_publication):
            with self.assertRaisesRegex(
                StateRestoreError, "simulated publication failure"
            ):
                await self.manager.load_state(db_path)

        self.assertIs(self.manager.teams, old_teams)
        self.assertIn("still live", live_team.doc_library.read_file("live.txt"))
        self.assertIn("first original", first.doc_library.read_file("first.txt"))
        self.assertIn("second original", second.doc_library.read_file("second.txt"))

    def test_native_symlink_cannot_escape_doclib(self):
        team = self.manager.create_agent_team(self.root)
        outside = os.path.join(self.tmpdir, "outside.txt")
        with open(outside, "w", encoding="utf-8") as stream:
            stream.write("outside")
        os.symlink(
            outside,
            os.path.join(team.doc_library.root_dir, "escape.txt"),
        )
        with self.assertRaises(PermissionError):
            team.doc_library.read_file("escape.txt")
        with self.assertRaises(PermissionError):
            team.doc_library.write_file("escape.txt", "overwrite")
        with open(outside, "r", encoding="utf-8") as stream:
            self.assertEqual(stream.read(), "outside")


if __name__ == "__main__":
    unittest.main()

