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

    async def test_discussions_serialize_per_team_but_not_across_teams(self):
        team_a = self.manager.create_agent_team(self.root)
        team_b = self.manager.create_agent_team(self.root)
        first_a_started = asyncio.Event()
        release_first_a = asyncio.Event()
        second_a_started = asyncio.Event()
        b_started = asyncio.Event()
        a_calls = 0

        async def fake_session(team, prompt, rounds=2, skip_audit=False):
            nonlocal a_calls
            if team is team_a:
                a_calls += 1
                if a_calls == 1:
                    first_a_started.set()
                    await release_first_a.wait()
                else:
                    second_a_started.set()
            else:
                b_started.set()
            return prompt

        self.manager._execute_team_discussion_session = fake_session
        first = asyncio.create_task(
            self.manager.execute_team_discussion(team_a, "ordinary")
        )
        await first_a_started.wait()
        emergency = asyncio.create_task(
            self.manager.execute_emergency_discussion(
                team_a, {"reason": "urgent"}, skip_audit=True
            )
        )
        other_team = asyncio.create_task(
            self.manager.execute_team_discussion(team_b, "parallel")
        )
        await asyncio.wait_for(b_started.wait(), timeout=1)
        await asyncio.sleep(0)
        self.assertFalse(second_a_started.is_set())

        release_first_a.set()
        await asyncio.wait_for(second_a_started.wait(), timeout=1)
        await asyncio.gather(first, emergency, other_team)

    async def test_token_budget_reservation_is_atomic_and_refunds_unused(self):
        started = asyncio.Event()
        release = asyncio.Event()

        class BlockingClient:
            def supports_output_token_limit(self):
                return "max_output_tokens"

            async def generate(self, prompt, max_output_tokens=None, **kwargs):
                started.set()
                await release.wait()
                return LLMResponse(
                    "ok",
                    usage={"input_tokens": 2, "output_tokens": 1},
                )

        manager = ATTManager(
            Agent("BudgetRoot", "Architect", BlockingClient()),
            ATTConfig(
                workspace_root=self.tmpdir,
                model_token_limits={"default": 10},
                model_max_output_tokens={"default": 6},
            ),
        )
        first = asyncio.create_task(
            generate_with_retry(
                manager.root_ai.llm_client,
                "12345678",
                manager=manager,
                retries=1,
            )
        )
        await started.wait()
        self.assertEqual(manager.token_budget.available("default"), 2)
        with self.assertRaises(TokenLimitExceededError):
            await generate_with_retry(
                manager.root_ai.llm_client,
                "12345678",
                manager=manager,
                retries=1,
            )
        release.set()
        await first
        self.assertEqual(manager.model_token_usage["default"], 3)
        self.assertEqual(manager.token_budget.available("default"), 7)
        await manager.close()

    async def test_cancelled_sent_request_charges_prompt_and_releases_output(self):
        started = asyncio.Event()

        class HangingClient:
            def supports_output_token_limit(self):
                return "max_output_tokens"

            async def generate(self, prompt, **kwargs):
                started.set()
                await asyncio.Event().wait()

        manager = ATTManager(
            Agent("CancelRoot", "Architect", HangingClient()),
            ATTConfig(
                workspace_root=self.tmpdir,
                model_token_limits={"default": 20},
                model_max_output_tokens={"default": 5},
            ),
        )
        task = asyncio.create_task(
            generate_with_retry(
                manager.root_ai.llm_client,
                "12345678",
                manager=manager,
                retries=1,
            )
        )
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(manager.model_token_usage["default"], 2)
        self.assertEqual(manager.token_budget.available("default"), 18)
        await manager.close()

    async def test_handler_max_tokens_cap_is_forwarded(self):
        observed = []

        async def handler(
            model_name,
            prompt,
            max_tokens,
            system_instruction=None,
            temperature=0.3,
            require_json=False,
        ):
            observed.append((model_name, max_tokens))
            return "ok"

        client = HandlerClientAdapter("bounded", handler)
        manager = ATTManager(
            Agent("HandlerRoot", "Architect", client),
            ATTConfig(
                workspace_root=self.tmpdir,
                model_token_limits={"bounded": 20},
                model_max_output_tokens={"bounded": 4},
            ),
        )
        manager.register_llm_client("bounded", client)
        await generate_with_retry(
            client, "12345678", manager=manager, retries=1
        )
        self.assertEqual(observed, [("bounded", 4)])
        await manager.close()

    async def test_governance_approval_requires_literal_boolean(self):
        events = []
        self.manager.on_system_event = lambda event, details: events.append(
            (event, details)
        )
        invalid_payloads = [
            '{"approved": "true"}',
            '{"approved": "false"}',
            '{"approved": 1}',
            '{"approved": 0}',
            '{"approved": null}',
            '{}',
        ]
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                approved, reason = parse_governance_decision(
                    payload, self.manager, "test authorization"
                )
                self.assertFalse(approved)
                self.assertIn("Invalid governance decision format", reason)
        await self.manager.flush_callbacks()
        self.assertEqual(
            sum(event == "governance_authorization_format_error" for event, _ in events),
            len(invalid_payloads),
        )
        self.assertEqual(
            parse_governance_decision(
                '{"approved": true, "reason": "valid"}',
                self.manager,
                "test authorization",
            ),
            (True, "valid"),
        )
        self.assertEqual(
            parse_governance_decision(
                '{"approved": false, "reason": "denied"}',
                self.manager,
                "test authorization",
            ),
            (False, "denied"),
        )

    async def test_corrupt_restore_preserves_live_manager_and_doclib(self):
        source_root = os.path.join(self.tmpdir, "source")
        db_path = os.path.join(self.tmpdir, "state.db")
        source = ATTManager(
            Agent("SourceRoot", "Architect", self.client),
            ATTConfig(workspace_root=source_root),
            db_path=db_path,
        )
        source.register_llm_client("test", self.client)
        persisted_team = source.create_agent_team(source.root_ai)
        persisted_team.doc_library.write_file("persisted.txt", "new state")
        await source.save_state()
        await source.close()
        with closing(sqlite3.connect(db_path)) as connection:
            connection.execute(
                "INSERT INTO team_members (team_id, agent_name) VALUES (?, ?)",
                (persisted_team.team_id, "missing-agent"),
            )
            connection.commit()

        original_team = self.manager.create_agent_team(self.root)
        original_team.doc_library.write_file("original.txt", "live state")
        old_config = self.manager.config
        old_root = self.manager.root_ai
        old_agents = self.manager.agents
        old_teams = self.manager.teams
        old_libraries = self.manager.libraries

        with self.assertRaisesRegex(StateRestoreError, "missing members"):
            await self.manager.load_state(db_path)

        self.assertIs(self.manager.config, old_config)
        self.assertIs(self.manager.root_ai, old_root)
        self.assertIs(self.manager.agents, old_agents)
        self.assertIs(self.manager.teams, old_teams)
        self.assertIs(self.manager.libraries, old_libraries)
        self.assertIn(
            "live state",
            original_team.doc_library.read_file("original.txt"),
        )

    async def test_restore_recomputes_depth_instead_of_trusting_database(self):
        source_root = os.path.join(self.tmpdir, "depth-source")
        db_path = os.path.join(self.tmpdir, "depth.db")
        source = ATTManager(
            Agent("DepthRoot", "Architect", self.client),
            ATTConfig(workspace_root=source_root),
            db_path=db_path,
        )
        source.register_llm_client("test", self.client)
        parent = source.create_agent_team(source.root_ai)
        child = source.create_agent_team(parent)
        await source.save_state()
        await source.close()
        with closing(sqlite3.connect(db_path)) as connection:
            connection.execute("UPDATE teams SET depth = 999")
            connection.commit()

        restored = ATTManager(
            Agent("DepthRoot", "Architect", self.client),
            ATTConfig(workspace_root=os.path.join(self.tmpdir, "unused")),
        )
        restored.register_llm_client("test", self.client)
        await restored.load_state(db_path)
        self.assertEqual(restored.teams[parent.team_id].depth, 1)
        self.assertEqual(restored.teams[child.team_id].depth, 2)
        await restored.close()

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
