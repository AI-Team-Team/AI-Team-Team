import asyncio
import json
import os
import tempfile
import threading
import unittest

from tokenizers import Tokenizer
from tokenizers.models import WordLevel
from tokenizers.pre_tokenizers import Whitespace

from ai_team_team import ATTConfig, ATTManager, Agent, FileReadConfig, FileReadStatus
from ai_team_team.core.exceptions import TokenLimitExceededError
from ai_team_team.core.response import ToolResultStatus
from ai_team_team.core.tool_runtime import ToolExecutor
from ai_team_team.gated_reader import (
    FileVersionChangedError,
    TokenCounterUnavailableError,
)


class PlainClient:
    pass


class CharacterCountingClient:
    def count_tokens(self, text):
        return len(text)


class WordCountingClient:
    async def count_tokens(self, text):
        return len(text.split())


class BlockingCountingClient:
    def __init__(self):
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def count_tokens(self, text):
        self.started.set()
        await self.release.wait()
        return len(text)


class ModelFileReadingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="att_model_read_")
        self.manager = ATTManager(
            Agent("Root", "Architect", PlainClient()),
            ATTConfig(workspace_root=self.temporary.name),
        )
        self.team = self.manager.create_agent_team(self.manager.root_ai)
        self.agent = self.team.members[0]

    async def asyncTearDown(self):
        await self.manager.close()
        self.temporary.cleanup()

    async def execute_read(self, tool_name, **kwargs):
        return await ToolExecutor(
            self.team, self.agent, self.manager
        ).execute(
            tool_name,
            kwargs=kwargs,
            call_id=f"test:{tool_name}",
            tools=self.team.tools,
        )

    async def test_file_read_config_is_strict_and_assignment_validated(self):
        with self.assertRaises(ValueError):
            FileReadConfig(max_read_tokens=0)
        with self.assertRaises(ValueError):
            FileReadConfig(tokenizer_fallback="optimistic")
        with self.assertRaises(ValueError):
            FileReadConfig(extra_setting=True)
        config = FileReadConfig()
        with self.assertRaises(ValueError):
            config.max_read_tokens = 0

        read_schema = self.team.tools["read_library_file"].json_schema
        self.assertEqual(read_schema["properties"]["start_line"]["minimum"], 1)
        invalid = await self.execute_read(
            "read_library_file",
            lib_id=self.team.doc_library.lib_id,
            path="anything.txt",
            start_line=0,
        )
        self.assertEqual(invalid.status, ToolResultStatus.INVALID_ARGUMENTS)

    async def test_team_and_private_reads_share_host_counter_behavior(self):
        self.manager.config.file_read.max_read_tokens = 5
        self.manager.register_token_counter("default", len)
        self.team.doc_library.write_file("team.txt", "abcdefghij")
        private = self.manager.libraries[self.agent.private_doc_library_id]
        private.write_file("private.txt", "abcdefghij")

        team_result = await self.execute_read(
            "read_library_file",
            lib_id=self.team.doc_library.lib_id,
            path="team.txt",
        )
        private_result = await self.execute_read(
            "read_private_file", path="private.txt"
        )

        self.assertEqual(team_result.status, ToolResultStatus.SUCCESS)
        self.assertEqual(private_result.status, ToolResultStatus.SUCCESS)
        for result in (team_result, private_result):
            payload = json.loads(result.content)
            self.assertEqual(payload["content"], "abcde")
            self.assertEqual(payload["status"], "partial")
            self.assertEqual(payload["token_count_method"], "host_counter")

    async def test_sync_host_counter_does_not_run_on_event_loop_thread(self):
        event_loop_thread = threading.get_ident()
        counter_threads = []

        def count(text):
            counter_threads.append(threading.get_ident())
            return len(text)

        self.manager.register_token_counter("default", count)
        self.team.doc_library.write_file("thread.txt", "content")

        result = await self.execute_read(
            "read_library_file",
            lib_id=self.team.doc_library.lib_id,
            path="thread.txt",
        )

        self.assertEqual(result.status, ToolResultStatus.SUCCESS)
        self.assertTrue(counter_threads)
        self.assertNotIn(event_loop_thread, counter_threads)

    async def test_read_fails_if_managed_link_acl_is_revoked_in_flight(self):
        target_team = self.manager.create_agent_team(self.manager.root_ai)
        source_lib_id = self.team.doc_library.lib_id
        target_lib_id = target_team.doc_library.lib_id
        target_team.doc_library.write_file("shared.txt", "private target")
        self.manager.library_permissions.setdefault(target_lib_id, {}).setdefault(
            "/shared.txt", {}
        )[self.team.team_id] = "READ"
        await self.manager.create_library_link(
            self.team.team_id,
            source_lib_id,
            "linked.txt",
            target_lib_id,
            "shared.txt",
        )
        client = BlockingCountingClient()
        self.agent.llm_client = client
        self.manager.register_llm_client("blocking", client)

        agent_token = self.manager._active_tool_agent.set(self.agent)
        team_token = self.manager._active_team.set(self.team)
        try:
            read_task = asyncio.create_task(
                self.manager.read_library_file(
                    self.team.team_id,
                    source_lib_id,
                    "linked.txt",
                )
            )
            await client.started.wait()
            del self.manager.library_permissions[target_lib_id]["/shared.txt"][
                self.team.team_id
            ]
            client.release.set()
            with self.assertRaises(PermissionError):
                await read_task
        finally:
            self.manager._active_team.reset(team_token)
            self.manager._active_tool_agent.reset(agent_token)

    async def test_read_rejects_file_replacement_during_token_counting(self):
        client = BlockingCountingClient()
        self.agent.llm_client = client
        self.manager.register_llm_client("version-blocking", client)
        self.team.doc_library.write_file("changing.txt", "first version")

        agent_token = self.manager._active_tool_agent.set(self.agent)
        team_token = self.manager._active_team.set(self.team)
        try:
            read_task = asyncio.create_task(
                self.manager.read_library_file(
                    self.team.team_id,
                    self.team.doc_library.lib_id,
                    "changing.txt",
                )
            )
            await client.started.wait()
            await asyncio.to_thread(
                self.team.doc_library.write_file,
                "changing.txt",
                "a different second version",
            )
            client.release.set()
            with self.assertRaises(FileVersionChangedError):
                await read_task
        finally:
            self.manager._active_team.reset(team_token)
            self.manager._active_tool_agent.reset(agent_token)

    async def test_read_rejects_file_deletion_during_token_counting(self):
        client = BlockingCountingClient()
        self.agent.llm_client = client
        self.manager.register_llm_client("deletion-blocking", client)
        self.team.doc_library.write_file("deleted.txt", "temporary content")

        agent_token = self.manager._active_tool_agent.set(self.agent)
        team_token = self.manager._active_team.set(self.team)
        try:
            read_task = asyncio.create_task(
                self.manager.read_library_file(
                    self.team.team_id,
                    self.team.doc_library.lib_id,
                    "deleted.txt",
                )
            )
            await client.started.wait()
            await asyncio.to_thread(
                os.remove,
                os.path.join(self.team.doc_library.root_dir, "deleted.txt"),
            )
            client.release.set()
            with self.assertRaises(FileVersionChangedError):
                await read_task
        finally:
            self.manager._active_team.reset(team_token)
            self.manager._active_tool_agent.reset(agent_token)

    async def test_read_uses_one_consistent_file_read_config_snapshot(self):
        client = BlockingCountingClient()
        self.agent.llm_client = client
        self.manager.register_llm_client("config-blocking", client)
        self.manager.config.file_read.max_read_tokens = 5
        self.team.doc_library.write_file("snapshot.txt", "abcdefghij")

        agent_token = self.manager._active_tool_agent.set(self.agent)
        team_token = self.manager._active_team.set(self.team)
        try:
            read_task = asyncio.create_task(
                self.manager.read_library_file(
                    self.team.team_id,
                    self.team.doc_library.lib_id,
                    "snapshot.txt",
                )
            )
            await client.started.wait()
            self.manager.config.file_read.max_read_tokens = 1
            client.release.set()
            result = await read_task
        finally:
            self.manager._active_team.reset(team_token)
            self.manager._active_tool_agent.reset(agent_token)

        self.assertEqual(result.content, "abcde")
        self.assertEqual(result.max_read_tokens, 5)

    async def test_provider_counter_uses_effective_client_after_failover(self):
        original = CharacterCountingClient()
        replacement = WordCountingClient()
        self.agent.llm_client = original
        self.manager.register_llm_client("original", original)
        self.manager.register_llm_client("replacement", replacement)
        self.manager.config.model_token_limits.update(
            {"original": 0, "replacement": 100}
        )
        self.manager.config.file_read.max_read_tokens = 2
        self.team.doc_library.write_file("words.txt", "one two three four")

        first = await self.execute_read(
            "read_library_file",
            lib_id=self.team.doc_library.lib_id,
            path="words.txt",
        )
        error = TokenLimitExceededError("exhausted")
        error.required_tokens = 1
        self.assertTrue(
            await self.manager.handle_failover(self.agent, self.team, error)
        )
        second = await self.execute_read(
            "read_library_file",
            lib_id=self.team.doc_library.lib_id,
            path="words.txt",
        )

        first_payload = json.loads(first.content)
        second_payload = json.loads(second.content)
        self.assertEqual(first_payload["model_alias"], "original")
        self.assertEqual(first_payload["content"], "on")
        self.assertEqual(second_payload["model_alias"], "replacement")
        self.assertEqual(second_payload["content"], "one two ")
        self.assertEqual(self.agent._model_alias, "replacement")

    async def test_registered_tokenizer_precedes_provider_counter(self):
        tokenizer = Tokenizer(
            WordLevel(vocab={"[UNK]": 0, "hello": 1, "world": 2}, unk_token="[UNK]")
        )
        tokenizer.pre_tokenizer = Whitespace()
        tokenizer_path = os.path.join(self.temporary.name, "tokenizer.json")
        tokenizer.save(tokenizer_path)
        provider = CharacterCountingClient()
        self.agent.llm_client = provider
        self.manager.register_llm_client("exact", provider)
        self.manager.config.model_tokenizer_configs["exact"] = tokenizer_path
        self.manager.config.file_read.max_read_tokens = 2
        self.team.doc_library.write_file("exact.txt", "hello world")

        result = await self.execute_read(
            "read_library_file",
            lib_id=self.team.doc_library.lib_id,
            path="exact.txt",
        )
        payload = json.loads(result.content)

        self.assertEqual(payload["status"], FileReadStatus.COMPLETE.value)
        self.assertEqual(payload["content"], "hello world")
        self.assertEqual(payload["token_count_method"], "registered_tokenizer")
        self.assertFalse(payload["estimated"])

    async def test_strict_mode_and_invalid_ranges_are_structured_failures(self):
        self.manager.config.file_read.tokenizer_fallback = "strict"
        self.team.doc_library.write_file("strict.txt", "content")

        unavailable = await self.execute_read(
            "read_library_file",
            lib_id=self.team.doc_library.lib_id,
            path="strict.txt",
        )
        invalid = await self.execute_read(
            "read_library_file",
            lib_id=self.team.doc_library.lib_id,
            path="strict.txt",
            end_line=1,
            character_count=2,
        )

        self.assertEqual(unavailable.status, ToolResultStatus.BUSINESS_ERROR)
        self.assertEqual(unavailable.error_kind, "token_counter_unavailable")
        self.assertEqual(invalid.status, ToolResultStatus.INVALID_ARGUMENTS)
        self.assertEqual(invalid.error_kind, "invalid_file_range")

    async def test_decoding_failure_does_not_return_file_bytes(self):
        self.manager.register_token_counter("default", len)
        target = os.path.join(self.team.doc_library.root_dir, "invalid.txt")
        with open(target, "wb") as stream:
            stream.write(b"secret-prefix-\xff-secret-suffix")

        result = await self.execute_read(
            "read_library_file",
            lib_id=self.team.doc_library.lib_id,
            path="invalid.txt",
        )

        self.assertEqual(result.status, ToolResultStatus.BUSINESS_ERROR)
        self.assertEqual(result.error_kind, "file_decoding_error")
        self.assertNotIn("secret", result.content)


if __name__ == "__main__":
    unittest.main()
