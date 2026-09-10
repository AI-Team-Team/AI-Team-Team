import os
import json
import shutil
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, AsyncMock, patch

# Setup paths
CURRENT_DIR = os.path.dirname(__file__)
ROOT_DIR = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from ai_team_team import ATTManager, Agent, AgentTeam, Tool, ATTConfig, DocumentLibrary

class TestDocLibrary(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.old_cwd = os.getcwd()
        self.tmpdir = tempfile.mkdtemp(prefix="att_doc_lib_test_")
        os.chdir(self.tmpdir)
        
        self.mock_client = MagicMock()
        self.mock_client.generate = AsyncMock(return_value='{"is_healthy": true, "reason": "Dialogue approved."}')
        self.root_ai = Agent(name="Root_AI", role="Architect", llm_client=self.mock_client)
        self.manager = ATTManager(root_ai=self.root_ai)
        self.manager.register_tools_context({"att_manager": self.manager})

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    async def read_as(self, team, tool, **kwargs):
        agent_token = self.manager._active_tool_agent.set(team.members[0])
        team_token = self.manager._active_team.set(team)
        try:
            return await tool(**kwargs)
        finally:
            self.manager._active_team.reset(team_token)
            self.manager._active_tool_agent.reset(agent_token)

    async def test_built_in_library_creation(self):
        """Verify that a team gets a default built-in DocLib on creation."""
        team = self.manager.create_agent_team(creator=self.root_ai, member_count=3, is_public_visible=True)
        self.assertIsNotNone(team.doc_library)
        self.assertEqual(team.doc_library.owner_team_id, team.team_id)
        self.assertTrue(team.doc_library.is_public_visible)
        
        # Verify registered in manager
        lib_id = f"DL-{team.team_id}"
        self.assertIn(lib_id, self.manager.libraries)

    async def test_initial_documents_injection(self):
        """Verify that initial_docs are written to the built-in library upon creation."""
        initial_docs = {
            "specs/spec.txt": "Core specification content",
            "notes.md": "# Quick notes"
        }
        team = self.manager.create_agent_team(
            creator=self.root_ai,
            member_count=3,
            initial_docs=initial_docs
        )
        lib = team.doc_library
        self.assertIsNotNone(lib)
        
        # Read files
        spec_content = lib.read_file("specs/spec.txt")
        self.assertIn("Core specification content", spec_content)
        
        notes_content = lib.read_file("notes.md")
        self.assertIn("# Quick notes", notes_content)

    async def test_public_visibility_listing(self):
        """Verify discovery of publicly visible libraries and listing."""
        team_a = self.manager.create_agent_team(creator=self.root_ai, member_count=3, is_public_visible=True)
        team_b = self.manager.create_agent_team(creator=self.root_ai, member_count=3, is_public_visible=False)
        
        # We call the tool list_public_libraries
        list_tool = team_a.tools["list_public_libraries"]
        res = await list_tool()
        
        self.assertIn(team_a.doc_library.lib_id, res)
        self.assertNotIn(team_b.doc_library.lib_id, res)

    async def test_permission_acl_isolation(self):
        """Verify permissions: read/write permissions block or allow access correctly."""
        team_a = self.manager.create_agent_team(creator=self.root_ai, member_count=3)
        team_b = self.manager.create_agent_team(creator=self.root_ai, member_count=3)
        
        lib_a_id = team_a.doc_library.lib_id
        
        # Team A writes a file to its own library
        write_tool_a = team_a.tools["write_library_file"]
        res_write = await write_tool_a(lib_id=lib_a_id, path="shared.txt", content="Secret data")
        self.assertIn("Successfully written", res_write)
        
        # Team B tries to read it -> Denied
        read_tool_b = team_b.tools["read_library_file"]
        res_read_denied = await self.read_as(
            team_b, read_tool_b, lib_id=lib_a_id, path="shared.txt"
        )
        self.assertIn("Permission denied", res_read_denied)
        
        # Team A grants READ access to Team B
        grant_tool_a = team_a.tools["grant_library_permission"]
        res_grant = await grant_tool_a(lib_id=lib_a_id, path="shared.txt", target_team_id=team_b.team_id, permission="READ")
        self.assertIn("Successfully granted", res_grant)
        
        # Team B reads it now -> Success
        res_read_success = await self.read_as(
            team_b, read_tool_b, lib_id=lib_a_id, path="shared.txt"
        )
        self.assertIn("Secret data", json.loads(res_read_success)["content"])
        
        # Team B tries to delete/write it -> Denied (only has READ)
        delete_tool_b = team_b.tools["delete_library_file"]
        res_delete_denied = await delete_tool_b(lib_id=lib_a_id, path="shared.txt")
        self.assertIn("Permission denied", res_delete_denied)

    async def test_dispatch_subagent_with_docs(self):
        """Verify that dispatch_subagent correctly propagates documents to the spawned child team."""
        preset = self.manager.get_preset("generic")
        team = self.manager.create_agent_team(creator=self.root_ai, member_count=3)
        dispatch_tool = team.tools["dispatch_subagent"]
        
        # We mock execute_team_discussion to capture the spawned team
        original_execute = self.manager.execute_team_discussion
        captured_child = None
        
        async def mock_execute(child_team, prompt, rounds=2):
            nonlocal captured_child
            captured_child = child_team
            return "Result"
            
        self.manager.execute_team_discussion = mock_execute
        
        try:
            initial_documents = {
                "guide.txt": "Subagent guidelines",
                "rules/rules.md": "# Safety first"
            }
            await dispatch_tool(
                task="Analyze task",
                team_purpose="Analysis team",
                member_configs={
                    "Agent1": {"model": "default"},
                    "Agent2": {"model": "default"},
                    "Agent3": {"model": "default"}
                },
                initial_documents=initial_documents
            )
        finally:
            self.manager.execute_team_discussion = original_execute
            
        self.assertIsNotNone(captured_child)
        self.assertIsNotNone(captured_child.doc_library)
        
        # Read propagated files from child library
        guide = captured_child.doc_library.read_file("guide.txt")
        self.assertIn("Subagent guidelines", guide)
        
        rules = captured_child.doc_library.read_file("rules/rules.md")
        self.assertIn("Safety first", rules)

    async def test_token_bounded_library_file_reading(self):
        """Verify that model reads are bounded by content tokens rather than file size."""
        self.manager.config.file_read.max_read_tokens = 40
        team = self.manager.create_agent_team(creator=self.root_ai, member_count=3)
        lib_id = team.doc_library.lib_id

        # Write large content (exceeds 50 KB)
        large_content = "Line content\n" * 5000  # ~ 60 KB
        write_tool = team.tools["write_library_file"]
        await write_tool(lib_id=lib_id, path="large.log", content=large_content)

        read_tool = team.tools["read_library_file"]

        first = json.loads(
            await self.read_as(team, read_tool, lib_id=lib_id, path="large.log")
        )
        self.assertEqual(first["status"], "partial")
        self.assertLessEqual(first["content_token_count"], 40)
        self.assertNotIn("LARGE FILE WARNING", first["content"])

        selected = json.loads(
            await self.read_as(
                team,
                read_tool,
                lib_id=lib_id,
                path="large.log",
                start_line=10,
                end_line=15,
            )
        )
        self.assertLessEqual(selected["content_token_count"], 40)
        self.assertTrue(selected["content"].startswith("Line content"))
        self.assertNotIn("10: ", selected["content"])

    async def test_prefix_bypass_path_traversal_prevention(self):
        """Verify that sibling prefix traversal (e.g. DL-AT-abc123_private) is blocked."""
        team = self.manager.create_agent_team(creator=self.root_ai, member_count=3)
        lib = team.doc_library
        
        base_dir_name = os.path.basename(lib.root_dir)
        traversal_path = f"../{base_dir_name}_hack/secrets.txt"
        
        with self.assertRaises(PermissionError):
            lib._resolve_path(traversal_path)

        for invalid_path in ("", ".", "..", "../secret.txt"):
            with self.subTest(path=invalid_path):
                with self.assertRaises(PermissionError):
                    lib.write_file(invalid_path, "blocked")

        for root_path in ("/", "///"):
            with self.subTest(path=root_path):
                with self.assertRaises(PermissionError):
                    lib.delete_file(root_path)

    async def test_portable_file_operations_without_dir_fd(self):
        """Verify the checked fallback used on platforms without dir_fd."""
        team = self.manager.create_agent_team(
            creator=self.root_ai,
            member_count=3,
        )
        library = team.doc_library
        with patch.object(
            DocumentLibrary,
            "_supports_secure_dir_fd",
            return_value=False,
        ):
            library.write_file("portable/note.txt", "portable content")
            self.assertIn(
                "portable content",
                library.read_file("portable/note.txt"),
            )
            library.move_file(
                "portable/note.txt",
                "portable/moved.txt",
            )
            self.assertTrue(library.is_file("portable/moved.txt"))

if __name__ == "__main__":
    unittest.main()
