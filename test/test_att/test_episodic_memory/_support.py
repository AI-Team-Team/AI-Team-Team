"""Fixtures for optional episodic-memory tests."""

import shutil
import tempfile
import unittest

from ai_team_team import ATTConfig, ATTManager, Agent, LLMResponse


class ScriptedMemoryClient:
    def __init__(self, responses=None, labels=None):
        self.responses = list(responses or ["Final Answer: complete"])
        self.labels = labels or {
            "title": "Completed work",
            "summary": "The Agent completed one recorded task.",
            "tags": ["work", "completed"],
        }
        self.calls = []

    async def generate(
        self,
        prompt,
        system_instruction=None,
        require_json=False,
        **kwargs,
    ):
        self.calls.append(
            {
                "prompt": prompt,
                "system_instruction": system_instruction,
                "require_json": require_json,
            }
        )
        if require_json:
            import json

            return LLMResponse(text=json.dumps(self.labels))
        if self.responses:
            return LLMResponse(text=self.responses.pop(0))
        return LLMResponse(text="Final Answer: complete")

    def supports_native_tool_calling(self):
        return False


class EpisodicMemoryTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="att-episodic-memory-")
        self.client = ScriptedMemoryClient()
        self.manager = ATTManager(
            Agent("Root", "Architect", self.client),
            ATTConfig(
                workspace_root=self.tmpdir,
                episodic_memory={
                    "enabled": True,
                    "index_retry_backoff_factor": 0.0,
                },
            ),
        )
        self.manager.register_llm_client("memory-model", self.client)
        self.team = self.manager.create_agent_team(
            self.manager.root_ai,
            member_count=3,
        )
        self.agent = self.team.members[0]

    async def asyncTearDown(self):
        await self.manager.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)
