import os
import sqlite3
from copy import deepcopy
from contextlib import closing

from ai_team_team import (
    ATTConfig,
    ATTManager,
    Agent,
    LLMResponse,
    StateRestoreError,
    ToolCall,
)

from test.test_att.test_episodic_memory._support import (
    EpisodicMemoryTestCase,
    ScriptedMemoryClient,
)
from ai_team_team.core.memory import SystemMemoryEvent
from ai_team_team.core.memory.sanitization import content_digest, render_recall_content




class TestPersistenceAndPrivacy(EpisodicMemoryTestCase):
    async def test_private_tool_body_never_enters_segment_or_card_metadata(self):
        secret = "SECRET-PRIVATE-BODY"
        self.client.responses = [
            f"Action: write_private_file(path='notes/private.txt', content={secret!r})",
            "Final Answer: Private work completed.",
        ]
        self.client.labels = {
            "title": "Private work",
            "summary": "A private file operation completed without copied body text.",
            "tags": ["private-work"],
        }
        await self.team.execute_reasoning_step_detailed(
            self.agent,
            "Store a private note.",
            "System.",
            manager=self.manager,
        )
        await self.manager.flush_memory_indexing()
        self.assertNotIn(secret, repr(self.manager._memory.snapshot()))
        self.assertNotIn(secret, repr(self.agent.messages))
        self.assertNotIn(secret, repr(self.agent.message_history))

    async def test_native_private_result_cannot_enter_persisted_memory(self):
        secret = "NATIVE-PRIVATE-SECRET"

        class NativePrivateClient(ScriptedMemoryClient):
            def __init__(self):
                super().__init__()
                self.native_responses = [
                    LLMResponse(
                        tool_calls=[
                            ToolCall(
                                call_id="read-private",
                                name="read_private_file",
                                arguments={"path": "notes/private.txt"},
                            )
                        ]
                    ),
                    LLMResponse(text=secret),
                ]

            async def generate(self, *args, require_json=False, **kwargs):
                if require_json:
                    return await super().generate(
                        *args,
                        require_json=True,
                        **kwargs,
                    )
                return self.native_responses.pop(0)

            def supports_native_tool_calling(self):
                return True

        client = NativePrivateClient()
        self.manager.register_llm_client("native-private", client)
        agent = Agent("NativePrivate", "Researcher", client)
        self.manager.register_agent(agent)
        self.team.members.append(agent)
        agent_token = self.manager._active_tool_agent.set(agent)
        team_token = self.manager._active_team.set(self.team)
        try:
            await self.manager.write_private_file("notes/private.txt", secret)
        finally:
            self.manager._active_team.reset(team_token)
            self.manager._active_tool_agent.reset(agent_token)
        self.manager.config.tool_calling_mode = "native"

        result = await self.team.execute_reasoning_step_detailed(
            agent,
            "Read the private note.",
            "System.",
            manager=self.manager,
        )
        await self.manager.flush_memory_indexing()

        self.assertEqual(result.answer, secret)
        self.assertNotIn(secret, repr(self.manager._memory.snapshot()))
        self.assertNotIn(secret, repr(agent.messages))
        self.assertNotIn(secret, repr(agent.message_history))

    async def test_custom_tool_content_requires_explicit_memory_capture_opt_in(self):
        metadata_only_body = "METADATA-ONLY-TOOL-BODY"
        captured_body = "EXPLICITLY-CAPTURED-TOOL-BODY"

        def metadata_tool():
            return metadata_only_body

        def captured_tool():
            return captured_body

        self.manager.register_tool("metadata_tool", "Metadata-only tool.", metadata_tool)
        self.client.responses = [
            "Action: metadata_tool()",
            "Final Answer: metadata tool completed",
        ]
        metadata_result = await self.team.execute_reasoning_step_detailed(
            self.agent,
            "Run the metadata-only tool.",
            "System.",
            manager=self.manager,
        )
        await self.manager.flush_memory_indexing()
        metadata_segment = next(
            item
            for item in self.manager._memory.segments.values()
            if item.turn_id == metadata_result.turn_id
        )
        self.assertNotIn(metadata_only_body, metadata_segment.recall_content)

        self.manager.register_tool(
            "captured_tool",
            "Content-capturing tool.",
            captured_tool,
            memory_capture="content",
        )
        self.client.responses = [
            "Action: captured_tool()",
            "Final Answer: captured tool completed",
        ]
        captured_result = await self.team.execute_reasoning_step_detailed(
            self.agent,
            "Run the explicitly captured tool.",
            "System.",
            manager=self.manager,
        )
        await self.manager.flush_memory_indexing()
        captured_segment = next(
            item
            for item in self.manager._memory.segments.values()
            if item.turn_id == captured_result.turn_id
        )
        self.assertIn(captured_body, captured_segment.recall_content)

    async def test_compression_cannot_capture_metadata_only_tool_content(self):
        marker = "METADATA-ONLY-COMPRESSION-BODY"
        summary_inputs = []
        original_generate = self.client.generate

        async def generate(
            prompt,
            system_instruction=None,
            require_json=False,
            **kwargs,
        ):
            if system_instruction == "You are a precise summarization assistant.":
                summary_inputs.append(str(prompt))
                return LLMResponse(
                    text=(
                        f"The lookup returned {marker}."
                        if marker in str(prompt)
                        else "Earlier work completed."
                    )
                )
            return await original_generate(
                prompt,
                system_instruction=system_instruction,
                require_json=require_json,
                **kwargs,
            )

        self.client.generate = generate
        self.manager.config.enable_memory_compression = True
        self.manager.config.max_memory_turns = 2

        def metadata_lookup():
            return marker

        self.manager.register_tool(
            "metadata_lookup",
            "Returns metadata-only content.",
            metadata_lookup,
        )
        self.client.responses = [
            "Action: metadata_lookup()",
            "Final Answer: lookup completed",
        ]
        await self.team.execute_reasoning_step_detailed(
            self.agent,
            "Look up the record.",
            "System.",
            manager=self.manager,
        )
        for prompt in ("Continue with another task.", "Continue again."):
            await self.team.execute_reasoning_step_detailed(
                self.agent,
                prompt,
                "System.",
                manager=self.manager,
            )
        await self.manager.flush_memory_indexing()

        self.assertTrue(summary_inputs)
        self.assertTrue(any(marker in item for item in summary_inputs))
        self.assertFalse(
            any(
                marker in str(event.payload)
                for event in self.manager._memory.events.values()
            )
        )
        self.assertFalse(
            any(
                marker in segment.recall_content
                for segment in self.manager._memory.segments.values()
            )
        )

        db_path = os.path.join(self.tmpdir, "compression-capture.db")
        await self.manager.save_state(db_path)
        with closing(sqlite3.connect(db_path)) as connection:
            persisted_events = connection.execute(
                "SELECT COUNT(*) FROM system_memory_events "
                "WHERE instr(payload, ?) > 0",
                (marker,),
            ).fetchone()[0]
            persisted_segments = connection.execute(
                "SELECT COUNT(*) FROM agent_memory_segments "
                "WHERE instr(recall_content, ?) > 0",
                (marker,),
            ).fetchone()[0]
        self.assertEqual(persisted_events, 0)
        self.assertEqual(persisted_segments, 0)


